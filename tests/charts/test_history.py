from datetime import timedelta

from nanobot.charts.controller import candle_time, chart_candles
from nanobot.charts.history import ChartHistory
from nanobot.market.cache import CandleSeries
from nanobot.session.records import RecordStore


def test_historical_window_survives_new_live_evidence_and_restart(workstation, monkeypatch):
    charts, controller, actor, chart, data = workstation
    history = ChartHistory(RecordStore("history", CandleSeries, charts.records.journal))
    monkeypatch.setattr("nanobot.charts.history.ChartHistory", lambda: history)
    old = [c.model_copy(update={"time": c.time - timedelta(days=100)}) for c in data]
    window = history.put(chart, old)
    chart.history_window_id = window.id
    chart.visible_range = (candle_time(old[0]), candle_time(old[-1]))
    chart = charts.update(chart, actor, chart.revision)
    controller.cache.put("XAU_USD", "gold", "H1", data)
    assert chart_candles(chart, controller.cache) == old
    restored = charts.get(chart.id, actor)
    assert history.get(restored).candles == old
    assert restored.data_revision == window.data_revision
    # A zoom into the saved historical window uses the same evidence, not recent candles.
    restored.visible_range = (candle_time(old[40]), candle_time(old[80]))
    assert chart_candles(restored, controller.cache) == old
