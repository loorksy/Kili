import json

from nanobot.agent.tools.chart import ChartTool
from nanobot.agent.tools.chart_snapshot import ChartSnapshotTool
from nanobot.agent.tools.context import RequestContext, ToolContext, request_context
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.outbound_events import CloudChartChanged
from nanobot.bus.queue import MessageBus
from nanobot.charts.controller import candle_time
from nanobot.config.schema import ToolsConfig


async def test_scripted_analyst_uses_existing_registry_and_chart_not_browser(workstation, tmp_path, monkeypatch):
    charts, controller, actor, chart, data = workstation
    monkeypatch.setattr("nanobot.charts.controller.MarketCache", lambda: controller.cache)
    controller.cache.put("XAU_USD", "gold", "D", data)
    controller.cache.put("XAU_USD", "gold", "H4", data)
    bus = MessageBus()
    context = ToolContext(config=ToolsConfig(), workspace=str(tmp_path), bus=bus)
    chart_tool, snapshot = ChartTool(context), ChartSnapshotTool(context)
    chart_tool.service = snapshot.service = charts
    registry = ToolRegistry()
    registry.register(chart_tool)
    registry.register(snapshot)
    with request_context(RequestContext(channel="websocket", chat_id="main", session_key=actor.principal)):
        async def operation(**parameters):
            current = charts.get(chart.id, actor)
            result = await registry.execute("chart", {"chart_id": chart.id, "expected_revision": current.revision, **parameters})
            assert not getattr(result, "is_error", False), result
            return result
        await operation(operation="set_timeframe", timeframe="D")
        await operation(operation="view", view={"operation": "range", "visible_range": [candle_time(data[10]), candle_time(data[90])], "candle_count": 81})
        daily = json.loads(await registry.execute("chart_snapshot", {"chart_id": chart.id}))
        assert len(daily["candles"]) == 81
        await operation(operation="set_timeframe", timeframe="H4")
        await operation(operation="view", view={"operation": "zoom", "factor": "2"})
        exact = json.loads(await registry.execute("chart", {"operation": "inspect_candle", "chart_id": chart.id, "candle_index": 50}))
        assert exact["close"] == "150"
        await operation(operation="select_drawing_tool", drawing_name="rect")
        points = [{"timestamp": candle_time(data[50]), "value": "105"}, {"timestamp": candle_time(data[60]), "value": "110"}]
        await operation(operation="cursor", points=[points[0]])
        await operation(operation="add_annotation", annotation_type="drawing", drawing_name="rect", points=points)
        visual = await registry.execute("chart_snapshot", {"chart_id": chart.id, "format": "image"})
        assert isinstance(visual, list) and visual[0]["image_url"]["url"].startswith("data:image/png;base64,")
        await operation(operation="set_timeframe", timeframe="H1")
        final = charts.get(chart.id, actor)
        assert final.timeframe == "H1" and final.annotations[0].library_name == "rect"
        events = [await bus.consume_outbound() for _ in range(bus.outbound_size)]
        assert all(isinstance(message.event, CloudChartChanged) for message in events)
        cursor = next(message.event for message in events if message.event.operation == "cursor")
        assert cursor.anchors == ((candle_time(data[50]), "105"),)
    assert charts.records.get(chart.id).annotations == final.annotations


async def test_model_cannot_assert_user_origin(workstation, tmp_path):
    charts, _, actor, chart, _ = workstation
    tool = ChartTool(ToolContext(config=ToolsConfig(), workspace=str(tmp_path)))
    tool.service = charts
    registry = ToolRegistry()
    registry.register(tool)
    with request_context(RequestContext(channel="websocket", chat_id="main", session_key=actor.principal)):
        result = await registry.execute("chart", {"operation": "add_annotation", "chart_id": chart.id,
            "expected_revision": 0, "origin": "USER", "points": [{"value": "100"}]})
        assert getattr(result, "is_error", False)
        assert charts.get(chart.id, actor).annotations == []
