"""Sustained-goal tools with explicit user opt-in at the execution boundary."""

# pyright: reportIncompatibleMethodOverride=false

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING, Any

from nanobot.agent.goal_permission import (
    goal_mutation_allowed,
    revoke_goal_mutation_permission,
)
from nanobot.agent.tools.base import Tool, ToolResult, tool_parameters
from nanobot.agent.tools.context import (
    RequestContext,
    ResponsibilityExecution,
    ToolContext,
    current_request_context,
)
from nanobot.agent.tools.schema import IntegerSchema, StringSchema, tool_parameters_schema
from nanobot.bus.queue import MessageBus
from nanobot.bus.runtime_events import GoalStateChanged, RuntimeEventContext
from nanobot.runtime_context import RuntimeContextBlock, wrap_runtime_context_lines
from nanobot.session.goal_state import (
    GOAL_STATE_KEY,
    MAX_GOAL_OBJECTIVE_CHARS,
    discard_legacy_goal_state_key,
    explicit_goal_requested,
    goal_state_raw,
    goal_state_runtime_lines,
    parse_goal_state,
    sustained_goal_active,
)
from nanobot.session.responsibilities import (
    TERMINAL_STATES,
    ExecutionClaim,
    ResponsibilityCheckpoint,
    ResponsibilityState,
    StaleExecutionError,
)
from nanobot.session.turn_continuation import reset_goal_continuation_rounds
from nanobot.utils.prompt_templates import render_template

if TYPE_CHECKING:
    from nanobot.session.manager import SessionManager


_GOAL_ACTIONS = ("complete", "cancel", "block", "replace", "list", "checkpoint", "wait", "pause", "resume", "bind")
_CREATE_UNAVAILABLE_ERROR = (
    "Error: create_goal is unavailable for this turn. Ask the user to submit the complete "
    "objective as `/goal <task>`."
)
_REPLACE_UNAVAILABLE_ERROR = (
    "Error: replacing the goal is unavailable for this turn. Ask the user to submit the "
    "replacement objective as `/goal <task>`."
)


def _iso_now() -> str:
    return datetime.now().isoformat()


class _GoalToolsMixin:
    """Shared routing context and session lookup."""

    def __init__(
        self,
        sessions: SessionManager,
        bus: MessageBus | None = None,
    ) -> None:
        self._sessions = sessions
        self._bus = bus

    def _session(self):
        request_ctx = current_request_context()
        if request_ctx is None:
            return None
        if request_ctx.responsibility_scope.closed:
            raise StaleExecutionError("Responsibility execution scope has ended")
        key = request_ctx.session_key
        if not key:
            return None
        if request_ctx.responsibility_scope.executions:
            return self._sessions.get_existing(key)
        return self._sessions.get_or_create(key)

    def _goal_mutation_allowed(self) -> bool:
        return current_request_context() is not None and goal_mutation_allowed()

    def _execution_claim(self, responsibility_id: str) -> ExecutionClaim:
        rc = current_request_context()
        if rc is None:
            raise RuntimeError("Responsibility execution requires backend request context")
        if rc.responsibility_scope.closed:
            raise StaleExecutionError("Responsibility execution scope has ended")
        if responsibility_id not in rc.responsibility_scope.executions:
            store = self._sessions.responsibilities
            claim = store.claim_foreground(responsibility_id)
            rc.responsibility_scope.executions[responsibility_id] = ResponsibilityExecution(store, claim)
        return rc.responsibility_scope.executions[responsibility_id].claim

    def _save_goal_state(
        self,
        sess: Any,
        blob: dict[str, Any],
        *,
        reset_continuation: bool = False,
    ) -> None:
        previous_metadata = deepcopy(sess.metadata)
        rc = current_request_context()
        store = self._sessions.responsibilities
        responsibility_id = blob.get("responsibility_id")
        if responsibility_id:
            claim = self._execution_claim(responsibility_id)
            record = store.assert_owner(claim)
        else:
            from nanobot.security.workspace_access import current_workspace_scope
            scope = current_workspace_scope()
            record = store.create(
                objective=blob["objective"], ui_summary=blob.get("ui_summary", ""),
                session_key=sess.key, channel=rc.channel if rc else "",
                chat_id=rc.chat_id if rc else "",
                workspace_scope=scope.metadata() if scope else None,
            )
        claim = self._execution_claim(record.id)
        record = store.assert_owner(claim)
        if reset_continuation and responsibility_id:
            record.wake_generation += 1
            record.next_wake_ms = None
            record.schedule = None
            record.waiting_for = None
        record.objective = blob["objective"]
        record.ui_summary = blob.get("ui_summary", "")
        record.progress = blob.get("recap", "")
        states: dict[str, ResponsibilityState] = {"active": "QUEUED", "blocked": "WAITING_FOR_USER",
                        "completed": "COMPLETED", "cancelled": "CANCELLED"}
        record.state = states[blob["status"]]
        record = store.save(record, claim=self._execution_claim(record.id))
        blob = {**blob, **record.goal_projection()}
        sess.metadata[GOAL_STATE_KEY] = blob
        discard_legacy_goal_state_key(sess.metadata)
        if reset_continuation:
            reset_goal_continuation_rounds(sess.metadata)
        try:
            self._sessions.save(sess, fsync=True)
        except BaseException:
            sess.metadata.clear()
            sess.metadata.update(previous_metadata)
            raise

    async def _publish_goal_state_changed(self, metadata: dict[str, Any]) -> None:
        bus = self._bus
        rc = current_request_context()
        if bus is None or rc is None:
            return
        cid = (rc.chat_id or "").strip()
        if not cid:
            return
        await bus.publish(
            GoalStateChanged(
                context=RuntimeEventContext(
                    channel=rc.channel,
                    chat_id=cid,
                    session_key=rc.session_key or f"{rc.channel}:{cid}",
                    metadata=dict(rc.metadata or {}),
                ),
                session_metadata=dict(metadata),
            )
        )


