import json
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from nanobot.agent.tools.market import MarketRecommendation, MarketTool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.market.models import Connection, Quote
from nanobot.market.oanda import OandaClient, OandaInstrument


@pytest.fixture
def market():
    client = OandaClient(Connection(secret_ref="test", account_id="test"))
    instrument = OandaInstrument(name="XAU_USD", type="METAL", displayName="XAU/USD", pipLocation=-2,
        displayPrecision=3, tradeUnitsPrecision=0, minimumTradeSize="1")
    client.instruments = AsyncMock(return_value=[instrument])
    client.quote = AsyncMock(return_value=Quote(canonical_instrument="XAU_USD", provider_instrument="XAU_USD",
        time="2026-10-08T12:00:00Z", fetched_at="2026-10-08T12:00:01Z", bid="2700.10", ask="2700.20", source="oanda"))
    client.candles = AsyncMock(return_value=[])
    return MarketTool(client)


async def test_discovery_and_one_symbol_quote_use_registry(market):
    registry = ToolRegistry()
    registry.register(market)
    capabilities = await registry.execute("market", {"operation": "capabilities"})
    assert not getattr(capabilities, "is_error", False)
    assert "quote" in json.loads(str(capabilities))["operations"]
    for symbol in ("XAUUSD", "XAU_USD", "XAU/USD"):
        result = await registry.execute("market", {"operation": "quote", "instrument": symbol})
        assert not getattr(result, "is_error", False), result
        assert json.loads(str(result))["bid"] == "2700.10"
    market.client.quote.assert_awaited_with("XAU_USD", "XAU_USD")


async def test_daily_alias_and_exact_pair_remain_supported(market):
    await market.execute(operation="candles", instrument="XAUUSD", timeframe="D1", count=20)
    market.client.candles.assert_awaited_with("XAU_USD", "XAU_USD", "D", count=20, before=None)
    await market.execute(operation="quote", provider_instrument="XAU_USD", canonical_instrument="gold")
    market.client.quote.assert_awaited_with("XAU_USD", "gold")


async def test_unknown_instrument_never_becomes_broker_mapping(market):
    with pytest.raises(ValueError, match="unavailable or ambiguous"):
        await market.execute(operation="quote", instrument="XAUUSDm")
    market.client.quote.assert_not_awaited()
    with pytest.raises(ValueError, match="Unsupported timeframe"):
        await market.execute(operation="candles", instrument="XAUUSD", timeframe="made_up")
    market.client.candles.assert_not_awaited()


async def test_recommendation_is_display_only_and_needs_no_account(market):
    result = await market.execute(operation="recommendation", recommendation={"instrument": "XAU_USD",
        "intent": "BUY", "summary": "Fixture analysis, not an execution", "entry": ["2700.1", "2701"], "stop_loss": "2695", "targets": ["2710"]})
    assert result.startswith("```market_recommendation\n")
    payload = json.loads(result.removeprefix("```market_recommendation\n").removesuffix("\n```"))
    assert payload["intent"] == "BUY" and payload["stop_loss"] == "2695"
    assert "approved" not in payload
    market.client.quote.assert_not_awaited()
    with pytest.raises(ValidationError):
        MarketRecommendation(instrument="gold", intent="BUY", summary="bad price", stop_loss="NaN")


@pytest.mark.parametrize("price", ["NaN", "Infinity", "-1", "0", "1e-1000000", "1e1000000", "1." + "0" * 1000])
def test_recommendation_rejects_unbounded_decimal_serialization(price):
    with pytest.raises(ValidationError):
        MarketRecommendation(instrument="gold", intent="BUY", summary="Fixture", stop_loss=price)
