"""Chart-only scene assembled from authoritative state and normalized cached candles."""
from __future__ import annotations

from pydantic import BaseModel, Field

from nanobot.charts.controller import candle_time, chart_candles, visible_candles
from nanobot.charts.indicators import IndicatorInstance, IndicatorRegistry, Scalar, evaluate
from nanobot.charts.native_indicators import native_values
from nanobot.charts.state import ChartActor, CloudChart
from nanobot.market.models import Candle


class SceneSeries(BaseModel):
    instance_id: str
    name: str
    kind: str
    pane: str
    color: str
    values: list[Scalar]


class ChartScene(BaseModel):
    scene_version: int = 1
    chart: CloudChart
    candles: list[Candle] = Field(max_length=5000)
    temporary_indicators: list[IndicatorInstance] = Field(default_factory=list)
    series: list[SceneSeries] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    def metadata(self) -> dict[str, object]:
        times = [candle_time(c) for c in self.candles]
        fetched = max((c.fetched_at for c in self.candles), default=None)
        return {"chart_id": self.chart.id, "revision": self.chart.revision, "instrument": self.chart.canonical_instrument,
            "timeframe": self.chart.timeframe, "provider": self.chart.provider, "visible_candles": len(times),
            "visible_range": [times[0], times[-1]] if times else None,
            "last_price": str(self.candles[-1].close) if self.candles else None,
            "last_completed_candle_time": next((candle_time(c) for c in reversed(self.candles) if c.complete), None),
            "annotation_ids": [a.id for a in self.chart.annotations if a.visible],
            "indicators": [{"id": s.instance_id, "series": s.name, "pane": s.pane} for s in self.series],
            "active_indicators": [instance.model_dump(mode="json") for instance in [*self.chart.indicator_instances, *self.temporary_indicators]],
            "legacy_studies": self.chart.studies,
            "fetched_at": fetched.isoformat() if fetched else None,
            "data_revision": self.chart.data_revision, "warnings": self.warnings}


def build_scene(chart: CloudChart, actor: ChartActor, registry: IndicatorRegistry | None = None) -> ChartScene:
    from decimal import Decimal

    from nanobot.charts.capabilities import BUILTIN_DEFAULTS
    data = chart_candles(chart)
    visible = visible_candles(chart, data)
    times = {candle_time(c) for c in visible}
    indexes = [i for i, c in enumerate(data) if candle_time(c) in times]
    from nanobot.charts.work import temporary_drawings, temporary_indicators
    view = chart.model_copy(deep=True)
    existing = {a.id for a in view.annotations}
    view.annotations.extend(a for a in temporary_drawings(chart.id, actor.principal) if a.id not in existing)
    scene = ChartScene(chart=view, candles=visible, temporary_indicators=temporary_indicators(chart.id, actor.principal))
    indicators = registry or IndicatorRegistry()
    principal = actor.parent_principal or actor.principal
    palette = ["#38bdf8", "#fbbf24", "#c084fc", "#fb7185", "#34d399"]
    import hashlib
    legacy = [IndicatorInstance(id="study_" + hashlib.md5(name.encode(), usedforsecurity=False).hexdigest(), indicator_id=name, calc_params=BUILTIN_DEFAULTS[name], pane="main" if name in {"MA", "EMA", "BOLL", "SAR"} else "separate", created_by=chart.owner_reference) for name in chart.studies if name in BUILTIN_DEFAULTS]
    for instance in [*legacy, *chart.indicator_instances, *scene.temporary_indicators]:
        if not instance.visible:
            continue
        if instance.indicator_id in BUILTIN_DEFAULTS:
            try:
                native = native_values(instance.indicator_id, data, instance.calc_params)
            except ValueError:
                scene.warnings.append("Built-in calculation unavailable: " + instance.indicator_id)
                continue
            for j, figure in enumerate(native.figures):
                values = [Decimal(str(native.values[i][figure.key])) if native.values[i].get(figure.key) is not None else None for i in indexes]
                scene.series.append(SceneSeries(instance_id=instance.id, name=figure.key, kind=figure.type,
                    pane=instance.pane, color=palette[j % len(palette)], values=values))
        else:
            record = indicators.get(instance.indicator_id, principal)
            calculated = evaluate(record.definition, data, instance.parameters)
            for output in record.definition.outputs:
                offset = output.anchor_offset
                if output.anchor_offset_parameter:
                    reference = output.anchor_offset_parameter
                    raw_offset = instance.parameters.get(reference, record.definition.parameters[reference].default)
                    if raw_offset != int(raw_offset) or not 0 <= raw_offset <= 512:
                        raise ValueError("Indicator output anchor offset must be a bounded integer")
                    offset = int(raw_offset)
                scene.series.append(SceneSeries(instance_id=instance.id, name=output.name, kind=output.kind,
                    pane=instance.pane, color=output.color, values=[calculated[output.name][i + offset] if i + offset < len(data) else None for i in indexes]))
    approximate = sorted({a.library_name for a in view.annotations if a.visible and a.library_name and a.library_name not in {"horizontalStraightLine", "priceLine", "verticalStraightLine", "segment", "rect", "simpleAnnotation", "simpleTag", "fibonacciLine"}})
    if approximate:
        scene.warnings.append("Raster view uses semantic anchor previews for: " + ", ".join(approximate))
    return scene
