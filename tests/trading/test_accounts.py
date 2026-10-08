import json
from types import SimpleNamespace

import httpx
import pytest

from nanobot.agent.tools.account import AccountTool
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.trade_execute import TradeExecuteTool
from nanobot.agent.tools.trade_prepare import TradePrepareTool
from nanobot.market.models import Connection, Instrument, IntegrationsConfig
from nanobot.security.actions import ActionStore
from nanobot.session.records import RecordStore
from nanobot.trading.accounts import AccountSelection, TradingAccounts
from nanobot.trading.execution import TradeExecutor
from nanobot.trading.instruments import InstrumentMappings, SymbolMapping
from nanobot.trading.metaapi import MetaApiClient
from nanobot.trading.proposals import TradeIntent, TradePreview, TradeProposal, TradeProposals


def test_settings_adds_profile_without_replacing_other_credentials_or_authority(tmp_path, monkeypatch):
    from nanobot.config.schema import Config, _resolve_tool_config_refs
    from nanobot.security.secrets import SecretStore
    from nanobot.trading.mission_models import AccountGuardrails
    from nanobot.webui.integration_settings import ConnectionUpdate, configure_connection

    monkeypatch.setattr("nanobot.security.runtime_storage.get_config_path", lambda: tmp_path / "config.json")
    secrets = SecretStore()
    secrets.put("first", "FIRST_PRIVATE_SENTINEL")
    _resolve_tool_config_refs()
    config = Config.model_validate({"channels": {"websocket": {"enabled": False}},
        "tools": {"integrations": {"metaapi": {"account_id": "first", "secret_ref": "first"}}}})
    settings = SimpleNamespace(update=lambda callback: callback(config), load=lambda: config)
    guards = RecordStore("account_guardrails", AccountGuardrails)
    guard = guards.create(AccountGuardrails(id="first", enabled=True, max_open_risk="100",
        max_account_loss="100", baseline_equity="10000"))
    result = configure_connection(settings, ConnectionUpdate(provider="metaapi", account_id="second",
        token="SECOND_PRIVATE_SENTINEL", name="Second", make_default=False))
    assert config.tools.integrations.metaapi.account_id == "first"
    assert set(config.tools.integrations.broker_accounts()) == {"first", "second"}
    second = config.tools.integrations.metaapi_accounts["second"]
    assert second.secret_ref != "first"
    assert secrets.resolve("first").reveal() == "FIRST_PRIVATE_SENTINEL"
    assert secrets.resolve(second.secret_ref).reveal() == "SECOND_PRIVATE_SENTINEL"
    assert guards.get("first").model_dump() == guard.model_dump()
    assert "PRIVATE_SENTINEL" not in json.dumps(result)


def profiles():
    return IntegrationsConfig(metaapi_accounts={
        "demo": Connection(account_id="demo", secret_ref="first", name="Personal"),
        "second": Connection(account_id="second", secret_ref="second", name="Practice"),
    }, default_metaapi_account="demo")


def test_legacy_connection_migration_is_repeatable():
    original = IntegrationsConfig(metaapi=Connection(account_id="demo", secret_ref="first"))
    restored = IntegrationsConfig.model_validate_json(original.model_dump_json())
    assert restored.model_dump() == original.model_dump()
    assert restored.default_metaapi_account == "demo"
    assert restored.metaapi_accounts["demo"].secret_ref == "first"
    with pytest.raises(ValueError, match="exact MetaApi"):
        IntegrationsConfig(metaapi_accounts={"wrong": Connection(account_id="demo", secret_ref="first")})
    with pytest.raises(ValueError, match="not configured"):
        IntegrationsConfig(default_metaapi_account="missing")


