"""Persist resolved user actions as wakes in the existing responsibility runtime."""
from __future__ import annotations

import json

from nanobot.security.actions import ActionStore
from nanobot.session.responsibilities import ResponsibilityStore


def queue_approval_resolutions(store: ResponsibilityStore, journal: ActionStore | None = None) -> None:
    journal = journal or ActionStore()
    for approval in journal.pending_resolutions():
        action = approval.action
        if action.responsibility_id:
            record = store.get(action.responsibility_id)
        else:
            channel, _, chat_id = action.principal.partition(":")
            if channel == "unified":
                channel, chat_id = "", ""
            record = store.create(objective="Continue the exact user-resolved action; inspect its saved preview and effect before execution.",
                                  session_key=action.principal,channel=channel,chat_id=chat_id,
                                  ui_summary="Action approval",legacy_key=f"approval:{approval.id}")
        store.enqueue_user_resolution(record.id,f"approval:{approval.id}",
                                      f"User {approval.status.lower()} the exact action {approval.id}. " + json.dumps(action.parameters))
        # Ack only after the durable receipt exists; a crash reuses the same IDs.
        journal.mark_resolution_queued(approval.id)
