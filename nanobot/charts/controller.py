"""Semantic viewport operations over the existing chart and normalized evidence."""
from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nanobot.charts.state import ChartActor, ChartService, CloudChart
from nanobot.market.cache import MarketCache
from nanobot.market.models import Candle


class ViewOperation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["reframe", "zoom", "pan", "jump", "range"]
    candle_count: int | None = Field(default=None, ge=2, le=5000)
    factor: Decimal = Field(default=Decimal(1), ge=Decimal("0.1"), le=Decimal(10))
    bars: int = Field(default=0, ge=-5000, le=5000)
    timestamp: int | None = Field(default=None, ge=0)
    visible_range: tuple[int, int] | None = None
    right_spacing: int | None = Field(default=None, ge=0, le=500)


def chart_candles(chart: CloudChart, cache: MarketCache | None = None) -> list[Candle]:
    return (cache or MarketCache()).get(chart.provider_instrument, chart.canonical_instrument,
                                      chart.timeframe).candles


def candle_time(candle: Candle) -> int:
    return int(candle.time.timestamp() * 1000)


def visible_candles(chart: CloudChart, candles: list[Candle]) -> list[Candle]:
    if chart.visible_range:
        start, end = chart.visible_range
        return [c for c in candles if start <= candle_time(c) <= end][-chart.candle_count:]
    return candles[-chart.candle_count:]


class ChartController:
    def __init__(self, service: ChartService, cache: MarketCache | None = None):
        self.service = service
        self.cache = cache or MarketCache()

    def view(self, chart: CloudChart, actor: ChartActor, revision: int,
             action: ViewOperation) -> CloudChart:
        data = chart_candles(chart, self.cache)
        if not data:
            raise ValueError("Load market candles before operating the viewport")
        times = [candle_time(c) for c in data]
        count = action.candle_count or chart.candle_count
        end = len(data) - 1
        if chart.visible_range:
            range_end = chart.visible_range[1]
            end = min(range(len(times)), key=lambda i: abs(times[i] - range_end))
        if action.operation == "zoom":
            count = max(2, min(5000, int(Decimal(count) / action.factor)))
        elif action.operation == "pan":
            end = max(1, min(len(times) - 1, end + action.bars))
        elif action.operation == "jump":
            if action.timestamp is None:
                raise ValueError("Jump requires a market timestamp")
            timestamp = action.timestamp
            end = min(range(len(times)), key=lambda i: abs(times[i] - timestamp))
            end = max(1, end)
        elif action.operation == "reframe":
            end = len(times) - 1
        elif action.operation == "range":
            if action.visible_range is None or action.visible_range[0] >= action.visible_range[1]:
                raise ValueError("Range requires increasing market timestamps")
            chart.visible_range = action.visible_range
            chart.candle_count = count
            if action.right_spacing is not None:
                chart.right_spacing = action.right_spacing
            return self.service.update(chart, actor, revision)
        chart.candle_count = count
        chart.visible_range = (times[max(0, end - count + 1)], times[end])
        if action.right_spacing is not None:
            chart.right_spacing = action.right_spacing
        return self.service.update(chart, actor, revision)

    def inspect(self, chart: CloudChart, *, timestamp: int | None = None,
                index: int | None = None) -> Candle:
        data = chart_candles(chart, self.cache)
        if (timestamp is None) == (index is None):
            raise ValueError("Specify exactly one candle timestamp or chronological index")
        if index is not None:
            if index < 0 or index >= len(data):
                raise ValueError("Candle index outside cached history")
            return data[index]
        for candle in data:
            if candle_time(candle) == timestamp:
                return candle
        raise ValueError("Exact candle timestamp not present; load the requested history")
