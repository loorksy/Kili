"""Authenticated owner control for market watchers.

The model tool remains fenced to a live responsibility claim. This path is only
for a trusted gateway mutation after the session owner has been authenticated.
"""
from __future__ import annotations

from pathlib import Path

from loguru import logger

from nanobot.market.watchers import (
    MarketWatcher,
    open_watcher_records,
    watcher_public,
)
from nanobot.session.records import RecordStore
from nanobot.session.responsibilities import ResponsibilityStore


def cancel_owned_watcher(
    workspace: Path,
    session_key: str,
    watcher_id: str,
    *,
    records: RecordStore[MarketWatcher] | None = None,
    responsibilities: ResponsibilityStore | None = None,
) -> dict[str, object]:
    """Cancel one watcher owned by this conversation, without an execution claim.

    Idempotent for watchers that already fired or were cancelled. A revision
    conflict reloads once; a second conflict is reported instead of looping.
    """
    if not watcher_id.startswith("watch_"):
        raise ValueError("Unknown market watcher")
    records = records or open_watcher_records(workspace)
    responsibilities = responsibilities or ResponsibilityStore(workspace)
    for _attempt in range(2):
        watcher = records.get(watcher_id)
        _assert_owner(responsibilities, watcher, session_key)
        if watcher.lifecycle in {"CANCELLED", "FIRED"}:
            return watcher_public(watcher)
        watcher.lifecycle = "CANCELLED"
        watcher.active = False
        watcher.fired = False
        watcher.stop_reason = "owner_cancel"
        try:
            saved = records.save_trusted(watcher)
        except ValueError:
            continue
        logger.info(
            "Owner cancelled market watcher {} for responsibility {}",
            saved.id, saved.responsibility_id,
        )
        return watcher_public(saved)
    raise ValueError("Market watcher changed; reload before cancelling")


def _assert_owner(responsibilities: ResponsibilityStore, watcher: MarketWatcher, session_key: str) -> None:
    parent = responsibilities.get(watcher.responsibility_id)
    if not parent.session_key or parent.session_key != session_key:
        raise PermissionError("Market watcher belongs to another conversation")
