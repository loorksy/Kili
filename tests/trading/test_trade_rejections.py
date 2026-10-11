"""Broker rejection regressions: offline SDK IPC, exact approval, no live money."""
import asyncio
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from loguru import logger
from pydantic import ValidationError
from test_execution import approve, setup

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.trading.metaapi import BrokerItem, BrokerPrice, SymbolSpec
from nanobot.trading.preflight import validate_market
from nanobot.trading.proposals import TradeIntent, TradeProposals
from nanobot.trading.retcodes import (
    ProviderDiagnostic,
    provider_diagnostic,
    rejection_reason,
    trade_outcome,
)
from nanobot.trading.sdk_bridge import SDKBridge, SDKFrame, SDKRejectedError
from nanobot.trading.sdk_worker import trade


@pytest.fixture
def operational_logs():
    messages = []
    sink = logger.add(lambda message: messages.append(str(message)))
    try:
        yield messages
    finally:
        logger.remove(sink)


NOW = datetime(2026, 10, 8, 19, 49, tzinfo=timezone.utc)


def terms():
    spec = SymbolSpec.model_validate({"symbol": "XAUUSDm", "digits": 3, "point": "0.001", "tickSize": "0.001",
        "minVolume": "0.01", "maxVolume": "200", "volumeStep": "0.01", "tradeMode": "SYMBOL_TRADE_MODE_FULL",
        "baseCurrency": "XAU", "profitCurrency": "USD", "allowedOrderTypes": ["SYMBOL_ORDER_MARKET", "SYMBOL_ORDER_LIMIT", "SYMBOL_ORDER_STOP", "SYMBOL_ORDER_SL", "SYMBOL_ORDER_TP"],
        "allowedExpirationModes": ["SYMBOL_EXPIRATION_GTC", "SYMBOL_EXPIRATION_SPECIFIED"],
        "fillingModes": ["SYMBOL_FILLING_FOK", "SYMBOL_FILLING_IOC"], "executionMode": "SYMBOL_TRADE_EXECUTION_MARKET",
        "stopsLevel": 0, "freezeLevel": 0,
        "tradeSessions": {"THURSDAY": [{"from": "00:00:00.000", "to": "20:57:59.999"}, {"from": "22:00:00.000", "to": "23:59:59.999"}]}})
    price = BrokerPrice(symbol="XAUUSDm", bid="4129.359", ask="4129.599", time=NOW.isoformat(), brokerTime="2026-10-08 19:49:00.000")
    intent = TradeIntent(canonical_instrument="gold", side="sell", order_type="limit", volume="0.11", price="4134",
                        stop_loss="4138.5", take_profit="4125", expiration_time=(NOW + timedelta(hours=3)).isoformat())
    return intent, spec, price


def test_real_broker_aliases_and_old_persisted_spec():
    _, spec, _ = terms()
    assert spec.currency_base == "XAU" and spec.currency_profit == "USD"
    assert "SYMBOL_ORDER_LIMIT" in spec.order_mode
    assert spec.allowed_expiration_modes and spec.filling_modes
    assert spec.point == Decimal(".001") and spec.stops_level == spec.freeze_level == 0
    assert SymbolSpec.model_validate(spec.model_dump(mode="json")) == spec
    old = spec.model_dump(mode="json")
    old.update(currencyProfit="EUR", currencyBase="XAG", orderMode=["SYMBOL_ORDER_MARKET"])
    del old["currency_profit"], old["currency_base"], old["order_mode"]
    assert SymbolSpec.model_validate(old).currency_profit == "EUR"