@tool_parameters(
    tool_parameters_schema(
        objective=StringSchema(
            "The sustained objective for this session. It may consolidate a plan from earlier "
            "discussion, but must be self-contained, bounded, safe under repetition, and "
            "explicit about done-ness.",
            min_length=1,
            max_length=MAX_GOAL_OBJECTIVE_CHARS,
        ),
        ui_summary=StringSchema(
            "Optional one-line display label for session lists and logs. It is not load-bearing.",
            max_length=120,
            nullable=True,
        ),
        required=["objective"],
    )
)
class CreateGoalTool(Tool, _GoalToolsMixin):
    """Create one explicit sustained objective for the current session."""

    def __init__(
        self,
        sessions: SessionManager,
        bus: MessageBus | None = None,
    ) -> None:
        _GoalToolsMixin.__init__(self, sessions, bus)

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        sess = ctx.sessions
        if sess is None:
            raise RuntimeError("CreateGoalTool requires an initialized session manager")
        return cls(
            sessions=sess,
            bus=ctx.bus,
        )

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.sessions is not None

    @property
    def name(self) -> str:
        return "create_goal"

    @property
    def description(self) -> str:
        return (
            "Create one sustained goal for the current session when Goal Runtime Guidance asks "
            "you to record it. Consolidate relevant prior discussion into a durable objective "
            "that is self-contained, bounded, safe under repetition, and explicit about "
            "completion criteria. Do not retry after a successful creation."
        )

    def runtime_context_provider(self):
        return self._provide_runtime_context

    async def _provide_runtime_context(
        self,
        request: RequestContext,
    ) -> RuntimeContextBlock | None:
        if not request.session_key:
            return None
        session = self._sessions.get_or_create(request.session_key)
        prior = parse_goal_state(goal_state_raw(session.metadata))
        record = None
        if prior and prior.get("responsibility_id"):
            record = self._sessions.responsibilities.get(prior["responsibility_id"])
            session.metadata[GOAL_STATE_KEY] = {**prior, **record.goal_projection()}
        goal_start_requested = explicit_goal_requested(request.metadata)
        goal_active = sustained_goal_active(session.metadata)
        if not goal_start_requested and not goal_active and not (prior and prior.get("responsibility_id")):
            return None

        guidance = render_template(
            "agent/goal_runtime.md",
            strip=True,
            goal_start_requested=goal_start_requested,
            goal_active=goal_active,
        )
        state = wrap_runtime_context_lines(goal_state_runtime_lines(session.metadata))
        if record is not None:
            state += "\n" + json.dumps(record.model_dump(mode="json", exclude={"wakes", "execution_token"}), ensure_ascii=False)
        content = "\n\n".join(part for part in (guidance, state) if part)
        return RuntimeContextBlock(source="goal", content=content)

    async def execute(
        self,
        objective: str,
        ui_summary: str | None = None,
        **kwargs: Any,
    ) -> str:
        sess = self._session()
        if sess is None:
            return ToolResult.error(
                "Error: create_goal requires an active chat session (missing routing context)."
            )
        rc = current_request_context()
        if not sess.policy.persist or (rc is not None and not rc.persist_session):
            return ToolResult.error("Error: durable goals require a persistent conversation.")
        if not self._goal_mutation_allowed():
            return ToolResult.error(_CREATE_UNAVAILABLE_ERROR)
        prior = parse_goal_state(goal_state_raw(sess.metadata))
        if isinstance(prior, dict) and prior.get("status") == "active":
            return ToolResult.error(
                "Error: a sustained goal is already active. Use update_goal with "
                "action='replace' only if the user explicitly changes the objective."
            )

        objective_text = objective.strip()
        if not objective_text:
            return ToolResult.error("Error: objective must not be empty.")
        if len(objective_text) > MAX_GOAL_OBJECTIVE_CHARS:
            return ToolResult.error(
                f"Error: objective must not exceed {MAX_GOAL_OBJECTIVE_CHARS} characters."
            )
        summary = (ui_summary or "").strip()[:120]
        blob = {
            "status": "active",
            "objective": objective_text,
            "ui_summary": summary,
            "started_at": _iso_now(),
        }
        self._save_goal_state(sess, blob, reset_continuation=True)
        await self._publish_goal_state_changed(sess.metadata)
        extra = f"\nSummary line: {summary}" if summary else ""
        return (
            "Goal recorded. Keep working toward the objective using ordinary tools. "
            "When fully done and verified, call update_goal with action='complete'."
            f"\nResponsibility ID: {sess.metadata[GOAL_STATE_KEY]['responsibility_id']}"
            f"{extra}"
        )


