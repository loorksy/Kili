import io

import pytest
from PIL import Image

from nanobot.charts.capabilities import BUILTIN_DEFAULTS
from nanobot.charts.indicators import IndicatorInstance
from nanobot.charts.native_indicators import native_values
from nanobot.charts.render import render_scene
from nanobot.charts.scene import build_scene
from nanobot.charts.state import Annotation, ChartPoint


@pytest.mark.parametrize("name,params", BUILTIN_DEFAULTS.items())
def test_native_builtin_calculations_are_bounded_and_reproducible(name, params, workstation):
    *_, data = workstation
    first = native_values(name, data, params)
    assert len(first.values) == len(data)
    assert first == native_values(name, data, params)
    assert len(first.figures) <= 8


def test_render_same_authoritative_scene_without_browser(workstation, monkeypatch):
    service, controller, actor, chart, data = workstation
    monkeypatch.setattr("nanobot.charts.controller.MarketCache", lambda: controller.cache)
    chart.annotations.append(Annotation(id="annotation_" + "a" * 32, type="price_zone", points=[
        ChartPoint(timestamp=int(data[20].time.timestamp() * 1000), value=95),
        ChartPoint(timestamp=int(data[40].time.timestamp() * 1000), value=110)], created_by=actor.principal))
    chart.indicator_instances.append(IndicatorInstance(id="study_" + "b" * 32, indicator_id="MA", calc_params=BUILTIN_DEFAULTS["MA"], created_by=actor.principal))
    scene = build_scene(chart, actor)
    assert scene.candles == data
    assert scene.metadata()["annotation_ids"] == [chart.annotations[0].id]
    raw = render_scene(scene)
    assert raw == render_scene(scene)
    assert Image.open(io.BytesIO(raw)).size == (1000, 640)
    assert scene.series
    with pytest.raises(ValueError):
        render_scene(scene, 100000, 100000)


def test_native_invalid_params_and_private_worker_environment(workstation):
    *_, data = workstation
    with pytest.raises(ValueError):
        native_values("MA", data, [float("nan")] * 4)
    with pytest.raises(ValueError):
        native_values("require('fs')", data, [])
