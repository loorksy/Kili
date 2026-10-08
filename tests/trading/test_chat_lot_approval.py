"""Editing lots never executes and cannot reuse older user authority."""
from decimal import Decimal

import pytest

from nanobot.config.schema import Config
from nanobot.market.models import Instrument
from nanobot.security.actions import Action, ActionStore
from nanobot.trading.instruments import InstrumentMappings
from nanobot.trading.proposals import TradeIntent, TradeProposals
from nanobot.webui.trade_approval import edit_approval


async def pending(client, tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.security.runtime_storage.get_config_path", lambda: tmp_path / "config.json")
    monkeypatch.setattr("nanobot.trading.accounts.TradingAccounts.client", lambda *_args, **_kwargs: client)
    config = Config()
    config.tools.integrations.metaapi = client.connection
    journal = ActionStore()
    await InstrumentMappings().verify_user_mapping(client, Instrument(id="gold", display_symbol="gold", asset_class="metal"), "GOLDm")
    service = TradeProposals(client)
    proposal = service.create("websocket:main", TradeIntent(canonical_instrument="gold", volume="0.10"))
    preview = await service.preview(proposal.id, proposal.principal)
    action = Action(tool="trade_execute", action_class="consequential", principal=proposal.principal, parameters=preview.material_action())
    return config, journal, journal.request(action)


async def test_chat_edit_revokes_old_terms_and_reopens_new_pending_terms(client, tmp_path, monkeypatch):
    config, journal, old = await pending(client, tmp_path, monkeypatch)
    result = await edit_approval(config, "websocket:main", old.id, Decimal("0.09"))
    assert result["status"] == "PENDING" and result["id"] != old.id
    assert result["action"]["intent"]["volume"] == "0.09"
    assert result["action"]["account_id"] == client.connection.account_id
    assert journal.consume_approval(old.action) is None
    with pytest.raises(ValueError, match="pending"):
        journal.resolve(old.id, principal="websocket:main", approve=True)
    # Reloading the original chat card restores the new exact preview.
    assert ActionStore().read_approval(old.id, "websocket:main") == result
    assert journal.list_effects() == []


async def test_wrong_principal_invalid_lot_and_concurrent_approval_cannot_edit(client, tmp_path, monkeypatch):
    config, journal, old = await pending(client, tmp_path, monkeypatch)
    with pytest.raises(PermissionError):
        await edit_approval(config, "websocket:other", old.id, Decimal("0.09"))
    with pytest.raises(ValueError, match="Volume"):
        await edit_approval(config, "websocket:main", old.id, Decimal("0.015"))
    assert journal.read_approval(old.id, "websocket:main")["status"] == "PENDING"
    journal.resolve(old.id, principal="websocket:main", approve=True)
    with pytest.raises(ValueError, match="pending"):
        await edit_approval(config, "websocket:main", old.id, Decimal("0.09"))
    assert journal.list_effects() == []
