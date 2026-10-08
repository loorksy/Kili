import pytest

from nanobot.charts.controller import ViewOperation, candle_time, visible_candles
from nanobot.charts.state import ChartService, CloudChart


def test_semantic_navigation_restart_and_exact_inspection(workstation):
    service, controller, actor, chart, data = workstation
    chart = controller.view(chart, actor, 0, ViewOperation(operation="reframe", candle_count=20))
    assert len(visible_candles(chart, data)) == 20
    chart = controller.view(chart, actor, chart.revision, ViewOperation(operation="zoom", factor=2))
    assert chart.candle_count == 10
    chart = controller.view(chart, actor, chart.revision, ViewOperation(operation="pan", bars=-30))
    assert chart.visible_range[1] == candle_time(data[69])
    chart = controller.view(chart, actor, chart.revision, ViewOperation(operation="jump", timestamp=candle_time(data[50])))
    assert chart.visible_range[1] == candle_time(data[50])
    reopened = ChartService(service.records).get(chart.id, actor)
    assert reopened.visible_range == chart.visible_range
    assert controller.inspect(chart, timestamp=candle_time(data[50])).close == 150
    assert controller.inspect(chart, index=50).complete
    with pytest.raises(ValueError, match="Exact"):
        controller.inspect(chart, timestamp=1)
    with pytest.raises(ValueError, match="conflict"):
        controller.view(chart, actor, 0, ViewOperation(operation="pan", bars=10))


def test_legacy_defaults_and_bounded_view(workstation):
    _, controller, actor, chart, _ = workstation
    assert CloudChart.model_validate(chart.model_dump(exclude={"candle_count", "right_spacing", "workstation_version"})).candle_count == 200
    with pytest.raises(ValueError):
        ViewOperation(operation="zoom", factor=0)
    with pytest.raises(ValueError):
        controller.view(chart, actor, 0, ViewOperation(operation="range", visible_range=(2, 1)))