@pytest.mark.parametrize("change,match", [
    ({"volume": "0.115"}, "Volume"), ({"volume": "0.001"}, "Volume"),
    ({"price": "4128"}, "Pending price"), ({"stop_loss": "4133"}, "Protection"),
    ({"take_profit": "4135"}, "Protection"),
    ({"expiration_time": (NOW - timedelta(minutes=1)).isoformat()}, "Expiration"),
    ({"expiration_time": (NOW + timedelta(seconds=119)).isoformat()}, "Expiration"),
])
def test_exact_report_request_preflight_and_invalid_terms(change, match):
    intent, spec, price = terms()
    TradeProposals.validate_spec(intent, spec)
    validate_market(intent, spec, price, NOW)
    modified = TradeIntent.model_validate({**intent.model_dump(), **change})
    with pytest.raises(ValueError, match=match):
        TradeProposals.validate_spec(modified, spec)
        validate_market(modified, spec, price, NOW)


@pytest.mark.parametrize("change,match", [
    ({"stops_level": 5000}, "Pending price"),
    ({"allowed_expiration_modes": ["SYMBOL_EXPIRATION_GTC"]}, "specified expiration"),
    ({"order_mode": ["SYMBOL_ORDER_MARKET"]}, "order type"),
])
def test_broker_capability_rejections_are_bilingual(change, match):
    intent, spec, price = terms()
    with pytest.raises(ValueError, match=match) as error:
        validate_market(intent, spec.model_copy(update=change), price, NOW)
    assert re.search(r"[\u0600-\u06ff]", str(error.value))


def test_stop_distance_freeze_and_tick_lattice():
    intent, spec, price = terms()
    with pytest.raises(ValueError, match="Protection"):
        validate_market(intent.model_copy(update={"stop_loss": Decimal("4134.01")}), spec.model_copy(update={"stops_level": 50}), price, NOW)
    with pytest.raises(ValueError, match="freeze"):
        validate_market(intent.model_copy(update={"operation": "cancel_order", "expiration_time": None}),
            spec.model_copy(update={"freeze_level": 50}), price, NOW,
            BrokerItem(id="order", symbol=spec.symbol, type="ORDER_TYPE_SELL_LIMIT", openPrice="4129.36"))
    with pytest.raises(ValueError, match="tick size"):
        TradeProposals.validate_spec(intent.model_copy(update={"price": Decimal("4134.001")}), spec.model_copy(update={"tick_size": Decimal(".01")}))


def test_market_session_uses_broker_clock_and_gtc_is_omitted():
    intent, spec, price = terms()
    with pytest.raises(ValueError, match="Market is closed"):
        validate_market(intent, spec, price, NOW.replace(hour=21, minute=30))
    # A broker clock two hours ahead puts the same UTC request in the closed gap.
    with pytest.raises(ValueError, match="Market is closed"):
        validate_market(intent, spec, price.model_copy(update={"broker_time": "2026-10-08 21:49:00.000"}), NOW)
    validate_market(intent.model_copy(update={"expiration_time": None}), spec, price, NOW)
    payload = TradeProposals.broker_request(intent.model_copy(update={"expiration_time": None}), "XAUUSDm", "effect")
    assert "expiration" not in payload
    assert re.fullmatch(r"[A-Za-z0-9]+_[A-Za-z0-9]+_[A-Za-z0-9]+", payload["clientId"])
    assert len(payload["clientId"]) <= 26
    assert payload == TradeProposals.broker_request(intent.model_copy(update={"expiration_time": None}), "XAUUSDm", "effect")


@pytest.mark.parametrize("code,numeric", [("TRADE_RETCODE_TIMEOUT", 10012), ("TRADE_RETCODE_CONNECTION", 10031),
    ("TRADE_RETCODE_REQUOTE", 10004), ("TRADE_RETCODE_PRICE_OFF", 10021)])
def test_uncertain_codes_are_never_known_failure(code, numeric):
    assert trade_outcome(code, numeric, kind="TradeException") == "UNCERTAIN"


def test_sdk_frame_accepts_diagnostics_but_rejects_unknown_fields():
    frame = SDKFrame.model_validate({"ok": False, "error": "rejected", "provider_error": {"kind": "TradeException", "numeric_code": 10022}})
    assert frame.provider_error.numeric_code == 10022
    with pytest.raises(ValidationError):
        SDKFrame.model_validate({**frame.model_dump(), "raw_request": "forbidden"})


