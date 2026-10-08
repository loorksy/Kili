"""Existing authenticated HTTP snapshots and WebSocket mutations for chart resources."""
from __future__ import annotations

from typing import Any

from nanobot.agent.tools.chart import ChartRequest, ChartTool
from nanobot.agent.tools.context import RequestContext, ToolContext, request_context
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.queue import MessageBus
from nanobot.charts.state import ChartActor, ChartService
from nanobot.config.schema import Config
from nanobot.market.cache import MarketCache
from nanobot.market.oanda import OandaClient, ProviderUnavailableError
from nanobot.security.actions import ActionStore
from nanobot.session.manager import SessionManager


async def chart_snapshot(config: Config, chart_id: str, principal: str,
                         *, candles: bool = False, before: str | None = None, count: int = 500) -> dict[str, object]:
    if not config.tools.integrations.charts_enabled:
        raise PermissionError("Cloud charts are disabled")
    service = ChartService()
    chart = service.get(chart_id, ChartActor(principal=principal))
    if not candles:
        return chart.model_dump(mode="json")
    if config.tools.integrations.oanda is None:
        raise ValueError("OANDA connection is not configured")
    cache = MarketCache()
    stale = False
    try:
        data = await OandaClient(config.tools.integrations.oanda).candles(
            chart.provider_instrument, chart.canonical_instrument, chart.timeframe, count=count, before=before)
    except ProviderUnavailableError:
        stale = True
        series = cache.get(chart.provider_instrument, chart.canonical_instrument, chart.timeframe)
        data = cache.page(series, count, before)
        if not data:
            raise ValueError("Market history is unavailable") from None
    series = cache.get(chart.provider_instrument, chart.canonical_instrument, chart.timeframe)
    return {"candles": [c.model_dump(mode="json") for c in data], "data_revision": series.data_revision,
            "chart_id": chart.id, "timeframe": chart.timeframe, "before": before, "stale": stale}



async def update_chart(config: Config, sessions: SessionManager, bus: MessageBus,
                       principal: str, payload: dict[str, Any]) -> dict[str, object]:
    if not config.tools.integrations.charts_enabled:
        raise PermissionError("Cloud charts are disabled")
    # Validate once before binding an authenticated user interaction.
    parsed = ChartRequest.model_validate(payload)
    ctx = ToolContext(config=config.tools, workspace=str(sessions.workspace), bus=bus, sessions=sessions)
    registry = ToolRegistry()
    registry.register(ChartTool(ctx))
    channel, _, chat_id = principal.partition(":")
    with request_context(RequestContext(channel=channel, chat_id=chat_id, session_key=principal)):
        result = await registry.execute("chart", parsed.model_dump(exclude_none=True))
    if getattr(result, "is_error", False):
        raise ValueError(str(result))
    if not parsed.chart_id:
        raise ValueError("Client changes require an existing chart id")
    return ChartService().get(parsed.chart_id, ChartActor(principal=principal)).model_dump(mode="json")


def resolve_approval(principal: str, approval_id: str, approve: bool) -> dict[str, object]:
    record = ActionStore().resolve(approval_id, principal=principal, approve=approve)
    return {"id": record.id, "status": record.status}
