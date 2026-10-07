"""Durable goal identity, independent of conversation storage and lifecycle.

This is state storage for the existing agent, not an execution service. Sessions
carry a projection; only this store owns the responsibility and its lifecycle.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from pathlib import Path
from typing import Literal, cast
from uuid import NAMESPACE_URL, uuid4, uuid5

from filelock import FileLock
from pydantic import BaseModel, ConfigDict, Field

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
    version: Literal[1] = 1
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
    last_wake_ms: int | None = None
    checkpoint: ResponsibilityCheckpoint = Field(default_factory=ResponsibilityCheckpoint)
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


class ResponsibilityStore:
    """Workspace-scoped records, using Nanobot's locked atomic JSON persistence."""

    def __init__(self, workspace: Path):
        self.root = workspace / "responsibilities"
        self._lock = FileLock(str(self.root / ".lock"))

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
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock:
            if legacy_key and self._path(record.id).exists():
                return self.get(record.id)
            self._write(record)
        return record

    def save(self, record: Responsibility) -> Responsibility:
        """Reject stale updates rather than silently losing a wake or checkpoint."""
        with self._lock:
            current = self.get(record.id)
            if current.revision != record.revision:
                raise ValueError("Responsibility changed; reload before updating")
            if current.state in TERMINAL_STATES and record != current:
                raise ValueError("Finished responsibilities cannot be changed")
            record = record.model_copy(deep=True)
            record.revision += 1
            record.updated_at_ms = int(time.time() * 1000)
            self._write(record)
        return record

    def _write(self, record: Responsibility) -> None:
        atomic_write_lines(self._path(record.id), [record.model_dump_json() + "\n"], fsync=True)

    def enqueue(self, responsibility_id: str, wake_id: str, content: str) -> bool:
        """Persist receipt before acknowledging an upstream delivery."""
        with self._lock:
            record = self.get(responsibility_id)
            if wake_id in record.wakes or record.state in TERMINAL_STATES:
                return False
            record.wakes[wake_id] = WakeReceipt(content=content[:8000])
            self.save(record)
            return True

    def claim(self, responsibility_id: str, wake_id: str) -> Responsibility | None:
        """One atomic admission across processes; never replay a started wake."""
        with self._lock:
            record = self.get(responsibility_id)
            wake = record.wakes.get(wake_id)
            if (wake is not None and wake.state == "QUEUED" and wake_id.startswith("schedule:")
                    and wake_id != f"schedule:{record.wake_generation}:{record.next_wake_ms}"):
                wake.state = "DISCARDED"
                self.save(record)
                return None
            if (wake is None or wake.state != "QUEUED" or record.active_wake_id
                    or record.state in TERMINAL_STATES | {"PAUSED", "WAITING_FOR_USER"}
                    or record.recovery_required):
                return None
            wake.state = "STARTED"
            wake.attempts += 1
            wake.started_at_ms = int(time.time() * 1000)
            record.active_wake_id = wake_id
            record.last_wake_ms = wake.started_at_ms
            record.next_wake_ms = None
            record.state = "RUNNING"
            return self.save(record)

    def finish(self, responsibility_id: str, wake_id: str, *, uncertain: bool = False) -> None:
        with self._lock:
            record = self.get(responsibility_id)
            if record.active_wake_id != wake_id:
                return
            receipt = record.wakes[wake_id]
            receipt.state = "UNCERTAIN" if uncertain else "COMPLETED"
            receipt.finished_at_ms = int(time.time() * 1000)
            record.active_wake_id = None
            record.recovery_required = uncertain
            if uncertain and record.state not in TERMINAL_STATES:
                record.state = "PAUSED"
            elif record.state == "RUNNING":
                record.state = "WAITING"
            # Finalization also applies if a goal tool completed the objective.
            record.revision += 1
            self._write(record)

    def recover(self) -> list[str]:
        """Called only after gateway execution ownership has been acquired."""
        recovered: list[str] = []
        if not self.root.exists():
            return recovered
        with self._lock:
            for record in self.list():
                if record.active_wake_id:
                    self.finish(record.id, record.active_wake_id, uncertain=True)
                    recovered.append(record.id)
                elif (record.checkpoint.pending_tools and not record.recovery_required
                      and record.state not in TERMINAL_STATES):
                    record.recovery_required = True
                    if record.state not in TERMINAL_STATES:
                        record.state = "PAUSED"
                    record.revision += 1
                    self._write(record)
                    recovered.append(record.id)
        return recovered

    def checkpoint_tools(self, responsibility_id: str, payload: Mapping[str, object],
                         session_key: str) -> None:
        """Project runner checkpoint IDs, excluding prompts, secrets and reasoning."""
        with self._lock:
            record = self.get(responsibility_id)
            if record.state in TERMINAL_STATES:
                return
            pending = payload.get("pending_tool_calls", [])
            completed = payload.get("completed_tool_results", [])
            record.checkpoint.pending_tools = _checkpoint_ids(pending, "id")
            for tool_id in _checkpoint_ids(completed, "tool_call_id"):
                ref = f"session:{session_key}:tool:{tool_id}"
                if ref not in record.checkpoint.result_refs:
                    record.checkpoint.result_refs.append(ref)
            self.save(record)


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
