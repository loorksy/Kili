import json

import pytest

from nanobot.agent.tools.chart import ChartTool
from nanobot.agent.tools.context import RequestContext, ToolContext, request_context
from nanobot.charts.state import Annotation, ChartActor, ChartPoint, ChartService, CloudChart
from nanobot.config.schema import ToolsConfig
from nanobot.security.actions import ActionStore
from nanobot.session.records import RecordStore


def service(tmp_path):
    return ChartService(RecordStore("charts",CloudChart,ActionStore(tmp_path / "state.db")))


def test_chart_restart_concurrency_and_private_shared_permissions(tmp_path):
    charts = service(tmp_path)
    primary = ChartActor(principal="websocket:main")
    worker = ChartActor(principal="subagent:1",worker_id="worker-1",parent_principal=primary.principal)
    chart = charts.create(primary,"gold-usd","XAU_USD","H1")
    chart.annotations.append(Annotation(id="annotation_"+"a"*32,type="horizontal_line",points=[ChartPoint(value="2700")],created_by=primary.principal))
    chart.annotation_revision += 1
    saved = charts.update(chart,primary,chart.revision)
    reopened = service(tmp_path).get(chart.id, primary)
    assert reopened.annotations[0].points[0].value == 2700
    assert reopened.revision == saved.revision
    with pytest.raises(ValueError,match="conflict"):
        charts.update(chart, primary, chart.revision)
    with pytest.raises(PermissionError):
        charts.get(chart.id,ChartActor(principal="websocket:other"))
    private = charts.create(worker,"gold-usd","XAU_USD","H4")
    with pytest.raises(PermissionError):
        charts.get(private.id,ChartActor(principal="subagent:2",worker_id="worker-2"))
    assert charts.get(private.id,primary).id == private.id
    shared = charts.create(primary,"gold-usd","XAU_USD","D","SHARED")
    shared.annotations.append(private.annotations[0] if private.annotations else reopened.annotations[0])
    charts.update(shared,worker,shared.revision)
    tampered = reopened.model_copy(update={"owner_scope":"SHARED"})
    with pytest.raises(PermissionError,match="ownership"):
        charts.update(tampered,primary,tampered.revision)


async def test_structured_chart_tool_mutations_and_contract(tmp_path, monkeypatch):
    from unittest.mock import AsyncMock

    from nanobot.market.models import Connection
    charts = service(tmp_path)
    monkeypatch.setattr("nanobot.agent.tools.chart.ChartService",lambda:charts)
    ctx = ToolContext(config=ToolsConfig(),workspace=str(tmp_path))
    ctx.config.integrations.metaapi = Connection(secret_ref="test", account_id="practice")
    monkeypatch.setattr("nanobot.market.broker.BrokerMarket.verify", AsyncMock())
    monkeypatch.setattr("nanobot.market.broker.BrokerMarket.timeframes", AsyncMock(return_value=("H1", "H4")))
    tool = ChartTool(ctx)
    with request_context(RequestContext(channel="websocket",chat_id="main",session_key="websocket:main")):
        result = await tool.execute(operation="create",canonical_instrument="gold-usd",provider_instrument="XAU_USD",timeframe="H1")
        contract = json.loads(result.split("\n")[1])
        assert contract["type"] == "trading_chart" and "candles" not in contract
        chart_id = contract["chart_id"]
        await tool.execute(operation="add_annotation",chart_id=chart_id,expected_revision=0,
                           annotation_type="note",points=[{"value":"2700"}],text="Evidence level")
        state = json.loads(await tool.execute(operation="get",chart_id=chart_id))
        annotation = state["annotations"][0]
        await tool.execute(operation="update_annotation",chart_id=chart_id,expected_revision=1,
                           annotation_id=annotation["id"],points=[{"value":"2701"}],text="Updated")
        await tool.execute(operation="set_timeframe",chart_id=chart_id,expected_revision=2,timeframe="H4")
        await tool.execute(operation="remove_annotation",chart_id=chart_id,expected_revision=3,annotation_id=annotation["id"])
        state = json.loads(await tool.execute(operation="get",chart_id=chart_id))
        assert state["timeframe"] == "H4" and state["annotations"] == []