def test_validation_diagnostics_redact_token_jwt_url_and_auth_fields():
    validation_error = type("ValidationException", (Exception,), {
        "details": [{"parameter": "clientId", "message": "Invalid format TOKEN_SENTINEL"}]})
    error = validation_error("TOKEN_SENTINEL eyJabc.eyJdef.signature https://provider.test/path?auth-token=SECRET Authorization: Bearer OTHER_SENTINEL")
    diagnostic = provider_diagnostic(error, "TOKEN_SENTINEL")
    text = diagnostic.model_dump_json()
    assert diagnostic.details[0].parameter == "clientId"
    for secret in ("TOKEN_SENTINEL", "eyJabc", "SECRET", "OTHER_SENTINEL", "https://"):
        assert secret not in text
    assert all(rejection_reason(diagnostic))


@pytest.mark.parametrize("code", ["INVALID_EXPIRATION", "INVALID_FILL", "INVALID_STOPS", "INVALID_PRICE", "INVALID_VOLUME", "MARKET_CLOSED",
    "TRADE_DISABLED", "NO_MONEY", "INVALID_ORDER", "LIMIT_ORDERS", "LIMIT_VOLUME", "REJECT", "SERVER_DISABLES_AT", "CLIENT_DISABLES_AT"])
def test_retcodes_have_bilingual_reasons(code):
    diagnostic = ProviderDiagnostic(kind="TradeException", string_code="TRADE_RETCODE_" + code)
    en, ar = rejection_reason(diagnostic)
    assert en and re.search(r"[\u0600-\u06ff]", ar)
    assert trade_outcome(diagnostic.string_code) == "FAILED"


async def test_pending_sdk_receives_float_numbers_and_timezone_aware_expiry():
    rpc = SimpleNamespace(create_limit_sell_order=AsyncMock(return_value={"stringCode": "TRADE_RETCODE_PLACED"}))
    payload = {"actionType": "ORDER_TYPE_SELL_LIMIT", "symbol": "XAUUSDm", "clientId": "nb_0123456789_abcdefghij", "volume": "0.11",
               "openPrice": "4134", "stopLoss": "4138.5", "takeProfit": "4125", "expiration": {"type": "ORDER_TIME_SPECIFIED", "time": "2026-10-08T23:00:00+00:00"}}
    await trade(rpc, payload)
    args, kwargs = rpc.create_limit_sell_order.call_args
    assert args == ("XAUUSDm", .11, 4134.0)
    assert all(type(value) is float for value in args[1:])
    assert type(kwargs["stop_loss"]) is type(kwargs["take_profit"]) is float
    expiry = kwargs["options"]["expiration"]["time"]
    assert isinstance(expiry, datetime) and expiry.utcoffset() == timedelta(0)
    rpc.create_limit_sell_order.assert_awaited_once()


@pytest.mark.parametrize("kind,code,numeric,state", [("TradeException", "TRADE_RETCODE_INVALID_EXPIRATION", 10022, "FAILED"),
    ("TradeException", "TRADE_RETCODE_TIMEOUT", 10012, "UNCERTAIN"),
    ("ValidationException", None, None, "FAILED"), ("TimeoutException", None, None, "UNCERTAIN")])
