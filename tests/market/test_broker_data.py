from datetime import datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from nanobot.market.broker import MT4_TIMEFRAMES, TIMEFRAMES, BrokerMarket
from nanobot.market.models import Connection
from nanobot.market.provider import ProviderUnavailableError
from nanobot.trading.metaapi import AccountConnection, BrokerPrice, MetaApiClient


@pytest.fixture(autouse=True)
def protected_test_storage(tmp_path, monkeypatch):
    monkeypatch.setattr("nanobot.security.runtime_storage.get_config_path", lambda: tmp_path / "config.json")


def broker(account_id="first", version=5):
    return SimpleNamespace(connection=Connection(account_id=account_id, secret_ref="credential"),
        secrets=object(), validate_symbol=MetaApiClient.validate_symbol,
        symbols=AsyncMock(return_value=["EURUSD.a", "US500+", "GOLDm", "BTC/USD"]),
        connection_state=AsyncMock(return_value=AccountConnection(
            _id=account_id, state="DEPLOYED", connectionStatus="CONNECTED", region="london", platformVersion=version)),
        price=AsyncMock(return_value=BrokerPrice(symbol="US500+", bid="5000.01", ask="5000.03",
                                                time="2026-10-08T10:00:00+00:00")))


def bar(time, symbol="US500+"):
    return {"symbol": symbol, "time": time.isoformat(), "open": "5000.01", "high": "5010.03",
            "low": "4990.01", "close": "5005.02", "tickVolume": 50}


async def test_all_broker_symbols_and_account_native_identity():
    first, second = BrokerMarket(broker()), BrokerMarket(broker("second"))
    catalog = await first.instruments()
    assert {item.name for item in catalog} == {"EURUSD.a", "US500+", "GOLDm", "BTC/USD"}
    assert first.canonical("GOLDm") != second.canonical("GOLDm")
    assert first.canonical("GOLDm") != first.canonical("GOLD")
    from nanobot.trading.instruments import InstrumentMappings
    mapping = InstrumentMappings().require("first", first.canonical("GOLDm"))
    assert mapping.provider_symbol == "GOLDm" and mapping.verification_source == "provider_metadata"
    with pytest.raises(ValueError):
        InstrumentMappings().require("second", first.canonical("GOLDm"))
    quote = await first.quote("US500+", first.canonical("US500+"))
    assert quote.bid == Decimal("5000.01")
    assert quote.source == "metaapi" and quote.account_id == "first"
    with pytest.raises(ValueError, match="not available"):
        await first.quote("XAUUSD", first.canonical("XAUUSD"))


async def test_actual_platform_timeframes_are_discovered():
    assert await BrokerMarket(broker(version=4)).timeframes() == MT4_TIMEFRAMES
    assert set(await BrokerMarket(broker(version=5)).timeframes()) == set(TIMEFRAMES)
    market = BrokerMarket(broker(version=4))
    with pytest.raises(ValueError, match="Unsupported"):
        await market.candles("GOLDm", market.canonical("GOLDm"), "M2")


async def test_normalized_history_is_sorted_scoped_and_preserves_completeness(monkeypatch):
    market = BrokerMarket(broker())
    start = datetime(2026, 10, 8, 10, tzinfo=timezone.utc)
    request = AsyncMock(return_value=[bar(start + timedelta(minutes=2)), bar(start), bar(start + timedelta(minutes=1))])
    monkeypatch.setattr("nanobot.market.broker.account_bridge", lambda *_: SimpleNamespace(request=request))
    candles = await market.candles("US500+", market.canonical("US500+"), "M1", count=3)
    assert [c.time for c in candles] == [start + timedelta(minutes=i) for i in range(3)]
    assert [c.complete for c in candles] == [True, True, False]
    assert all(c.source == "metaapi" and c.account_id == "first" for c in candles)
    assert candles[0].open == Decimal("5000.01") and candles[0].volume == 50
    assert request.await_args.args[1]["timeframe"] == "1m"


async def test_history_pagination_is_bounded_and_uses_provider_start_time(monkeypatch):
    market = BrokerMarket(broker())
    start = datetime(2026, 10, 8, 10, tzinfo=timezone.utc)
    fixture = [bar(start + timedelta(minutes=i)) for i in range(1200)]

    async def provider(_operation, params):
        boundary = datetime.fromisoformat(params["start"]) if params["start"] else None
        eligible = [item for item in fixture if boundary is None or datetime.fromisoformat(item["time"]) <= boundary]
        assert params["limit"] <= 1000
        return eligible[-params["limit"]:]

    request = AsyncMock(side_effect=provider)
    monkeypatch.setattr("nanobot.market.broker.account_bridge", lambda *_: SimpleNamespace(request=request))
    candles = await market.candles("US500+", market.canonical("US500+"), "M1", count=1200)
    assert len(candles) == 1200
    assert request.await_count == 2
    assert candles[0].time == start


@pytest.mark.parametrize("bad", [{"symbol": "wrong"}, {"high": "4990"}, {"close": "NaN"}, {"time": "2026-10-08T10:00:00"}])
async def test_malformed_provider_evidence_is_rejected(monkeypatch, bad):
    market = BrokerMarket(broker())
    request = AsyncMock(return_value=[{**bar(datetime(2026, 10, 8, 10, tzinfo=timezone.utc)), **bad}])
    monkeypatch.setattr("nanobot.market.broker.account_bridge", lambda *_: SimpleNamespace(request=request))
    with pytest.raises(ProviderUnavailableError):
        await market.candles("US500+", market.canonical("US500+"), "H1", count=1)
