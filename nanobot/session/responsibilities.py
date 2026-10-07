"""Durable goal identity, independent of conversation storage and lifecycle.

This is state storage for the existing agent, not an execution service. Sessions
carry a projection; only this store owns the responsibility and its lifecycle.
"""

from __future__ import annotations

import hashlib
import secrets
import time
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Literal, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field

from nanobot.security.runtime_storage import internal_state_root
from nanobot.session.wake_schedule import WakeSchedule
from nanobot.utils.helpers import atomic_write_lines

ResponsibilityState = Literal[
    "QUEUED", "RUNNING", "WAITING", "WAITING_FOR_USER", "WAITING_FOR_EVENT",
    "WAITING_FOR_SUBAGENT", "SCHEDULED", "PAUSED", "COMPLETED", "FAILED", "CANCELLED",
]
TERMINAL_STATES = {"COMPLETED", "FAILED", "CANCELLED"}


class ResponsibilityCheckpoint(BaseModel):
    """Operational facts only; never a model's reasoning transcript."""

    model_config = ConfigDict(extra="forbid")
    completed_steps: list[str] = Field(default_factory=list)
    pending_work: list[str] = Field(default_factory=list)
    result_refs: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    pending_tools: list[str] = Field(default_factory=list)


class WakeReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["QUEUED", "STARTED", "COMPLETED", "UNCERTAIN", "DISCARDED"] = "QUEUED"
    content: str = ""
    attempts: int = 0
    started_at_ms: int | None = None
    finished_at_ms: int | None = None


class Responsibility(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1, 2, 3, 4] = 4
    id: str = Field(pattern=r"^resp_[0-9a-f]{32}$")
    revision: int = 0
    objective: str = Field(min_length=1, max_length=4000)
    ui_summary: str = ""
    state: ResponsibilityState = "QUEUED"
    progress: str = ""
    session_key: str | None = None
    channel: str = ""
    chat_id: str = ""
    workspace_scope: dict[str, str] = Field(default_factory=dict)
    waiting_for: str | None = None
    next_wake_ms: int | None = None
    schedule: WakeSchedule | None = None
    last_wake_ms: int | None = None
    checkpoint: ResponsibilityCheckpoint = Field(default_factory=ResponsibilityCheckpoint)
    parent_responsibility_id: str | None = None
    parent_execution_generation: int | None = None
    delegation_id: str | None = None
    result_summary: str = ""
    delivery_needed: bool = False
    execution_generation: int = 0
    execution_token: str | None = None
    wake_generation: int = 0
    wakes: dict[str, WakeReceipt] = Field(default_factory=dict)
    active_wake_id: str | None = None
    recovery_required: bool = False
    created_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000))
    updated_at_ms: int = Field(default_factory=lambda: int(time.time() * 1000))

    def goal_projection(self) -> dict[str, object]:
        status = "active" if self.state in {"QUEUED", "RUNNING"} else "blocked"
        if self.state in TERMINAL_STATES:
            status = self.state.lower()
        return {
            "responsibility_id": self.id, "status": status,
            "objective": self.objective, "ui_summary": self.ui_summary,
            "recap": self.progress, "responsibility_state": self.state,
        }


class ExecutionClaim(BaseModel):
    """Immutable backend capability; never put it in a prompt or tool argument."""

    model_config = ConfigDict(extra="forbid", frozen=True)
    responsibility_id: str
    wake_id: str
    generation: int
    token: str


class StaleExecutionError(ValueError):
    """The caller no longer owns this execution, even after reloading state."""