async def test_worker_bridge_client_effect_preserve_code_and_never_resend(tmp_path, client, monkeypatch, operational_logs, kind, code, numeric, state):
    preview, executor, registry = await setup(tmp_path, client)
    script = tmp_path / "fake_sdk.py"
    script.write_text(f'''
import sys,types,asyncio
sys.path.insert(0,{str(Path.cwd())!r})
from nanobot.trading import sdk_worker as worker
sys.modules['metaapi_cloud_sdk.logger']=types.SimpleNamespace(LoggerManager=types.SimpleNamespace(use_logging=lambda:None))
worker.install_network_boundary=lambda:None
ProviderError=type({kind!r}, (Exception,), {{
    "stringCode":{code!r}, "numericCode":{numeric!r},
    "details":[{{"parameter":"clientId","message":"Invalid format https://provider.test/?token=PRIVATE"}}]}})
class Environment:
    def __init__(self,bootstrap,emit): self.token=bootstrap['token']
    async def execute(self,operation,parameters):
        if operation=='prepare_trade': return {{'ready':True}}
        raise ProviderError('Broker refusal '+self.token+' https://provider.test?auth-token=PRIVATE')
    async def close(self): pass
worker.AccountEnvironment=Environment
asyncio.run(worker.run())
''')
    bridge = SDKBridge(client.connection, client.secrets)
    original_create = asyncio.create_subprocess_exec
    count = []

    async def create(*args, **kwargs):
        count.append(1)
        return await original_create(sys.executable, "-I", str(script), **kwargs)

    # Exercise the real startup, JSON-lines worker loop and bridge error schema.
    executable = tmp_path / "internal/metaapi-sdk/bin/python"
    executable.parent.mkdir(parents=True)
    executable.touch()
    monkeypatch.setattr("nanobot.trading.sdk_bridge.internal_state_root", lambda: tmp_path / "internal")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create)
    monkeypatch.setattr("nanobot.trading.sdk_bridge.account_bridge", lambda *_: bridge)
    original_read, fixture_transport = client._request, client.transport

    async def read(method, path, **kwargs):
        assert method == "GET"
        client.transport = fixture_transport
        try:
            return await original_read(method, path, **kwargs)
        finally:
            client.transport = None

    monkeypatch.setattr(client, "_request", read)
    client.transport = None
    try:
        with request_context(RequestContext(channel="websocket", chat_id="main", session_key="websocket:main")):
            approve(preview, executor.effects)
            result = json.loads(await registry.execute("trade_execute", {"preview_id": preview.id}))
            assert result["state"] == state
            assert result["result"]["string_code"] == code and result["result"]["numeric_code"] == numeric
            assert result["result"]["reason_en"] and result["result"]["reason_ar"]
            assert result["result"]["details"][0]["parameter"] == "clientId"
            saved = executor.effects.get_effect(result["effect_id"])
            assert saved.result == result["result"]
            assert "PRIVATE_META_SENTINEL" not in json.dumps(result) and "https://" not in json.dumps(result)
            assert json.loads(await registry.execute("trade_execute", {"preview_id": preview.id})) == result
            assert len(count) == 1
            logs = "".join(operational_logs)
            assert "PRIVATE_META_SENTINEL" not in logs and "auth-token" not in logs
            assert "https://provider.test" not in logs
        from nanobot.trading.sdk_bridge import SDKUnavailableError
        with pytest.raises(SDKUnavailableError if kind == "TimeoutException" else SDKRejectedError) as error:
            await bridge.request("account")
        assert error.value.provider_error.string_code == code
    finally:
        await bridge.close()


async def test_invalid_pending_terms_fail_before_preview_or_approval(tmp_path, client, monkeypatch):
    from trade_helpers import service_for
    service = await service_for(tmp_path, client)
    proposal = service.create("websocket:main", TradeIntent(canonical_instrument="XAU-USD", side="sell", order_type="limit", volume=".11", price="2600"))
    with pytest.raises(ValueError, match="Pending price"):
        await service.preview(proposal.id, proposal.principal)
    assert service.proposals.get(proposal.id).preview_id is None
    assert service.previews.list() == []


@pytest.mark.parametrize("code,numeric", [("ERR_TRADE_TIMEOUT", 128), ("ERR_NO_CONNECTION", 6), ("ERR_OFF_QUOTES", 136), ("ERR_REQUOTE", 138)])
def test_mt4_uncertainty_is_not_a_known_rejection(code, numeric):
    assert trade_outcome(code, numeric, kind="TradeException") == "UNCERTAIN"


