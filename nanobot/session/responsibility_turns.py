"""Wake durable goals through the existing automation turn admission path."""

from __future__ import annotations

import asyncio
import json
import time
from collections.abc import Awaitable, Callable

from nanobot.bus.events import InboundMessage, OutboundMessage
from nanobot.cron.session_turns import CRON_DEFER_UNTIL_IDLE_META, CRON_TRIGGER_META
from nanobot.security.workspace_access import WORKSPACE_SCOPE_METADATA_KEY
from nanobot.session.goal_state import GOAL_STATE_KEY, goal_state_raw, parse_goal_state
from nanobot.session.keys import last_channel_from_metadata
from nanobot.session.manager import SessionManager
from nanobot.session.responsibilities import ResponsibilityStore

RESPONSIBILITY_WAKE_META = "_responsibility_wake"
RESPONSIBILITY_TRIGGER_META = "_responsibility_id"
RESPONSIBILITY_CRON_ID = "responsibility_wakes"


def migrate_session_goals(sessions: SessionManager) -> None:
    """Idempotently link legacy goals; do not schedule previously unscheduled work."""
    for row in sessions.list_sessions():
        session = sessions.get_existing(row["key"])
        if session is None or not session.policy.persist:
            continue
        goal = parse_goal_state(goal_state_raw(session.metadata))
        if not goal or goal.get("responsibility_id") or goal.get("status") not in {"active", "blocked"}:
            continue
        objective = str(goal.get("objective") or "").strip()
        if not objective:
            continue
        route = last_channel_from_metadata(session.metadata)
        if route is None:
            channel, _, chat_id = session.key.partition(":")
            route = (channel, chat_id) if channel != "unified" else ("", "")
        record = sessions.responsibilities.create(
            objective=objective, session_key=session.key, channel=route[0], chat_id=route[1],
            ui_summary=str(goal.get("ui_summary") or ""),
            legacy_key=f"nanobot-goal:{session.key}:{goal.get('started_at', '')}:{objective}",
        )
        if goal.get("status") == "blocked" and record.revision == 0:
            record.state = "WAITING_FOR_USER"
            record = sessions.responsibilities.save(record)
        session.metadata[GOAL_STATE_KEY] = {**goal, **record.goal_projection()}
        sessions.save(session, fsync=True)


async def run_responsibility_wakes(
    store: ResponsibilityStore,
    *,
    submit_turn: Callable[[InboundMessage], Awaitable[OutboundMessage | None]],
    is_channel_enabled: Callable[[str], bool],
    now_ms: int | None = None,
) -> None:
    """One cron callback; no background loop, workers or alternate agent runtime.

    An overdue schedule is coalesced into one persisted occurrence. Event
    receipts and schedule receipts use the same durable admission contract.
    """
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    for record in store.list():
        if record.state == "SCHEDULED" and record.next_wake_ms is not None and record.next_wake_ms <= now:
            store.enqueue(record.id, f"schedule:{record.wake_generation}:{record.next_wake_ms}", "Scheduled responsibility wake")
        record = store.get(record.id)
        if not record.channel or not record.chat_id or not is_channel_enabled(record.channel):
            continue
        for wake_id, receipt in record.wakes.items():
            if receipt.state != "QUEUED":
                continue
            claimed = store.claim(record.id, wake_id)
            if claimed is None:
                continue
            session_key = claimed.session_key or f"{claimed.channel}:{claimed.chat_id}"
            content = (
                "Continue this durable responsibility using its saved operational state. "
                "Inspect current state before effects. When no work remains now, use update_goal "
                "to wait, pause, or complete; do not keep inference running while waiting.\n"
                + json.dumps({"id": claimed.id, "objective": claimed.objective,
                              "progress": claimed.progress,
                              "checkpoint": claimed.checkpoint.model_dump(),
                              "wake": receipt.content}, ensure_ascii=False)
            )
            metadata = {
                RESPONSIBILITY_WAKE_META: {"id": claimed.id, "wake_id": wake_id},
                CRON_TRIGGER_META: {
                    "job_id": RESPONSIBILITY_CRON_ID,
                    "job_name": claimed.ui_summary or "Responsibility",
                    "run_id": f"{claimed.id}:{wake_id}",
                    "persist_content": content,
                },
                CRON_DEFER_UNTIL_IDLE_META: True,
            }
            if claimed.workspace_scope:
                metadata[WORKSPACE_SCOPE_METADATA_KEY] = claimed.workspace_scope
            try:
                await submit_turn(InboundMessage(
                    channel=claimed.channel, chat_id=claimed.chat_id, sender_id="cron",
                    content=content, metadata=metadata, session_key_override=session_key,
                ))
            except (Exception, asyncio.CancelledError):
                store.finish(claimed.id, wake_id, uncertain=True)
                raise
            else:
                store.finish(claimed.id, wake_id)
