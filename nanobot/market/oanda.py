"""Controlled OANDA reads. Credentials exist only in the trusted HTTP request."""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from nanobot.market.models import Candle, Connection, Quote
from nanobot.security.network import PinnedDNSAsyncTransport, httpx_env_proxy_mounts
from nanobot.security.secrets import SecretStore

GRANULARITIES = ("S5", "S10", "S15", "S30", "M1", "M2", "M4", "M5", "M10", "M15", "M30", "H1", "H2", "H3", "H4", "H6", "H8", "H12", "D", "W", "M")


class ProviderUnavailableError(RuntimeError):
    """Sanitized exception: never carry request/response/authentication objects."""


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


class _Prices(BaseModel):
    prices: list[_Price]


_ModelT = TypeVar("_ModelT", bound=BaseModel)


def parse_provider(model: type[_ModelT], data: object) -> _ModelT:
    try:
        return model.model_validate(data)
    except ValidationError:
        raise ProviderUnavailableError("Provider returned invalid structured data") from None


class OandaClient:
    def __init__(self, connection: Connection, secrets: SecretStore | None = None,
                 *, transport: httpx.AsyncBaseTransport | None = None):
        self.connection = connection
        self.secrets = secrets or SecretStore()
        self.transport = transport
        self.base = "https://api-fxpractice.oanda.com" if connection.environment == "practice" else "https://api-fxtrade.oanda.com"

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
                    return response.json()
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
                     fetched_at=datetime.now(timezone.utc), tradable=price.tradeable)

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
        return [Candle(canonical_instrument=canonical, provider_instrument=symbol, time=c.time,
                       open=c.mid.o, high=c.mid.h, low=c.mid.low, close=c.mid.c,
                       volume=c.volume, complete=c.complete, source="oanda", fetched_at=now)
                for c in parse_provider(_Candles, data).candles]