def test_unknown_broker_code_remains_uncertain_and_visible():
    error = ProviderDiagnostic(kind="TradeException", string_code="FUTURE_PROVIDER_CODE")
    assert trade_outcome(error.string_code, kind=error.kind) == "UNCERTAIN"
    assert "FUTURE_PROVIDER_CODE" in rejection_reason(error)[0]


async def test_real_pinned_sdk_formats_pending_wire_request_offline(tmp_path):
    import os
    executable = os.environ.get("NANOBOT_TEST_METAAPI_SDK_PYTHON")
    if not executable:
        pytest.skip("Set NANOBOT_TEST_METAAPI_SDK_PYTHON to the isolated SDK interpreter for this offline compatibility check")
    script = tmp_path / "sdk_wire.py"
    script.write_text(f'''
import sys,asyncio,json
sys.path.insert(0,{str(Path.cwd())!r})
from types import SimpleNamespace
from nanobot.trading.sdk_worker import trade
from metaapi_cloud_sdk.metaapi.metaapi_connection_instance import MetaApiConnectionInstance
from metaapi_cloud_sdk.clients.metaapi.metaapi_websocket_client import MetaApiWebsocketClient
async def check():
    wire=[]
    formatter=object.__new__(MetaApiWebsocketClient)
    async def send(account,request,application,reliability):
        formatter._format_request(request)
        wire.append(request)
        return {{'stringCode':'TRADE_RETCODE_PLACED'}}
    rpc=MetaApiConnectionInstance(SimpleNamespace(trade=send), SimpleNamespace(application='RPC',account=SimpleNamespace(id='fixture',reliability='regular')))
    rpc._opened=True
    await trade(rpc,{{'actionType':'ORDER_TYPE_SELL_LIMIT','symbol':'XAUUSDm','volume':'0.11','openPrice':'4134','stopLoss':'4138.5','takeProfit':'4125',
        'clientId':'nb_0123456789_abcdefghij','expiration':{{'type':'ORDER_TIME_SPECIFIED','time':'2026-10-08T23:00:00+00:00'}}}})
    assert len(wire)==1
    assert wire[0]['volume']==0.11 and wire[0]['openPrice']==4134.0
    assert wire[0]['expiration']['time']=='2026-10-08T23:00:00.000Z'
    print(json.dumps({{'checked':True}}))
asyncio.run(check())
''')
    process = await asyncio.create_subprocess_exec(executable, "-I", str(script),
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=20)
    assert process.returncode == 0, stderr.decode()
    assert json.loads(stdout) == {"checked": True}


def test_advertised_market_filling_and_missing_broker_clock_are_checked():
    intent, spec, price = terms()
    market = intent.model_copy(update={"order_type": "market", "price": None, "expiration_time": None,
                                      "stop_loss": Decimal("4138.5"), "take_profit": Decimal("4125")})
    with pytest.raises(ValueError, match="filling mode"):
        validate_market(market, spec.model_copy(update={"filling_modes": ["SYMBOL_FILLING_BOC"]}), price, NOW)
    with pytest.raises(ValueError, match="session timezone"):
        validate_market(intent, spec, price.model_copy(update={"broker_time": None}), NOW)


def test_overnight_session_uses_previous_broker_day():
    from nanobot.trading.metaapi import TradeSession
    intent, spec, price = terms()
    spec = spec.model_copy(update={"trade_sessions": {"WEDNESDAY": [TradeSession.model_validate({"from": "22.00.00.000", "to": "02.00.00.000"})]}})
    gtc = intent.model_copy(update={"expiration_time": None})
    validate_market(gtc, spec, price, NOW.replace(hour=1))
    with pytest.raises(ValueError, match="Market is closed"):
        validate_market(gtc, spec, price, NOW.replace(hour=3))
