"""Cheap deterministic observation; only a satisfied logical condition wakes the agent."""
from __future__ import annotations

import time
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field, model_validator

from nanobot.market.models import Quote
from nanobot.market.oanda import GRANULARITIES, OandaClient, ProviderUnavailableError
from nanobot.session.records import RecordStore, RuntimeRecord
from nanobot.session.responsibilities import ResponsibilityStore


class MarketWatcher(RuntimeRecord):
    responsibility_id: str
    provider_instrument: str
    canonical_instrument: str
    condition: Literal["above", "below", "cross_above", "cross_below", "new_completed_candle"]
    threshold: Decimal | None = None
    timeframe: str = "H1"
    last_completed_time: datetime | None = None
    interval_ms: int = Field(default=60_000, ge=1000)
    next_check_ms: int
    last_price: Decimal | None = None
    active: bool = True
    fired: bool = False
    observation: Quote | None = None
    failures: int = 0

    @model_validator(mode="after")
    def check_condition(self) -> MarketWatcher:
        OandaClient.validate_symbol(self.provider_instrument)
        if self.condition != "new_completed_candle" and self.threshold is None:
            raise ValueError("Price conditions require a threshold")
        if self.timeframe not in GRANULARITIES:
            raise ValueError("Unsupported watcher timeframe")
        return self


class MarketWatchers:
    def __init__(self, client: OandaClient, responsibilities: ResponsibilityStore,
                 records: RecordStore[MarketWatcher] | None = None):
        self.client, self.responsibilities = client, responsibilities
        self.records = records or RecordStore("market_watchers", MarketWatcher)

    def nearest(self) -> int | None:
        due = [w.next_check_ms for w in self.records.list() if w.active]
        return min(due) if due else None

    async def run_due(self, now_ms: int | None = None) -> None:
        now = now_ms if now_ms is not None else time.time_ns() // 1_000_000
        quotes: dict[str, Quote] = {}
        for watcher in self.records.list():
            if not watcher.active or watcher.next_check_ms > now:
                continue
            responsibility = self.responsibilities.get(watcher.responsibility_id)
            if responsibility.state in {"COMPLETED", "FAILED", "CANCELLED"}:
                watcher.active = False
                self.records.save(watcher)
                continue
            if watcher.condition == "new_completed_candle":
                try:
                    candles = await self.client.candles(watcher.provider_instrument,
                        watcher.canonical_instrument, watcher.timeframe, count=2)
                    latest = max((c.time for c in candles if c.complete), default=None)
                    if latest is not None:
                        if watcher.last_completed_time is not None and latest > watcher.last_completed_time:
                            self.responsibilities.enqueue(watcher.responsibility_id, f"market:{watcher.id}",
                                f"New completed {watcher.timeframe} candle on {watcher.provider_instrument} at {latest.isoformat()}.")
                            watcher.active, watcher.fired = False, True
                        watcher.last_completed_time = latest
                    watcher.failures = 0
                except ProviderUnavailableError:
                    watcher.failures += 1
                watcher.next_check_ms = now + min(3_600_000, watcher.interval_ms * 2 ** min(watcher.failures, 6))
                self.records.save(watcher)
                continue
            assert watcher.threshold is not None
            try:
                quote = quotes.get(watcher.provider_instrument)
                if quote is None:
                    quote = await self.client.quote(watcher.provider_instrument, watcher.canonical_instrument)
                    quotes[watcher.provider_instrument] = quote
            except ProviderUnavailableError:
                watcher.failures += 1
                watcher.next_check_ms = now + min(3_600_000, watcher.interval_ms * 2 ** min(watcher.failures, 6))
                self.records.save(watcher)
                continue
            price, previous = quote.bid, watcher.last_price
            hit = ((watcher.condition == "above" and price >= watcher.threshold)
                   or (watcher.condition == "below" and price <= watcher.threshold)
                   or (watcher.condition == "cross_above" and previous is not None and previous < watcher.threshold <= price)
                   or (watcher.condition == "cross_below" and previous is not None and previous > watcher.threshold >= price))
            watcher.last_price, watcher.observation, watcher.failures = price, quote, 0
            watcher.next_check_ms = now + watcher.interval_ms
            if hit:
                # Persist the wake FIRST. A crash before watcher save repeats the same key.
                self.responsibilities.enqueue(watcher.responsibility_id, f"market:{watcher.id}",
                                               f"Market condition {watcher.condition} {watcher.threshold} satisfied on {watcher.provider_instrument}; observed {price}, source OANDA at {quote.time.isoformat()}.")
                watcher.active, watcher.fired = False, True
            self.records.save(watcher)
