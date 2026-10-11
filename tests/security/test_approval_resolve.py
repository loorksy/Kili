"""Approve and reject share one store path and do not place an order."""

from datetime import datetime

import pytest

from nanobot.bus.events import InboundMessage
from nanobot.command.builtin import cmd_action_approval
from nanobot.command.router import CommandContext
from nanobot.security.actions import Action, ActionStore
from nanobot.session.responsibilities import ResponsibilityStore
from nanobot.webui.cloud_resources import resolve_approval


def _action(volume: str) -> Action:
    return Action(
        tool="trade_execute",
        action_class="consequential",
        principal="websocket:main",
        parameters={"symbol": "GOLDm", "volume": volume, "side": "buy"},
    )


def _store(tmp_path, monkeypatch) -> ActionStore:
    monkeypatch.setattr(
        "nanobot.security.runtime_storage.get_config_path",
        lambda: tmp_path / "config.json",
    )
    return ActionStore()


def test_http_resolve_approves_and_rejects_without_trading(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    approved = store.request(_action("0.10"))
    assert resolve_approval("websocket:main", approved.id, True) == {
        "id": approved.id,
        "status": "APPROVED",
    }
    with pytest.raises(ValueError, match="no longer pending"):
        resolve_approval("websocket:main", approved.id, False)

    rejected = store.request(_action("0.20"))
    assert resolve_approval("websocket:main", rejected.id, False)["status"] == "DENIED"
    pending = store.request(_action("0.30"))
    with pytest.raises(PermissionError):
        resolve_approval("websocket:other", pending.id, True)
    assert store.read_approval(pending.id, "websocket:main")["status"] == "PENDING"


def test_expired_approval_cannot_be_resolved(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    pending = store.request(_action("0.10"))
    monkeypatch.setattr("nanobot.security.actions.now_ms", lambda: pending.expires_at + 1)
    with pytest.raises(ValueError, match="no longer pending"):
        resolve_approval("websocket:main", pending.id, True)
    assert store.read_approval(pending.id, "websocket:main")["status"] == "EXPIRED"


async def test_slash_approve_and_reject_use_the_same_store(tmp_path, monkeypatch):
    store = _store(tmp_path, monkeypatch)
    responsibilities = ResponsibilityStore(tmp_path / "workspace")

    class _Sessions:
        def __init__(self) -> None:
            self.responsibilities = responsibilities

    class _Loop:
        def __init__(self) -> None:
            self.sessions = _Sessions()

    async def decide(raw: str, approval_id: str) -> str:
        message = InboundMessage(
            channel="websocket",
            sender_id="owner",
            chat_id="main",
            content=raw,
            timestamp=datetime.now(),
        )
        reply = await cmd_action_approval(CommandContext(
            msg=message,
            session=None,
            key="websocket:main",
            raw=raw,
            args=approval_id,
            loop=_Loop(),  # type: ignore[arg-type]
            is_user_turn=True,
        ))
        return str(reply.content)

    approved = store.request(_action("0.11"))
    assert f"approved: {approved.id}" in (await decide(f"/approve {approved.id}", approved.id)).lower()
    assert store.read_approval(approved.id, "websocket:main")["status"] == "APPROVED"

    rejected = store.request(_action("0.12"))
    assert f"denied: {rejected.id}" in (await decide(f"/reject {rejected.id}", rejected.id)).lower()
    assert store.read_approval(rejected.id, "websocket:main")["status"] == "DENIED"
