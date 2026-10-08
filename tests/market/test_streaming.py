import asyncio
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx
import pytest

from nanobot.market.models import Connection, Quote
from nanobot.market.oanda import OandaClient, ProviderUnavailableError
from nanobot.market.streaming import PriceStream
from nanobot.security.secrets import SecretStore


class Chunks(httpx.AsyncByteStream):
    def __init__(self, chunks):
        self.chunks = chunks

    async def __aiter__(self):
        for chunk in self.chunks:
            yield chunk


def frame(time="2026-10-07T19:00:00Z", symbol="XAU_USD"):
    return {"type": "PRICE", "instrument": symbol, "time": time,
        "bids": [{"price": "2700.12345"}], "asks": [{"price": "2700.22345"}], "tradeable": True}


async def test_stream_small_split_frames_heartbeat_decimal_and_secret_boundary(tmp_path):
    secrets = SecretStore(tmp_path / "secrets")
    secrets.put("test", "PRIVATE_STREAM_SENTINEL")
    raw = (json.dumps({"type": "HEARTBEAT", "time": "2026-10-07T19:00:00Z"}) + "\n" + json.dumps(frame()) + "\n").encode()
    requested = []

    def handle(request):
        requested.append(request)
        assert request.url.host == "stream-fxpractice.oanda.com"
        assert request.url.params["instruments"] == "XAU_USD"
        assert request.headers["Authorization"] == "Bearer PRIVATE_STREAM_SENTINEL"
        return httpx.Response(200, stream=Chunks([raw[:25], raw[25:]]))

    client = OandaClient(Connection(secret_ref="test", account_id="demo"), secrets,
        transport=httpx.MockTransport(handle))
    stream = client.stream_prices({"XAU_USD": "gold"})
    quote = await anext(stream)
    assert quote.bid == Decimal("2700.12345") and quote.canonical_instrument == "gold"
    assert quote.time.tzinfo is not None and quote.source == "oanda"
    assert "PRIVATE_STREAM_SENTINEL" not in quote.model_dump_json()
    with pytest.raises(ProviderUnavailableError, match="ended"):
        await anext(stream)
    assert len(requested) == 1


async def test_price_delivered_before_stream_finishes_or_accumulates_a_full_buffer(tmp_path):
    class OpenStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield (json.dumps(frame()) + "\n").encode()
            await asyncio.Event().wait()

    secrets = SecretStore(tmp_path / "secrets")
    secrets.put("test", "PRIVATE_STREAM_SENTINEL")
    client = OandaClient(Connection(secret_ref="test", account_id="demo"), secrets,
        transport=httpx.MockTransport(lambda request: httpx.Response(200, stream=OpenStream())))
    stream = client.stream_prices({"XAU_USD": "gold"})
    try:
        result = await asyncio.wait_for(anext(stream), 1)
        assert result.bid == Decimal("2700.12345")
    finally:
        await stream.aclose()


@pytest.mark.parametrize("response", [
    httpx.Response(403, text="PRIVATE_STREAM_SENTINEL"),
    httpx.Response(200, stream=Chunks([b"PRIVATE_STREAM_SENTINEL\n"])),
    httpx.Response(200, stream=Chunks([b"x" * 65537])),
    httpx.Response(200, stream=Chunks([(json.dumps({**frame(), "bids": [{"price": "NaN"}]}) + "\n").encode()])),
    httpx.Response(302, headers={"Location": "http://127.0.0.1/secrets"}),
])
async def test_stream_rejects_errors_malformed_unbounded_and_redirects_without_leaks(tmp_path, response):
    secrets = SecretStore(tmp_path / "secrets")
    secrets.put("test", "PRIVATE_STREAM_SENTINEL")
    client = OandaClient(Connection(secret_ref="test", account_id="demo"), secrets,
        transport=httpx.MockTransport(lambda request: response))
    with pytest.raises(ProviderUnavailableError) as exc:
        await anext(client.stream_prices({"XAU_USD": "gold"}))
    assert "PRIVATE_STREAM_SENTINEL" not in str(exc.value)


def quote(offset=0, symbol="XAU_USD"):
    now = datetime(2026, 10, 7, tzinfo=timezone.utc) + timedelta(seconds=offset)
    return Quote(canonical_instrument="gold", provider_instrument=symbol, time=now,
        fetched_at=now, bid="2700", ask="2701", source="oanda")


async def test_one_stream_shared_clients_no_idle_work_coalescing_old_tick_and_cleanup(monkeypatch, tmp_path):
    client = OandaClient(Connection(secret_ref="test", account_id="demo"), SecretStore(tmp_path / "secrets"))
    incoming = asyncio.Queue()
    started = asyncio.Event()
    calls = []

    async def prices(instruments):
        calls.append(instruments)
        started.set()
        while True:
            yield await incoming.get()

    monkeypatch.setattr(client, "stream_prices", prices)
    hub = PriceStream(client)
    received_a, received_b = [], []
    updated = asyncio.Event()

    async def callback_a(value):
        if isinstance(value, Quote):
            received_a.append(value)

    async def callback_b(value):
        if isinstance(value, Quote):
            received_b.append(value)
            updated.set()

    assert calls == []
    await hub.add("a", "XAU_USD", "gold", callback_a)
    await started.wait()
    await hub.add("b", "XAU_USD", "gold-usd", callback_b)
    await incoming.put(quote(2))
    await asyncio.wait_for(updated.wait(), 1)
    assert len(calls) == 1
    assert received_b[0].canonical_instrument == "gold-usd"
    updated.clear()
    await incoming.put(quote(1))
    await incoming.put(quote(2))
    await incoming.put(quote(3))
    await asyncio.wait_for(updated.wait(), 1)
    assert [q.time for q in received_b] == [quote(2).time, quote(3).time]
    await hub.remove("a")
    assert hub._task is not None
    await hub.remove("b")
    assert hub._task is None and not hub._consumers
    await hub.close()


async def test_reconnect_after_provider_failure_and_cancel_backoff(monkeypatch, tmp_path):
    client = OandaClient(Connection(secret_ref="test", account_id="demo"), SecretStore(tmp_path / "secrets"))
    failed = asyncio.Event()

    async def broken(instruments):
        if False:
            yield quote()
        raise ProviderUnavailableError("offline")

    async def consume(value):
        if value == "reconnecting":
            failed.set()

    monkeypatch.setattr(client, "stream_prices", broken)
    hub = PriceStream(client)
    await hub.add("a", "XAU_USD", "gold", consume)
    await asyncio.wait_for(failed.wait(), 1)
    await hub.close()
    assert hub._task is None


async def test_concurrent_clients_cannot_start_parallel_account_streams(monkeypatch, tmp_path):
    client = OandaClient(Connection(secret_ref="test", account_id="demo"), SecretStore(tmp_path / "secrets"))
    started = asyncio.Event()
    current, peak = 0, 0

    async def prices(instruments):
        nonlocal current, peak
        current += 1
        peak = max(current, peak)
        started.set()
        try:
            await asyncio.Event().wait()
            yield quote()
        finally:
            current -= 1

    async def consume(value):
        pass

    monkeypatch.setattr(client, "stream_prices", prices)
    hub = PriceStream(client)
    await hub.add("a", "XAU_USD", "gold", consume)
    await started.wait()
    await asyncio.gather(hub.add("b", "EUR_USD", "eurusd", consume), hub.add("c", "GBP_USD", "gbpusd", consume))
    await asyncio.gather(hub.remove("a"), hub.remove("b"))
    await hub.close()
    assert peak == 1 and current == 0
