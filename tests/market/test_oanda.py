from decimal import Decimal

import httpx
import pytest
from legacy_oanda import OandaClient, ProviderUnavailableError

from nanobot.market.models import Connection
from nanobot.security.secrets import SecretStore


@pytest.fixture
def secrets(tmp_path):
    store = SecretStore(tmp_path / "secrets")
    store.put("oanda", "PRIVATE_OANDA_SENTINEL")
    return store


async def test_normalized_quotes_candles_and_metadata(secrets):
    def handler(request):
        assert request.headers["Authorization"] == "Bearer PRIVATE_OANDA_SENTINEL"
        if request.url.path.endswith("pricing"):
            return httpx.Response(200, json={"prices":[{"instrument":"XAU_USD", "time":"2026-10-07T19:00:00Z", "bids":[{"price":"2700.12345"}], "asks":[{"price":"2700.22345"}]}]})
        if request.url.path.endswith("candles"):
            return httpx.Response(200, json={"candles":[{"time":"2026-10-07T18:00:00Z", "complete":True, "volume":17, "mid":{"o":"2699.12","h":"2701.50","l":"2698.00","c":"2700.12"}}]})
        return httpx.Response(200, json={"instruments":[{"name":"XAU_USD","type":"METAL","displayName":"Gold/USD","pipLocation":-2,"displayPrecision":3,"tradeUnitsPrecision":0,"minimumTradeSize":"1"}]})
    client = OandaClient(Connection(secret_ref="oanda", account_id="demo"), secrets, transport=httpx.MockTransport(handler))
    quote = await client.quote("XAU_USD", "gold-usd")
    assert quote.bid == Decimal("2700.12345")
    assert quote.source == "oanda" and quote.time.utcoffset().total_seconds() == 0
    candle, = await client.candles("XAU_USD", "gold-usd", "H1", count=1)
    assert candle.complete and candle.close == Decimal("2700.12") and candle.volume == 17
    assert "PRIVATE_OANDA_SENTINEL" not in quote.model_dump_json() + candle.model_dump_json()
    instrument, = await client.instruments()
    assert instrument.minimum_trade_size == Decimal(1)
    with pytest.raises(ValueError):
        await client.candles("XAU_USD", "gold-usd", "invalid")


async def test_rate_limit_and_error_redaction(secrets):
    calls = 0
    def handler(request):
        nonlocal calls
        calls += 1
        return httpx.Response(429 if calls < 3 else 403, text="PRIVATE_OANDA_SENTINEL")
    client = OandaClient(Connection(secret_ref="oanda", account_id="demo"), secrets, transport=httpx.MockTransport(handler))
    with pytest.raises(ProviderUnavailableError) as exc:
        await client.instruments()
    assert calls == 3
    assert "PRIVATE_OANDA_SENTINEL" not in str(exc.value)


async def test_invalid_response_does_not_leak(secrets):
    client = OandaClient(Connection(secret_ref="oanda", account_id="demo"), secrets,
                         transport=httpx.MockTransport(lambda r: httpx.Response(200,json={"instruments":"PRIVATE_OANDA_SENTINEL"})))
    with pytest.raises(ProviderUnavailableError) as exc:
        await client.instruments()
    assert "PRIVATE_OANDA_SENTINEL" not in str(exc.value)
