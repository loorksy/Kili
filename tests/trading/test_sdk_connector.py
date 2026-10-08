"""Provider connector contracts; no network access or real financial mutations."""
import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.market.models import Connection
from nanobot.market.oanda import ProviderUnavailableError
from nanobot.security.secrets import SecretStore
from nanobot.trading.metaapi import MetaApiClient, ProviderRejectedError
from nanobot.trading.sdk_bridge import (
    SDKBridge,
    SDKRejectedError,
    account_bridge,
    close_sdk_connections,
)
from nanobot.trading.sdk_worker import AccountEnvironment, number, provider_url, trade


@pytest.mark.parametrize("url", ["http://mt-client-api-v1.london.agiliumtrade.ai", "https://127.0.0.1",
                                 "https://agiliumtrade.ai.attacker.test", "https://x.agiliumtrade.ai:444",
                                 "https://token@x.agiliumtrade.ai", "file:///etc/passwd"])
def test_provider_endpoint_allowlist(url):
    with pytest.raises(ValueError, match="endpoint"):
        provider_url(url)


def test_financial_numbers_reject_precision_loss():
    assert number("0.09") == 0.09
    assert number(None) is None
    for value in ("NaN", "Infinity", "0.1234567890123456789"):
        with pytest.raises(ValueError):
            number(value)


async def test_sdk_environment_shares_synchronized_rpc_and_never_broadcasts(monkeypatch):
    rpc = SimpleNamespace(connect=AsyncMock(), wait_synchronized=AsyncMock(), get_symbols=AsyncMock(return_value=["GOLDm"]),
                          get_account_information=AsyncMock(return_value={"balance": 100}), close=AsyncMock())
    account = SimpleNamespace(get_rpc_connection=lambda: rpc)
    api = SimpleNamespace(metatrader_account_api=SimpleNamespace(get_account=AsyncMock(return_value=account)))
    calls = []

    def make_api(token, options):
        calls.append((token, options))
        return api

    monkeypatch.setitem(sys.modules, "metaapi_cloud_sdk", SimpleNamespace(MetaApi=make_api))
    environment = AccountEnvironment({"token": "SENTINEL", "account_id": "demo", "region": "london"})
    assert await environment.execute("symbols", {}) == ["GOLDm"]
    assert await environment.execute("account", {}) == {"balance": 100}
    rpc.connect.assert_awaited_once()
    api.metatrader_account_api.get_account.assert_awaited_once_with("demo")
    assert rpc.wait_synchronized.await_count == 2
    assert calls[0][1]["retryOpts"] == {"retries": 0}
    with pytest.raises(ValueError, match="Unsupported"):
        await environment.execute("eval", {"code": "print(1)"})


@pytest.mark.parametrize("kind,method,extra", [
    ("ORDER_TYPE_BUY", "create_market_buy_order", {}),
    ("ORDER_TYPE_SELL", "create_market_sell_order", {}),
    ("ORDER_TYPE_BUY_LIMIT", "create_limit_buy_order", {"openPrice": "2700"}),
    ("ORDER_TYPE_SELL_LIMIT", "create_limit_sell_order", {"openPrice": "2700"}),
    ("ORDER_TYPE_BUY_STOP", "create_stop_buy_order", {"openPrice": "2700"}),
    ("ORDER_TYPE_SELL_STOP", "create_stop_sell_order", {"openPrice": "2700"}),
    ("POSITION_MODIFY", "modify_position", {"positionId": "7"}),
    ("POSITION_PARTIAL", "close_position_partially", {"positionId": "7"}),
    ("POSITION_CLOSE_ID", "close_position", {"positionId": "7"}),
    ("ORDER_MODIFY", "modify_order", {"orderId": "8", "openPrice": "2700"}),
    ("ORDER_CANCEL", "cancel_order", {"orderId": "8"}),
])
async def test_only_supported_sdk_trade_methods_used_once(kind, method, extra):
    call = AsyncMock(return_value={"stringCode": "TRADE_RETCODE_DONE"})
    rpc = SimpleNamespace(**{method: call})
    payload = {"actionType": kind, "symbol": "GOLDm", "volume": "0.09", "stopLoss": "2670",
               "takeProfit": "2740", "clientId": "nbfixture", **extra}
    assert (await trade(rpc, payload))["stringCode"] == "TRADE_RETCODE_DONE"
    assert call.await_count == 1
    with pytest.raises(ValueError, match="parameter"):
        await trade(rpc, {**payload, "url": "http://localhost"})
    assert call.await_count == 1


async def test_sdk_timeout_is_not_retried():
    rpc = SimpleNamespace(create_market_buy_order=AsyncMock(side_effect=TimeoutError("private provider text")))
    with pytest.raises(TimeoutError):
        await trade(rpc, {"actionType": "ORDER_TYPE_BUY", "symbol": "GOLDm", "volume": "0.09"})
    rpc.create_market_buy_order.assert_awaited_once()


async def test_default_client_uses_sdk_and_sanitizes_rejections(monkeypatch, tmp_path):
    secret_store = SecretStore(tmp_path / "secrets")
    secret_store.put("meta", "TOKEN_SENTINEL")
    connection = Connection(secret_ref="meta", account_id="demo")
    request = AsyncMock(return_value=["GOLDm"])
    monkeypatch.setattr("nanobot.trading.sdk_bridge.account_bridge", lambda *_: SimpleNamespace(request=request))
    client = MetaApiClient(connection, secret_store)
    assert await client.symbols() == ["GOLDm"]
    request.assert_awaited_once_with("symbols", {})
    request.side_effect = SDKRejectedError("TOKEN_SENTINEL")
    with pytest.raises(ProviderRejectedError) as error:
        await client.account()
    assert "TOKEN_SENTINEL" not in str(error.value)


