import json

import pytest

from nanobot.agent.tools.chart import ChartTool
from nanobot.agent.tools.context import RequestContext, ToolContext, request_context
from nanobot.charts.work import temporary_drawings
from nanobot.config.schema import ToolsConfig


async def test_temporary_analysis_explicit_publication_and_object_cas(workstation, tmp_path, monkeypatch):
    service, _, actor, chart, _ = workstation
    tool = ChartTool(ToolContext(config=ToolsConfig(), workspace=str(tmp_path)))
    tool.service = service
    with request_context(RequestContext(channel="websocket", chat_id="main", session_key=actor.principal)):
        await tool.execute(operation="add_annotation", chart_id=chart.id, expected_revision=0,
            temporary=True, annotation_type="horizontal_line", points=[{"value": "2700"}])
        assert service.get(chart.id, actor).annotations == []
        temporary = temporary_drawings(chart.id, actor.principal)[0]
        assert temporary_drawings(chart.id, "websocket:other") == []
        await tool.execute(operation="publish_annotation", chart_id=chart.id, expected_revision=0, annotation_id=temporary.id)
        assert len(service.get(chart.id, actor).annotations) == 1
        assert temporary_drawings(chart.id, actor.principal) == []
        await tool.execute(operation="set_timeframe", chart_id=chart.id, expected_revision=1, timeframe="H4")
        # Unrelated chart change merges, but a stale edit to the same object cannot.
        await tool.execute(operation="update_annotation", chart_id=chart.id, expected_revision=1,
            object_revision=0, annotation_id=temporary.id, annotation_type="horizontal_line", points=[{"value": "2710"}])
        with pytest.raises(ValueError, match="Drawing revision"):
            await tool.execute(operation="remove_annotation", chart_id=chart.id, expected_revision=1,
                object_revision=0, annotation_id=temporary.id)
        result = json.loads(await tool.execute(operation="get", chart_id=chart.id))
        assert result["annotations"][0]["revision"] == 1
        assert result["timeframe"] == "H4"
