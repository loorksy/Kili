"""Broker-native market evidence for every exact symbol advertised by an account."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator

from nanobot.market.models import Candle, Quote
from nanobot.market.provider import TIMEFRAMES, ProviderUnavailableError
from nanobot.trading.metaapi import MetaApiClient
from nanobot.trading.sdk_bridge import account_bridge

# Actual documented MetaApi historical-candle granularities. The adapter accepts
# Nanobot's existing chart labels without inventing unsupported seconds bars.
MT4_TIMEFRAMES = ("M1", "M5", "M15", "M30", "H1", "H4", "D", "W", "M")


class BrokerInstrument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    display_name: str
    canonical_instrument: str
    account_id: str
    source: str = "metaapi"


class _BrokerCandle(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    symbol: str
    time: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    tick_volume: int | None = Field(default=None, alias="tickVolume", ge=0)

    @field_validator("time")
    @classmethod
    def aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Broker candle timestamps require UTC offsets")
        return value.astimezone(timezone.utc)


class BrokerMarket:
    def __init__(self, client: MetaApiClient):
        self.client = client
        self.connection = client.connection

    @staticmethod
    def validate_symbol(symbol: str) -> str:
        return MetaApiClient.validate_symbol(symbol)

    async def timeframes(self) -> tuple[str, ...]:
        account = await self.client.connection_state()
        return tuple(TIMEFRAMES) if account.platform_version == 5 else MT4_TIMEFRAMES

    def canonical(self, symbol: str) -> str:
        self.client.validate_symbol(symbol)
        # Broker-native identity is account scoped. No suffix stripping or
        # assumed equivalence between differently named broker instruments.
        from nanobot.trading.instruments import InstrumentMappings
        return InstrumentMappings.native_identity(self.connection.account_id, symbol)

    async def instruments(self) -> list[BrokerInstrument]:
        from nanobot.trading.instruments import InstrumentMappings
        symbols = await self.client.symbols()
        InstrumentMappings().register_catalog(self.connection.account_id, symbols)
        return [BrokerInstrument(name=symbol, display_name=symbol, canonical_instrument=self.canonical(symbol),
                                 account_id=self.connection.account_id) for symbol in symbols]

    async def verify(self, symbol: str, canonical: str) -> None:
        self.client.validate_symbol(symbol)
        if symbol not in await self.client.symbols():
            raise ValueError("Instrument is not available from this broker account")
        if canonical != self.canonical(symbol):
            # Existing explicitly verified canonical mappings remain usable;
            # arbitrary model labels never create an execution mapping.
            from nanobot.trading.instruments import InstrumentMappings
            mapping = InstrumentMappings().require(self.connection.account_id, canonical)
            if mapping.provider_symbol != symbol:
                raise ValueError("Canonical instrument maps to another broker symbol")

    async def quote(self, symbol: str, canonical: str) -> Quote:
        await self.verify(symbol, canonical)
        price = await self.client.price(symbol)
        return Quote(canonical_instrument=canonical, provider_instrument=symbol, account_id=self.connection.account_id,
                     time=datetime.fromisoformat(price.time.replace("Z", "+00:00")), bid=price.bid, ask=price.ask,
                     source="metaapi", fetched_at=datetime.now(timezone.utc))

    async def candles(self, symbol: str, canonical: str, timeframe: str, *, count: int = 500,
                      before: str | None = None) -> list[Candle]:
        await self.verify(symbol, canonical)
        if timeframe not in await self.timeframes() or not 1 <= count <= 5000:
            raise ValueError("Unsupported broker timeframe or candle count; maximum view size is 5000")
        boundary = datetime.fromisoformat(before.replace("Z", "+00:00")) if before else None
        if boundary is not None and boundary.tzinfo is None:
            raise ValueError("Historical boundary requires timezone")
        bars: dict[datetime, _BrokerCandle] = {}
        cursor = boundary
        bridge = account_bridge(self.connection, self.client.secrets)
        for _ in range(6):
            remaining = count - len(bars)
            if remaining <= 0:
                break
            data = await bridge.request("candles", {
                "symbol": symbol, "timeframe": TIMEFRAMES[timeframe], "limit": min(1000, remaining + (1 if cursor else 0)),
                "start": cursor.isoformat() if cursor else None,
            })
            try:
                page = TypeAdapter(list[_BrokerCandle]).validate_python(data)
            except ValueError:
                raise ProviderUnavailableError("Broker returned invalid candles") from None
            eligible = [bar for bar in page if cursor is None or bar.time < cursor]
            if not eligible:
                break
            bars.update({bar.time: bar for bar in eligible})
            cursor = min(bar.time for bar in eligible)
        fetched = datetime.now(timezone.utc)
        normalized: list[Candle] = []
        # The provider returns historical pages backwards. Sort/deduplicate and
        # use a following bar to prove completion; the newest bar stays partial.
        ordered = sorted(bars.values(), key=lambda bar: bar.time)
        for index, bar in enumerate(ordered):
            if bar.symbol != symbol or not bar.low <= min(bar.open, bar.close) <= max(bar.open, bar.close) <= bar.high:
                raise ProviderUnavailableError("Broker candle identity or OHLC range is invalid")
            if boundary is not None and bar.time >= boundary:
                continue
            normalized.append(Candle(canonical_instrument=canonical, provider_instrument=symbol,
                account_id=self.connection.account_id, time=bar.time, open=bar.open, high=bar.high,
                low=bar.low, close=bar.close, volume=bar.tick_volume, complete=index < len(ordered) - 1,
                source="metaapi", fetched_at=fetched))
        result = normalized[-count:]
        from nanobot.market.cache import MarketCache
        MarketCache(provider="metaapi", account_id=self.connection.account_id).put(symbol, canonical, timeframe, result)
        return result