def test_selection_survives_restart_is_private_and_never_changes_default(tmp_path):
    journal = ActionStore(tmp_path / "state.db")
    config = profiles()
    accounts = TradingAccounts(config, journal)
    accounts.select("websocket:first", "second")
    reopened = TradingAccounts(config, ActionStore(tmp_path / "state.db"))
    assert reopened.connection(principal="websocket:first").account_id == "second"
    assert reopened.connection(principal="websocket:other").account_id == "demo"
    assert reopened.connection("demo", principal="websocket:first").account_id == "demo"
    assert config.metaapi.account_id == "demo"
    assert config.default_metaapi_account == "demo"
    records = RecordStore("broker_account_selection", AccountSelection, journal).list()
    assert len(records) == 1 and records[0].principal == "websocket:first"
    assert "secret_ref" not in json.dumps(reopened.public_accounts("websocket:first"))


def test_removed_selected_account_does_not_silently_fall_back(tmp_path):
    config = profiles()
    accounts = TradingAccounts(config, ActionStore(tmp_path / "state.db"))
    accounts.select("websocket:first", "second")
    del config.metaapi_accounts["second"]
    with pytest.raises(ValueError, match="select a connected"):
        accounts.connection(principal="websocket:first")
    accounts.select("websocket:first", "demo")
    assert accounts.connection(principal="websocket:first").account_id == "demo"


async def test_account_tool_switches_without_financial_authorization_or_token_output(client, tmp_path):
    accounts = TradingAccounts(profiles(), ActionStore(tmp_path / "state.db"))
    tool = AccountTool(client, accounts)
    with request_context(RequestContext(channel="websocket", chat_id="main", session_key="websocket:main")):
        result = json.loads(await tool.execute(operation="select_account", account_id="second"))
        assert next(item for item in result if item["selected"])["account_id"] == "second"
        assert "PRIVATE_META_SENTINEL" not in str(result)
    assert accounts.selections.journal.list_effects() == []
    assert accounts.selections.journal.pending_resolutions() == []


async def test_proposal_and_preview_keep_original_account_after_chat_switch(client, tmp_path, monkeypatch):
    journal = ActionStore(tmp_path / "state.db")
    mappings = InstrumentMappings(RecordStore("mappings", SymbolMapping, journal))
    proposals = RecordStore("trade_proposals", TradeProposal, journal)
    previews = RecordStore("trade_previews", TradePreview, journal)
    accounts = TradingAccounts(profiles(), journal)
    def second_provider(request):
        response = client.transport.handler(request)
        if request.url.path.endswith("/accounts/second"):
            return httpx.Response(200, json={**response.json(), "_id": "second"})
        return response

    second = MetaApiClient(client.connection.model_copy(update={"account_id": "second"}),
                           client.secrets, transport=httpx.MockTransport(second_provider))
    instrument = Instrument(id="XAU-USD", display_symbol="XAUUSD", asset_class="metal", base="XAU", quote="USD")
    await mappings.verify_user_mapping(client, instrument, "GOLDm")
    await mappings.verify_user_mapping(second, instrument, "GOLDm")
    chosen = []

    def routed(account_id=None, *, principal=None):
        account_id = accounts.connection(account_id, principal=principal).account_id
        chosen.append(account_id)
        return client if account_id == "demo" else second

    monkeypatch.setattr(accounts, "client", routed)
    service = TradeProposals(client, mappings, proposals, previews)
    tool = TradePrepareTool(service, accounts)
    owner = "websocket:main"
    with request_context(RequestContext(channel="websocket", chat_id="main", session_key=owner)):
        accounts.select(owner, "second")
        created = json.loads(await tool.execute(operation="create", intent=TradeIntent(
            canonical_instrument=instrument.id, side="buy", volume="0.09", stop_loss="2670").model_dump(mode="json")))
        assert created["account_id"] == "second"
        accounts.select(owner, "demo")
        preview = json.loads(await tool.execute(operation="preview", proposal_id=created["id"]))
        assert preview["account_id"] == "second"
        assert chosen[-1] == "second"
        with pytest.raises(PermissionError, match="cannot switch"):
            await tool.execute(operation="preview", proposal_id=created["id"], account_id="demo")
        execute = TradeExecuteTool(TradeExecutor(service, journal), accounts)
        assert execute.executor_for(preview["id"], owner).proposals.client.connection.account_id == "second"
    assert proposals.get(created["id"]).account_id == "second"
    assert journal.list_effects() == []
