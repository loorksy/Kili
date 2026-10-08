"""Bounded, protected normalized evidence cache; never a memory or scheduler."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime

from pydantic import Field

from nanobot.market.models import Candle
from nanobot.session.records import RecordStore, RuntimeRecord


class CandleSeries(RuntimeRecord):
    candles: list[Candle] = Field(default_factory=list, max_length=5000)
    data_revision: str = ""


class MarketCache:
    def __init__(self, records: RecordStore[CandleSeries] | None = None):
        self.records = records or RecordStore("market_candles", CandleSeries)

    @staticmethod
    def identity(symbol: str, canonical: str, timeframe: str) -> str:
        return hashlib.sha256(json.dumps(["oanda", symbol, canonical, timeframe]).encode()).hexdigest()

    def get(self, symbol: str, canonical: str, timeframe: str) -> CandleSeries:
        return self.records.get(self.identity(symbol, canonical, timeframe))

    def put(self, symbol: str, canonical: str, timeframe: str, candles: list[Candle]) -> CandleSeries:
        identity = self.identity(symbol, canonical, timeframe)
        for attempt in range(3):
            try:
                series = self.records.get(identity)
            except ValueError:
                try:
                    series = self.records.create(CandleSeries(id=identity))
                except sqlite3.IntegrityError:
                    series = self.records.get(identity)
            merged = {c.time: c for c in series.candles}
            merged.update({c.time: c for c in candles})
            series.candles = [merged[t] for t in sorted(merged)][-5000:]
            evidence = [c.model_dump(mode="json", exclude={"fetched_at"}) for c in series.candles]
            series.data_revision = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
            try:
                return self.records.save(series)
            except ValueError:
                if attempt == 2:
                    raise
        raise ValueError("Market evidence revision conflict")

    @staticmethod
    def page(series: CandleSeries, count: int, before: str | None) -> list[Candle]:
        boundary = datetime.fromisoformat(before.replace("Z", "+00:00")) if before else None
        if boundary is not None and boundary.tzinfo is None:
            raise ValueError("History boundary requires a timezone")
        return [c for c in series.candles if boundary is None or c.time < boundary][-count:]
