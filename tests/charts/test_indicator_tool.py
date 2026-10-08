import json
from decimal import Decimal

import pytest

from nanobot.agent.tools.chart_indicator import ChartIndicatorTool
from nanobot.agent.tools.context import RequestContext, ToolContext, request_context
from nanobot.charts.indicators import CustomIndicator, IndicatorRegistry
from nanobot.config.schema import ToolsConfig
from nanobot.security.actions import ActionStore
from nanobot.session.records import RecordStore


def definition():
    return {"name": "Confirmed structure", "description": "Confirm swing highs after three following candles", "parameters": {
        "right": {"default": "3", "minimum": "1", "maximum": "10"}}, "nodes": [
        {"op": "input", "field": "high"}, {"op": "swing_high", "inputs": [0], "window": 3, "offset_parameter": "right"}],
        "outputs": [{"name": "high", "node": 1, "kind": "marker"}]}


async def test_factory_import_version_pin_and_control(workstation, tmp_path, monkeypatch):
    charts, controller, actor, chart, data = workstation
    monkeypatch.setattr("nanobot.charts.controller.MarketCache", lambda: controller.cache)
    registry = IndicatorRegistry(RecordStore("custom_indicators", CustomIndicator, ActionStore(tmp_path / "state.db")))
    tool = ChartIndicatorTool(ToolContext(config=ToolsConfig(), workspace=str(tmp_path)))
    tool.registry, tool.charts = registry, charts
    with request_context(RequestContext(channel="websocket", chat_id="main", session_key=actor.principal)):
        # Deterministic model output for the natural-language request goes through final IR validation.
        first = json.loads(await tool.execute(operation="create", definition=definition()))
        saved = json.loads(await tool.execute(operation="add", chart_id=chart.id, expected_revision=0, indicator_id=first["id"]))
        instance = saved["indicator_instances"][0]
        values = json.loads(await tool.execute(operation="values", chart_id=chart.id, instance_id=instance["id"]))
        assert len(values["timestamps"]) == len(data)
        changed = definition()
        changed["description"] = "Longer confirmation"
        second = json.loads(await tool.execute(operation="create", definition=changed, family_id=first["family_id"]))
        assert second["indicator_version"] == 2
        assert charts.get(chart.id, actor).indicator_instances[0].indicator_id == first["id"]
        with pytest.raises(ValueError, match="conflict"):
            await tool.execute(operation="update", chart_id=chart.id, expected_revision=1,
                instance_id=instance["id"], object_revision=9, parameters={"right": "4"})
        await tool.execute(operation="update", chart_id=chart.id, expected_revision=1,
            instance_id=instance["id"], object_revision=0, parameters={"right": "4"})
        assert charts.get(chart.id, actor).indicator_instances[0].parameters["right"] == Decimal(4)
        upload = tmp_path / "indicator.json"
        upload.write_text(json.dumps(definition()))
        imported = json.loads(await tool.execute(operation="import", path=str(upload)))
        assert imported["source"] == "USER_IMPORTED" and imported["original_filename"] == upload.name
        repeated = json.loads(await tool.execute(operation="import", path=str(upload)))
        assert repeated["id"] == imported["id"]
        malicious = tmp_path / "bad.js"
        malicious.write_text("require('fs').readFileSync('/etc/passwd')")
        with pytest.raises(ValueError, match="scripts"):
            await tool.execute(operation="import", path=str(malicious))
        upload.write_text('{"name":"bad","javascript":"fetch(secrets)"}')
        with pytest.raises(ValueError):
            await tool.execute(operation="import", path=str(upload))


async def test_temporary_indicator_does_not_pollute_chart(workstation, tmp_path):
    charts, _, actor, chart, _ = workstation
    tool = ChartIndicatorTool(ToolContext(config=ToolsConfig(), workspace=str(tmp_path)))
    tool.charts = charts
    with request_context(RequestContext(channel="websocket", chat_id="main", session_key=actor.principal)):
        state = json.loads(await tool.execute(operation="add", temporary=True, chart_id=chart.id, expected_revision=0, indicator_id="EMA"))
        instance = state["temporary_indicator_instances"][0]
        assert charts.records.get(chart.id).indicator_instances == []
        await tool.execute(operation="update", chart_id=chart.id, expected_revision=0, instance_id=instance["id"], calc_params=[3, 6, 9])
        await tool.execute(operation="remove", chart_id=chart.id, expected_revision=0, instance_id=instance["id"])
    assert charts.records.get(chart.id).revision == 0
