"""Controlled OANDA reads. Credentials exist only in the trusted HTTP request."""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from nanobot.market.models import Candle, Connection, Quote
from nanobot.market.provider import ProviderUnavailableError, parse_provider
from nanobot.security.network import PinnedDNSAsyncTransport, httpx_env_proxy_mounts
from nanobot.security.secrets import SecretStore

GRANULARITIES = ("S5", "S10", "S15", "S30", "M1", "M2", "M4", "M5", "M10", "M15", "M30", "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D", "W", "M")


class OandaInstrument(BaseModel):
    model_config = ConfigDict(extra="ignore")
    name: str
    type: str
    display_name: str = Field(alias="displayName")
    pip_location: int = Field(alias="pipLocation")
    display_precision: int = Field(alias="displayPrecision")
    trade_units_precision: int = Field(alias="tradeUnitsPrecision")
    minimum_trade_size: Decimal = Field(alias="minimumTradeSize")


class _Instruments(BaseModel):
    instruments: list[OandaInstrument]


class _OHLC(BaseModel):
    o: Decimal
    h: Decimal
    low: Decimal = Field(alias="l")
    c: Decimal


class _Candle(BaseModel):
    time: datetime
    complete: bool
    volume: int
    mid: _OHLC


class _Candles(BaseModel):
    candles: list[_Candle]


class _PriceLevel(BaseModel):
    price: Decimal


class _Price(BaseModel):
    instrument: str
    time: datetime
    bids: list[_PriceLevel] = Field(min_length=1)
    asks: list[_PriceLevel] = Field(min_length=1)
    tradeable: bool = True
    status: Literal["tradeable", "non-tradeable", "invalid"] | None = None

    @property
    def is_tradeable(self) -> bool:
        return self.status == "tradeable" if self.status is not None else self.tradeable


class _Prices(BaseModel):
    prices: list[_Price]


class _StreamFrame(BaseModel):
    type: Literal["PRICE", "HEARTBEAT"]