@tool_parameters(
    tool_parameters_schema(
        action=StringSchema(
            "How to update the active goal.",
            enum=_GOAL_ACTIONS,
        ),
        recap=StringSchema(
            "Brief honest recap for the user. Required in practice for complete, cancel, and block.",
            max_length=8000,
            nullable=True,
        ),
        objective=StringSchema(
            "Replacement objective. Required only when action is 'replace'; make it durable, "
            "self-contained, bounded, and explicit about done-ness.",
            max_length=MAX_GOAL_OBJECTIVE_CHARS,
            nullable=True,
        ),
        ui_summary=StringSchema(
            "Optional one-line display label for a replacement goal.",
            max_length=120,
            nullable=True,
        ),
        responsibility_id=StringSchema("Stable responsibility ID; use list to find goals after chat reset.", nullable=True),
        schedule_json=StringSchema("User schedule JSON: kind at/after/every/cron with at_ms, delay_ms, every_ms or expr/tz. Used with wait; recurrence is durable.", nullable=True),
        next_wake_ms=IntegerSchema(description="UTC Unix milliseconds for a scheduled wake. Used with wait.", nullable=True),
        waiting_for=StringSchema("Event condition, or 'user'. Used with wait; event wakes use a local trigger bound to this ID.", nullable=True),
        checkpoint_json=StringSchema("JSON object with completed_steps, pending_work, result_refs and artifacts arrays. Operational facts only; no hidden reasoning.", nullable=True),
        required=["action"],
    )
)
class UpdateGoalTool(Tool, _GoalToolsMixin):
    """Complete, cancel, block, or replace the active sustained goal."""

    def __init__(
        self,
        sessions: SessionManager,
        bus: MessageBus | None = None,
    ) -> None:
        _GoalToolsMixin.__init__(self, sessions, bus)

    @classmethod
    def create(cls, ctx: ToolContext) -> Tool:
        sess = ctx.sessions
        if sess is None:
            raise RuntimeError("UpdateGoalTool requires an initialized session manager")
        return cls(
            sessions=sess,
            bus=ctx.bus,
        )

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.sessions is not None

    @property
    def name(self) -> str:
        return "update_goal"

    @property
    def description(self) -> str:
        return (
            "Update the active sustained goal. Use action='complete' only after the objective "
            "is actually achieved and verified. Use action='cancel' when the user cancels, "
            "action='block' when progress is genuinely blocked, and action='replace' only when "
            "the requested objective changes."
        )

    async def execute(
        self,
        action: str,
        recap: str | None = None,
        objective: str | None = None,
        ui_summary: str | None = None,
        responsibility_id: str | None = None,
        next_wake_ms: int | None = None,
        schedule_json: str | None = None,
        waiting_for: str | None = None,
        checkpoint_json: str | None = None,
        **kwargs: Any,
    ) -> str:
        sess = self._session()
        if sess is None:
            return ToolResult.error("Error: update_goal requires an active chat session.")
        rc = current_request_context()
        if not sess.policy.persist or (rc is not None and not rc.persist_session):
            return ToolResult.error("Error: durable goals require a persistent conversation.")
        store = self._sessions.responsibilities
        if action == "list":
            return json.dumps([r.model_dump(mode="json", exclude={"execution_token"}) for r in store.list()], ensure_ascii=False)
        prior = parse_goal_state(goal_state_raw(sess.metadata))
        responsibility_id = responsibility_id or (prior or {}).get("responsibility_id")
        if responsibility_id:
            record = store.get(responsibility_id)
            prior = {**(prior or {}), **record.goal_projection()}
            if action in {"checkpoint", "wait", "pause", "resume", "bind"}:
                if record.recovery_required and action == "resume" and not self._goal_mutation_allowed():
                    return ToolResult.error("Error: reconcile interrupted work and obtain explicit user /goal authorization before resuming.")
                claim = self._execution_claim(record.id)
                record = store.assert_owner(claim)
                if record.state in TERMINAL_STATES:
                    return ToolResult.error("Error: responsibility is already finished.")
                if checkpoint_json is not None:
                    checkpoint = ResponsibilityCheckpoint.model_validate_json(checkpoint_json)
                    if checkpoint.pending_tools:
                        return ToolResult.error("Error: pending tool ownership is managed by the runtime.")
                    checkpoint.pending_tools = record.checkpoint.pending_tools
                    record.checkpoint = checkpoint
                if recap is not None:
                    record.progress = recap.strip()[:8000]
                if action == "wait":
                    import time

                    from nanobot.session.wake_schedule import WakeSchedule
                    record.schedule = WakeSchedule.model_validate_json(schedule_json) if schedule_json else None
                    if record.schedule:
                        next_wake_ms = record.schedule.first(int(time.time() * 1000))
                    if next_wake_ms is None and not waiting_for:
                        return ToolResult.error("Error: wait requires next_wake_ms or waiting_for.")
                    record.next_wake_ms = next_wake_ms
                    record.wake_generation += 1
                    record.waiting_for = waiting_for
                    record.state = "SCHEDULED" if next_wake_ms is not None else (
                        "WAITING_FOR_USER" if waiting_for == "user" else (
                            "WAITING_FOR_SUBAGENT" if waiting_for and waiting_for.startswith("subagent:")
                            else "WAITING_FOR_EVENT"))
                elif action == "pause":
                    record.state = "PAUSED"
                    record.next_wake_ms = None
                elif action == "resume":
                    if record.recovery_required and not self._goal_mutation_allowed():
                        return ToolResult.error("Error: interrupted work may have external effects. Reconcile first; explicit user /goal authorization is required to resume. No interrupted tool is replayed automatically.")
                    record.state = "SCHEDULED"
                    import time
                    record.next_wake_ms = int(time.time() * 1000)
                    record.waiting_for = None
                    record.wake_generation += 1
                    record.recovery_required = False
                    record.checkpoint.pending_tools = []
                elif action == "bind":
                    rc = current_request_context()
                    assert rc is not None
                    record.session_key, record.channel, record.chat_id = sess.key, rc.channel, rc.chat_id
                    record.delivery_needed = False
                record = store.save(record, claim=self._execution_claim(record.id))
                trigger_note = ""
                if action == "wait" and record.state == "WAITING_FOR_EVENT":
                    from nanobot.session.responsibility_turns import RESPONSIBILITY_TRIGGER_META
                    from nanobot.triggers.local_store import LocalTriggerStore
                    triggers = LocalTriggerStore(self._sessions.workspace)
                    trigger = next((t for t in triggers.list_triggers()
                                    if t.origin_metadata.get(RESPONSIBILITY_TRIGGER_META) == record.id), None)
                    if trigger is None:
                        trigger = triggers.create(
                            name=record.ui_summary or "Responsibility event",
                            session_key=record.session_key or sess.key,
                            channel=record.channel, chat_id=record.chat_id,
                            origin_metadata={RESPONSIBILITY_TRIGGER_META: record.id},
                        )
                    trigger_note = f" Local trigger ID: {trigger.id}. Send matching events through the existing trigger command."
                sess.metadata[GOAL_STATE_KEY] = record.goal_projection()
                self._sessions.save(sess, fsync=True)
                await self._publish_goal_state_changed(sess.metadata)
                return f"Responsibility {record.id}: {record.state}. Progress saved.{trigger_note}"
            # Waiting/paused goals remain explicitly manageable by their stable ID.
            if record.state not in TERMINAL_STATES:
                prior["status"] = "active"
        if not isinstance(prior, dict) or prior.get("status") != "active":
            return "No active goal to update."

        normalized = (action or "").strip().lower()
        if normalized not in _GOAL_ACTIONS:
            return ToolResult.error(
                "Error: action must be one of complete, cancel, block, or replace."
            )

        if normalized == "replace":
            if not self._goal_mutation_allowed():
                return ToolResult.error(_REPLACE_UNAVAILABLE_ERROR)
            objective_text = (objective or "").strip()
            if not objective_text:
                return ToolResult.error(
                    "Error: update_goal action='replace' requires a replacement objective."
                )
            if len(objective_text) > MAX_GOAL_OBJECTIVE_CHARS:
                return ToolResult.error(
                    f"Error: objective must not exceed {MAX_GOAL_OBJECTIVE_CHARS} characters."
                )
            summary = (ui_summary or "").strip()[:120]
            blob = {
                **prior,
                "status": "active",
                "objective": objective_text,
                "ui_summary": summary,
                "started_at": _iso_now(),
                "replaced_at": _iso_now(),
                "previous_objective": str(prior.get("objective") or ""),
                "recap": (recap or "").strip(),
            }
            self._save_goal_state(sess, blob, reset_continuation=True)
            await self._publish_goal_state_changed(sess.metadata)
            extra = f"\nSummary line: {summary}" if summary else ""
            return "Goal replaced. Continue toward the new objective using ordinary tools." + extra

        ended = _iso_now()
        status = {
            "complete": "completed",
            "cancel": "cancelled",
            "block": "blocked",
        }[normalized]
        blob = {
            **prior,
            "status": status,
            "ended_at": ended,
            "recap": (recap or "").strip(),
        }
        if normalized == "complete":
            blob["completed_at"] = ended
        self._save_goal_state(sess, blob)
        revoke_goal_mutation_permission()
        await self._publish_goal_state_changed(sess.metadata)

        tail = (recap or "").strip()
        label = {
            "complete": "complete",
            "cancel": "cancelled",
            "block": "blocked",
        }[normalized]
        if tail:
            return f"Goal marked {label} ({ended}). Recap:\n{tail}"
        return f"Goal marked {label} ({ended})."
