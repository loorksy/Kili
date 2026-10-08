"""Protected bounded historical windows, independent of live evidence cache eviction."""
from __future__ import annotations

import hashlib
import json

from nanobot.charts.state import CloudChart
from nanobot.market.cache import CandleSeries
from nanobot.market.models import Candle
from nanobot.session.records import RecordStore


class ChartHistory:
    def __init__(self, records: RecordStore[CandleSeries] | None = None):
        self.records = records

    def _store(self, chart: CloudChart) -> RecordStore[CandleSeries]:
        return self.records or RecordStore("chart_history:" + chart.id, CandleSeries)

    def get(self, chart: CloudChart) -> CandleSeries:
        if not chart.history_window_id:
            raise ValueError("No historical window selected")
        return self._store(chart).get(chart.history_window_id)

    def put(self, chart: CloudChart, candles: list[Candle]) -> CandleSeries:
        ordered = sorted({c.time: c for c in candles}.values(), key=lambda c: c.time)
        if not 2 <= len(ordered) <= 5000:
            raise ValueError("Historical view requires 2–5000 candles")
        for candle in ordered:
            if (candle.provider_instrument != chart.provider_instrument or candle.canonical_instrument != chart.canonical_instrument
                    or candle.source != chart.provider or candle.account_id != chart.account_id):
                raise ValueError("Historical evidence does not match chart instrument")
        identity = hashlib.sha256(json.dumps([chart.provider, chart.account_id, chart.provider_instrument, chart.canonical_instrument, chart.timeframe,
            ordered[0].time.isoformat(), ordered[-1].time.isoformat()]).encode()).hexdigest()
        evidence = [c.model_dump(mode="json", exclude={"fetched_at"}) for c in ordered]
        digest = hashlib.sha256(json.dumps(evidence, sort_keys=True).encode()).hexdigest()
        store = self._store(chart)
        try:
            previous = store.get(identity)
        except ValueError:
            result = store.create(CandleSeries(id=identity, candles=ordered, data_revision=digest))
        else:
            previous.candles, previous.data_revision = ordered, digest
            result = store.save(previous)
        # Retain sixteen bounded windows and never evict the linked active window.
        recent = sorted(store.list(), key=lambda record: record.updated_at, reverse=True)
        keep = {record.id for record in recent[:16]} | {identity, chart.history_window_id}
        with store.execution_write(), store.journal.transaction() as db:
            for record in recent:
                if record.id not in keep:
                    db.execute("DELETE FROM records WHERE namespace=? AND id=?", (store.namespace, record.id))
        return result