class OandaClient:
    def __init__(self, connection: Connection, secrets: SecretStore | None = None,
                 *, transport: httpx.AsyncBaseTransport | None = None):
        self.connection = connection
        self.secrets = secrets or SecretStore()
        self.transport = transport
        self.base = "https://api-fxpractice.oanda.com" if connection.environment == "practice" else "https://api-fxtrade.oanda.com"

    async def stream_prices(self, instruments: dict[str, str]) -> AsyncIterator[Quote]:
        """Authenticated bounded NDJSON stream; heartbeat frames never call a model."""
        if not instruments or len(instruments) > 100:
            raise ValueError("A price stream needs 1–100 instruments")
        for symbol in instruments:
            self.validate_symbol(symbol)
        token = self.secrets.resolve(self.connection.secret_ref)
        origin = "https://stream-fxpractice.oanda.com" if self.connection.environment == "practice" else "https://stream-fxtrade.oanda.com"
        transport = self.transport or PinnedDNSAsyncTransport()
        mounts = None if self.transport else httpx_env_proxy_mounts()
        try:
            async with httpx.AsyncClient(transport=transport, mounts=mounts,
                    timeout=httpx.Timeout(15, connect=20), follow_redirects=False) as client:
                async with client.stream("GET", origin + f"/v3/accounts/{self.connection.account_id}/pricing/stream",
                        params={"instruments": ",".join(sorted(instruments)), "snapshot": "true"},
                        headers={"Authorization": "Bearer " + token.reveal()}) as response:
                    if response.status_code != 200:
                        raise ProviderUnavailableError(f"OANDA stream rejected (HTTP {response.status_code})")
                    pending = b""
                    # Do not request a minimum chunk size: buffering until 4 KiB
                    # would delay small price/heartbeat frames for many seconds.
                    async for chunk in response.aiter_bytes():
                        pending += chunk
                        if len(pending) > 65536:
                            raise ProviderUnavailableError("OANDA stream frame exceeds bounded size")
                        while b"\n" in pending:
                            line, pending = pending.split(b"\n", 1)
                            if not line.strip():
                                continue
                            frame = token.redact(json.loads(line))
                            if parse_provider(_StreamFrame, frame).type == "HEARTBEAT":
                                continue
                            price = parse_provider(_Price, frame)
                            if price.instrument not in instruments:
                                continue
                            bid, ask = price.bids[0].price, price.asks[0].price
                            if not bid.is_finite() or not ask.is_finite() or not 0 < bid <= ask:
                                raise ProviderUnavailableError("OANDA stream returned invalid pricing")
                            yield Quote(canonical_instrument=instruments[price.instrument],
                                provider_instrument=price.instrument, time=price.time, bid=bid, ask=ask,
                                source="oanda", fetched_at=datetime.now(timezone.utc), tradable=price.is_tradeable)
                    raise ProviderUnavailableError("OANDA price stream ended")
        except (httpx.HTTPError, ValueError):
            raise ProviderUnavailableError("OANDA price stream unavailable") from None

    async def _get(self, path: str, params: dict[str, str] | None = None) -> object:
        token = self.secrets.resolve(self.connection.secret_ref)
        transport = self.transport or PinnedDNSAsyncTransport()
        mounts = None if self.transport else httpx_env_proxy_mounts()
        async with httpx.AsyncClient(transport=transport, mounts=mounts, timeout=20, follow_redirects=False) as client:
            for attempt in range(3):
                try:
                    response = await client.get(self.base + path, params=params,
                                                headers={"Authorization": "Bearer " + token.reveal()})
                    if response.status_code == 429 or response.status_code >= 500:
                        if attempt < 2:
                            await asyncio.sleep(.1 * 2 ** attempt)
                            continue
                    if response.status_code >= 300:
                        raise ProviderUnavailableError(f"OANDA read rejected (HTTP {response.status_code})")
                    return token.redact(response.json())
                except (httpx.HTTPError, ValueError):
                    if attempt < 2:
                        await asyncio.sleep(.1 * 2 ** attempt)
                        continue
                    raise ProviderUnavailableError("OANDA read unavailable") from None
        raise ProviderUnavailableError("OANDA read unavailable")

    async def instruments(self) -> list[OandaInstrument]:
        data = await self._get(f"/v3/accounts/{self.connection.account_id}/instruments")
        return parse_provider(_Instruments, data).instruments

    @staticmethod
    def validate_symbol(symbol: str) -> None:
        import re
        if not re.fullmatch(r"[A-Z0-9_]{3,40}", symbol):
            raise ValueError("Invalid OANDA instrument")

    async def quote(self, symbol: str, canonical: str) -> Quote:
        self.validate_symbol(symbol)
        data = await self._get(f"/v3/accounts/{self.connection.account_id}/pricing", {"instruments": symbol})
        prices = parse_provider(_Prices, data).prices
        price = next((p for p in prices if p.instrument == symbol), None)
        if price is None:
            raise ProviderUnavailableError("OANDA returned no quote for this instrument")
        return Quote(canonical_instrument=canonical, provider_instrument=symbol, time=price.time,
                     bid=price.bids[0].price, ask=price.asks[0].price, source="oanda",
                     fetched_at=datetime.now(timezone.utc), tradable=price.is_tradeable)

    async def candles(self, symbol: str, canonical: str, timeframe: str, *, count: int = 500,
                      before: str | None = None, price: Literal["M"] = "M") -> list[Candle]:
        self.validate_symbol(symbol)
        if timeframe not in GRANULARITIES or not 1 <= count <= 5000:
            raise ValueError("Unsupported candle timeframe or count")
        params = {"granularity": timeframe, "count": str(count), "price": price}
        if before:
            params["to"] = datetime.fromisoformat(before.replace("Z", "+00:00")).isoformat()
        data = await self._get(f"/v3/instruments/{symbol}/candles", params)
        now = datetime.now(timezone.utc)
        candles = [Candle(canonical_instrument=canonical, provider_instrument=symbol, time=c.time,
                       open=c.mid.o, high=c.mid.h, low=c.mid.low, close=c.mid.c,
                       volume=c.volume, complete=c.complete, source="oanda", fetched_at=now)
                for c in parse_provider(_Candles, data).candles]
        from nanobot.market.cache import MarketCache
        MarketCache().put(symbol, canonical, timeframe, candles)
        return candles