async def test_bridge_pool_is_account_scoped_and_closed(tmp_path):
    secrets = SecretStore(tmp_path / "secrets")
    first = Connection(secret_ref="meta", account_id="first")
    second = Connection(secret_ref="meta", account_id="second")
    assert account_bridge(first, secrets) is account_bridge(first, secrets)
    assert account_bridge(first, secrets) is not account_bridge(second, secrets)
    previous = account_bridge(first, secrets)
    await close_sdk_connections()
    assert account_bridge(first, secrets) is not previous
    await close_sdk_connections()


async def test_connector_ipc_redacts_reflected_secrets_and_filters_environment(monkeypatch, tmp_path):
    secrets = SecretStore(tmp_path / "secrets")
    secrets.put("meta", "TOKEN_SENTINEL")
    bridge = SDKBridge(Connection(secret_ref="meta", account_id="demo"), secrets)
    executable = tmp_path / "internal/metaapi-sdk/bin/python"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setattr("nanobot.trading.sdk_bridge.internal_state_root", lambda: tmp_path / "internal")
    monkeypatch.setenv("UNRELATED_PRIVATE_KEY", "PRIVATE_ENV_SENTINEL")
    original_create = asyncio.create_subprocess_exec
    arguments = []

    async def create(*args, **kwargs):
        arguments.append((args, kwargs))
        script = 'import sys,json; b=json.loads(sys.stdin.readline());\nfor line in sys.stdin: print(json.dumps({"ok":True,"data":{"reflected":b["token"]}}),flush=True)'
        return await original_create(sys.executable, "-I", "-c", script, **kwargs)

    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    try:
        assert await bridge.request("symbols") == {"reflected": "[redacted]"}
        assert "PRIVATE_ENV_SENTINEL" not in json.dumps(arguments)
        assert "TOKEN_SENTINEL" not in str(arguments)
        assert "UNRELATED_PRIVATE_KEY" not in arguments[0][1]["env"]
        assert len(arguments) == 1
        await bridge.request("account")
        assert len(arguments) == 1
    finally:
        await bridge.close()


async def test_connector_process_death_does_not_replay_request(monkeypatch, tmp_path):
    secrets = SecretStore(tmp_path / "secrets")
    secrets.put("meta", "TOKEN_SENTINEL")
    bridge = SDKBridge(Connection(secret_ref="meta", account_id="demo"), secrets)
    process = await asyncio.create_subprocess_exec(sys.executable, "-I", "-c",
        'import sys,os;sys.stdin.readline();os._exit(1)',
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE)
    start = AsyncMock(return_value=process)
    monkeypatch.setattr(bridge, "_start", start)
    bridge._process = process
    with pytest.raises(ProviderUnavailableError):
        await bridge.request("account")
    start.assert_awaited_once()
    assert process.returncode is not None


async def test_connector_rejects_trade_without_gateway_authority(tmp_path):
    bridge = SDKBridge(Connection(secret_ref="meta", account_id="demo"), SecretStore(tmp_path / "secrets"))
    with pytest.raises(PermissionError, match="exact gateway"):
        await bridge.request("trade", {"actionType": "ORDER_TYPE_BUY"})
    assert bridge._process is None


async def test_sdk_mutation_refences_after_account_synchronization(client, tmp_path, monkeypatch):
    from test_execution import approve, setup

    from nanobot.agent.tools.context import RequestContext, request_context

    preview, executor, registry = await setup(tmp_path, client)
    original_request = client._request
    calls = []

    async def reads(method, path, **kwargs):
        if method == "GET":
            # Keep read-only fixture data while exercising the production SDK
            # mutation branch (no injected transport and no live connection).
            client.transport = legacy_transport
            try:
                return await original_request(method, path, **kwargs)
            finally:
                client.transport = None
        raise AssertionError("No HTTP financial mutation allowed")

    async def sdk_request(operation, parameters=None):
        calls.append(operation)
        if operation == "prepare_trade":
            effect = executor.effects.find_effect(preview.effect_key)
            executor.effects.recover()
            assert executor.effects.get_effect(effect.id).state == "UNCERTAIN"
            return {"ready": True}
        raise AssertionError("A superseded effect must not reach SDK trade")

    legacy_transport = client.transport
    monkeypatch.setattr(client, "_request", reads)
    monkeypatch.setattr("nanobot.trading.sdk_bridge.account_bridge", lambda *_: SimpleNamespace(request=sdk_request))
    client.transport = None
    with request_context(RequestContext(channel="websocket", chat_id="main", session_key="websocket:main")):
        approve(preview, executor.effects)
        result = await registry.execute("trade_execute", {"preview_id": preview.id})
        assert result.is_error
    assert calls == ["prepare_trade"]
    assert executor.effects.find_effect(preview.effect_key).state == "UNCERTAIN"


def test_missing_mapping_error_is_actionable(client, tmp_path):
    from nanobot.security.actions import ActionStore
    from nanobot.session.records import RecordStore
    from nanobot.trading.instruments import InstrumentMappings, SymbolMapping
    mappings = InstrumentMappings(RecordStore("mappings", SymbolMapping, ActionStore(tmp_path / "state.db")))
    with pytest.raises(ValueError, match="verify the exact broker symbol"):
        mappings.require(client.connection.account_id, "XAU-USD")