class ResponsibilityStore:
    """Protected records for the existing goal runtime; no scheduler or workers."""

    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        namespace = hashlib.sha256(str(self.workspace).encode()).hexdigest()
        self.root = internal_state_root(create=True) / "responsibilities" / namespace
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = FileLock(str(self.root / ".lock"))
        self.on_change: Callable[[], None] | None = None

    def _path(self, responsibility_id: str) -> Path:
        import re
        if re.fullmatch(r"resp_[0-9a-f]{32}", responsibility_id) is None:
            raise ValueError("Invalid responsibility ID")
        return self.root / f"{responsibility_id}.json"

    def get(self, responsibility_id: str) -> Responsibility:
        return Responsibility.model_validate_json(self._path(responsibility_id).read_text())

    def list(self) -> list[Responsibility]:
        return [Responsibility.model_validate_json(p.read_text())
                for p in sorted(self.root.glob("resp_*.json"))]

    def create(self, *, objective: str, session_key: str | None,
               channel: str, chat_id: str, ui_summary: str = "",
               legacy_key: str | None = None,
               workspace_scope: dict[str, str] | None = None) -> Responsibility:
        identity = uuid5(NAMESPACE_URL, legacy_key) if legacy_key else uuid4()
        record = Responsibility(id=f"resp_{identity.hex}", objective=objective,
                                session_key=session_key, channel=channel,
                                chat_id=chat_id, ui_summary=ui_summary,
                                workspace_scope=workspace_scope or {})
        with self._lock:
            if legacy_key and self._path(record.id).exists():
                return self.get(record.id)
            self._write(record)
        return record

    def assert_owner(self, claim: ExecutionClaim) -> Responsibility:
        record = self.get(claim.responsibility_id)
        if (record.execution_generation != claim.generation
                or record.execution_token != claim.token
                or record.active_wake_id != claim.wake_id):
            raise StaleExecutionError("Stale responsibility execution ownership")
        return record

    def save(self, record: Responsibility, *, claim: ExecutionClaim) -> Responsibility:
        """All execution writes require the originally claimed immutable token."""
        with self._lock:
            current = self.assert_owner(claim)
            if record.id != claim.responsibility_id:
                raise StaleExecutionError("Claim belongs to another responsibility")
            self._check_revision(record, current)
            if current.state in TERMINAL_STATES and record != current:
                raise ValueError("Finished responsibilities cannot be changed")
            # Ownership is backend-owned, not supplied by a mutable record.
            if (record.execution_generation != current.execution_generation
                    or record.execution_token != current.execution_token
                    or record.active_wake_id != current.active_wake_id):
                raise StaleExecutionError("Execution cannot change its own ownership")
            return self._commit(record)

    @staticmethod
    def _check_revision(record: Responsibility, current: Responsibility) -> None:
        if current.revision != record.revision:
            raise ValueError("Responsibility changed; reload before updating")

    def control_update(self, record: Responsibility) -> Responsibility:
        """Trusted lifecycle operations invalidate an interrupted worker first.

        Only gateway migration/deletion use this path; it is not a model tool.
        """
        with self._lock:
            current = self.get(record.id)
            self._check_revision(record, current)
            if current.active_wake_id:
                self._interrupt(record)
            return self._commit(record)

    def _commit(self, record: Responsibility) -> Responsibility:
        record = record.model_copy(deep=True)
        record.version = 4
        record.revision += 1
        record.updated_at_ms = int(time.time() * 1000)
        self._write(record)
        return record

    def _write(self, record: Responsibility) -> None:
        atomic_write_lines(self._path(record.id), [record.model_dump_json() + "\n"], fsync=True)
        self._path(record.id).chmod(0o600)
        if self.on_change is not None:
            self.on_change()

    def enqueue(self, responsibility_id: str, wake_id: str, content: str) -> bool:
        """Persist receipt before acknowledging an upstream delivery."""
        with self._lock:
            record = self.get(responsibility_id)
            if wake_id in record.wakes or record.state in TERMINAL_STATES:
                return False
            record.wakes[wake_id] = WakeReceipt(content=content[:8000])
            self._commit(record)
            return True

    def claim(self, responsibility_id: str, wake_id: str) -> ExecutionClaim | None:
        """Atomic admission; a STARTED receipt is never automatically replayed."""
        with self._lock:
            record = self.get(responsibility_id)
            wake = record.wakes.get(wake_id)
            if (wake is not None and wake.state == "QUEUED" and wake_id.startswith("schedule:")
                    and wake_id != f"schedule:{record.wake_generation}:{record.next_wake_ms}"):
                wake.state = "DISCARDED"
                self._commit(record)
                return None
            if (wake is None or wake.state != "QUEUED" or record.active_wake_id
                    or record.state in TERMINAL_STATES | {"PAUSED", "WAITING_FOR_USER"}
                    or record.recovery_required or record.delivery_needed):
                return None
            wake.state = "STARTED"
            wake.attempts += 1
            wake.started_at_ms = int(time.time() * 1000)
            record.last_wake_ms = wake.started_at_ms
            record.next_wake_ms = None
            record.state = "RUNNING"
            return self._own(record, wake_id)

    def _own(self, record: Responsibility, wake_id: str, *, advance_generation: bool = True) -> ExecutionClaim:
        if advance_generation:
            record.execution_generation += 1
        record.execution_token = secrets.token_hex(32)
        record.active_wake_id = wake_id
        self._commit(record)
        return ExecutionClaim(responsibility_id=record.id, wake_id=wake_id,
                              generation=record.execution_generation, token=record.execution_token)

    def claim_foreground(self, responsibility_id: str) -> ExecutionClaim:
        """A chat turn may manage waiting goals, but cannot steal a running turn."""
        with self._lock:
            record = self.get(responsibility_id)
            if record.active_wake_id:
                raise StaleExecutionError("Responsibility already has an execution owner")
            wake_id = f"turn:{uuid4().hex}"
            record.wakes[wake_id] = WakeReceipt(state="STARTED", attempts=1,
                                              started_at_ms=int(time.time() * 1000))
            return self._own(record, wake_id)

    def takeover(self, responsibility_id: str) -> ExecutionClaim:
        """Explicit trusted takeover, never an automatic retry of external work."""
        with self._lock:
            record = self.get(responsibility_id)
            self._interrupt(record)
            wake_id = f"takeover:{uuid4().hex}"
            record.wakes[wake_id] = WakeReceipt(state="STARTED", attempts=1,
                                              started_at_ms=int(time.time() * 1000))
            return self._own(record, wake_id, advance_generation=False)

    def finish(self, claim: ExecutionClaim, *, uncertain: bool = False) -> None:
        with self._lock:
            record = self.assert_owner(claim)
            receipt = record.wakes[claim.wake_id]
            receipt.state = "UNCERTAIN" if uncertain else "COMPLETED"
            receipt.finished_at_ms = int(time.time() * 1000)
            record.active_wake_id = None
            record.execution_token = None
            if uncertain:
                record.execution_generation += 1
                record.recovery_required = True
                if record.state not in TERMINAL_STATES:
                    record.state = "PAUSED"
            elif record.state == "RUNNING":
                record.state = "WAITING"
            if not uncertain and record.state == "WAITING" and record.schedule:
                record.next_wake_ms = record.schedule.next_after(int(time.time() * 1000))
                if record.next_wake_ms is not None:
                    record.state = "SCHEDULED"
            self._commit(record)

    @staticmethod
    def _interrupt(record: Responsibility) -> None:
        if record.active_wake_id:
            wake = record.wakes[record.active_wake_id]
            wake.state = "UNCERTAIN"
            wake.finished_at_ms = int(time.time() * 1000)
        record.execution_generation += 1
        record.execution_token = None
        record.active_wake_id = None
        record.recovery_required = True
        if record.state not in TERMINAL_STATES:
            record.state = "PAUSED"

    def recover(self) -> list[str]:
        """Only after exclusive gateway ownership: invalidate all old claims."""
        recovered: list[str] = []
        with self._lock:
            for record in self.list():
                if (record.active_wake_id or (record.checkpoint.pending_tools
                        and not record.recovery_required and record.state not in TERMINAL_STATES)):
                    self._interrupt(record)
                    self._commit(record)
                    recovered.append(record.id)
        return recovered

    def checkpoint_tools(self, claim: ExecutionClaim, payload: Mapping[str, object],
                         session_key: str) -> None:
        """Project tool IDs only. Validate ownership even for a terminal record."""
        with self._lock:
            record = self.assert_owner(claim)
            pending = payload.get("pending_tool_calls", [])
            completed = payload.get("completed_tool_results", [])
            record.checkpoint.pending_tools = _checkpoint_ids(pending, "id")
            for tool_id in _checkpoint_ids(completed, "tool_call_id"):
                ref = f"session:{session_key}:tool:{tool_id}"
                if ref not in record.checkpoint.result_refs:
                    record.checkpoint.result_refs.append(ref)
            # Final runner checkpoint may follow the model's completion tool.
            self._commit(record)

    def delivery_missing(self, responsibility_id: str) -> None:
        with self._lock:
            record = self.get(responsibility_id)
            if not record.delivery_needed:
                record.delivery_needed = True
                self._commit(record)

    def unlink_session(self, session_key: str) -> None:
        with self._lock:
            for record in self.list():
                if record.session_key == session_key and record.state not in TERMINAL_STATES:
                    record.delivery_needed = True
                    if record.active_wake_id:
                        self._interrupt(record)
                    self._commit(record)

    def migrate_workspace_records(self) -> None:
        """One-time trusted relocation of the previous draft, with protected backup.

        Never overwrite an already migrated record. Retire the agent-writable
        copy after the protected record and backup have reached durable storage.
        """
        legacy = self.workspace / "responsibilities"
        if not legacy.exists():
            return
        with FileLock(str(legacy / ".lock")), self._lock:
            backup = self.root / "legacy-backup"
            backup.mkdir(mode=0o700, exist_ok=True)
            for path in sorted(legacy.glob("resp_*.json")):
                text = path.read_text()
                record = Responsibility.model_validate_json(text)
                atomic_write_lines(backup / path.name, [text], fsync=True)
                (backup / path.name).chmod(0o600)
                if not self._path(record.id).exists():
                    record.version = 4
                    if record.active_wake_id or record.checkpoint.pending_tools:
                        self._interrupt(record)
                    self._write(record)
                path.unlink()
            # Keep unrelated user files; no recursive deletion of workspace data.

def _checkpoint_ids(value: object, field: str) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for row in cast(list[object], value):
        if isinstance(row, dict):
            identifier = cast(dict[str, object], row).get(field)
            if isinstance(identifier, str) and identifier:
                result.append(identifier)
    return result
