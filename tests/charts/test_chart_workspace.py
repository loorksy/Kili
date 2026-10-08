from unittest.mock import AsyncMock

import pytest

from nanobot.agent.tools.chart import ChartTool
from nanobot.bus.queue import MessageBus
from nanobot.charts.state import ChartActor
from nanobot.config.schema import Config
from nanobot.market.models import Connection
from nanobot.market.oanda import OandaInstrument
from nanobot.session.manager import SessionManager
from nanobot.webui.cloud_resources import list_charts, update_chart


async def test_manual_catalog_preserves_existing_scope_and_parent_read_permissions(workstation, monkeypatch):
    service, _, actor, chart, _ = workstation
    other = service.create(ChartActor(principal="websocket:other"), "eur", "EUR_USD", "H1")
    worker = service.create(ChartActor(principal=actor.principal, worker_id="worker1"), "gold", "XAU_USD", "H1", "WORKER")
    monkeypatch.setattr("nanobot.webui.cloud_resources.ChartService", lambda: service)
    config = Config()
    config.tools.integrations.charts_enabled = True
    result = await list_charts(config, actor.principal)
    ids = {item["chart_id"] for item in result["charts"]}
    assert chart.id in ids and other.id not in ids and worker.id in ids
    with pytest.raises(PermissionError):
        service.require_access(worker, actor, write=True)
    assert result["instruments"] == []


async def test_manual_create_returns_existing_runtime_record_and_reopens(workstation, monkeypatch, tmp_path):
    service, _, actor, _, _ = workstation
    monkeypatch.setattr("nanobot.webui.cloud_resources.ChartService", lambda: service)
    original = ChartTool.__init__
    def initialize(tool, ctx):
        original(tool, ctx)
        tool.service = service
    monkeypatch.setattr(ChartTool, "__init__", initialize)
    item = OandaInstrument(name="XAU_USD", type="METAL", displayName="XAU/USD", pipLocation=-2,
        displayPrecision=3, tradeUnitsPrecision=0, minimumTradeSize="1")
    monkeypatch.setattr("nanobot.market.oanda.OandaClient.instruments", AsyncMock(return_value=[item]))
    config = Config()
    config.tools.integrations.charts_enabled = True
    config.tools.integrations.oanda = Connection(secret_ref="test", account_id="test")
    sessions = SessionManager(tmp_path / "workspace")
    result = await update_chart(config, sessions, MessageBus(), actor.principal,
        {"operation": "create", "provider_instrument": "XAU_USD", "canonical_instrument": "XAU_USD", "timeframe": "H1"})
    assert result["id"] == service.get(result["id"], actor).id
    assert result["annotations"] == []
    with pytest.raises(ValueError, match="advertised"):
        await update_chart(config, sessions, MessageBus(), actor.principal,
            {"operation": "create", "provider_instrument": "XAUUSDm", "canonical_instrument": "XAUUSDm", "timeframe": "H1"})


async def test_public_chart_catalog_requires_token_existing_conversation_and_cannot_mutate(workstation, monkeypatch, tmp_path):
    from types import SimpleNamespace

    from websockets.datastructures import Headers
    from websockets.http11 import Request

    from nanobot.webui.ws_http import GatewayHTTPHandler

    class TokenGate:
        def check_api_token(self, request):
            return request.headers.get("Authorization") == "Bearer fixture"

    service, _, actor, chart, _ = workstation
    monkeypatch.setattr("nanobot.webui.cloud_resources.ChartService", lambda: service)
    config = Config()
    config.tools.integrations.charts_enabled = True
    sessions = SessionManager(tmp_path / "workspace")
    sessions.save(sessions.get_or_create(actor.principal))
    handler = object.__new__(GatewayHTTPHandler)
    handler.tokens, handler.session_manager = TokenGate(), sessions
    handler.settings = SimpleNamespace(config=SimpleNamespace(load=lambda: config))
    path = "/api/webui/cloud-charts"
    query = "?session_key=" + actor.principal
    assert (await handler._handle_cloud_resource(Request(path + query, Headers()), path)).status_code == 401
    headers = Headers({"Authorization": "Bearer fixture"})
    response = await handler._handle_cloud_resource(Request(path + query, headers), path)
    assert response.status_code == 200
    assert chart.id.encode() in bytes(response.body)
    assert (await handler._handle_cloud_resource(Request(path + "?session_key=websocket:missing", headers), path)).status_code == 404
    assert (await handler._handle_cloud_resource(Request(path + "/update" + query, headers), path + "/update")).status_code == 400
    assert service.get(chart.id, actor).revision == 0


async def test_recommendation_cannot_reference_another_private_chart(workstation):
    from nanobot.agent.tools.context import RequestContext, request_context
    from nanobot.agent.tools.market import MarketTool
    from nanobot.market.oanda import OandaClient

    service, _, _, chart, _ = workstation
    tool = MarketTool(OandaClient(Connection(secret_ref="test", account_id="test")))
    # Use the actual scope boundary with this deterministic persisted fixture.
    from unittest.mock import patch
    with patch("nanobot.charts.state.ChartService", return_value=service):
        with request_context(RequestContext(channel="websocket", chat_id="other", session_key="websocket:other")):
            with pytest.raises(PermissionError):
                await tool.execute(operation="recommendation", recommendation={"instrument": "gold", "intent": "WAIT",
                    "summary": "Fixture", "chart_id": chart.id})
