"""Existing authenticated HTTP snapshots and WebSocket mutations for chart resources."""
from __future__ import annotations

import asyncio
from typing import Any

from nanobot.agent.tools.chart import ChartRequest, ChartTool
from nanobot.agent.tools.context import RequestContext, ToolContext, request_context
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.bus.queue import MessageBus
from nanobot.charts.state import ChartActor, ChartService
from nanobot.config.schema import Config
from nanobot.market.broker import BrokerMarket
from nanobot.market.cache import CandleSeries, MarketCache
from nanobot.market.provider import ProviderUnavailableError
from nanobot.security.actions import ActionStore
from nanobot.session.manager import SessionManager
from nanobot.trading.accounts import TradingAccounts


async def list_charts(config: Config, principal: str) -> dict[str, object]:
    if not config.tools.integrations.charts_enabled:
        raise PermissionError("Cloud charts are disabled")
    service = ChartService()
    actor = ChartActor(principal=principal)
    rows: list[dict[str, object]] = []
    for chart in sorted(service.records.list(), key=lambda item: (item.updated_at, item.created_at, item.id)):
        try:
            service.require_access(chart, actor)
        except PermissionError:
            continue
        rows.append(dict(chart.contract()))
    instruments: list[dict[str, str]] = []
    market_unavailable = False
    if config.tools.integrations.broker_accounts():
        try:
            market = BrokerMarket(TradingAccounts(config.tools.integrations).client(principal=principal))
            instruments = [{"name": item.name, "display_name": item.display_name,
                            "canonical_instrument": item.canonical_instrument, "account_id": item.account_id}
                           for item in await market.instruments()]
        except (ProviderUnavailableError, ValueError):
            market_unavailable = True
    return {"charts": rows, "instruments": instruments, "market_unavailable": market_unavailable}


async def chart_snapshot(config: Config, chart_id: str, principal: str,
                         *, candles: bool = False, before: str | None = None, count: int = 500) -> dict[str, object]:
    if not config.tools.integrations.charts_enabled:
        raise PermissionError("Cloud charts are disabled")
    service = ChartService()
    chart = service.get(chart_id, ChartActor(principal=principal))
    if not candles:
        state: dict[str, object] = chart.model_dump(mode="json")
        from nanobot.charts.capabilities import DRAWING_ANCHORS
        from nanobot.charts.work import temporary_drawings, temporary_indicators
        experiments = temporary_indicators(chart.id, principal)
        state["temporary_indicator_instances"] = [s.model_dump(mode="json") for s in experiments]
        state["temporary_annotations"] = [a.model_dump(mode="json") for a in temporary_drawings(chart.id, principal)]
        state["drawing_tools"] = [{"id": name, "anchors": anchors} for name, anchors in DRAWING_ANCHORS.items()]
        if any(instance.indicator_id.startswith("indicator_") for instance in [*chart.indicator_instances, *experiments]):
            from nanobot.charts.controller import candle_time
            from nanobot.charts.scene import build_scene
            custom_view = chart.model_copy(deep=True)
            custom_view.studies = []
            custom_view.indicator_instances = [instance for instance in chart.indicator_instances if instance.indicator_id.startswith("indicator_")]
            scene = await asyncio.to_thread(build_scene, custom_view, ChartActor(principal=principal))
            state["computed_series"] = [series.model_dump(mode="json") for series in scene.series]
            state["computed_timestamps"] = [candle_time(c) for c in scene.candles]
        return state
    if chart.provider != "metaapi" or chart.account_id is None:
        # Preserve read-only historical access under the old source identity;
        # never fetch OANDA or attach these bars to a broker chart.
        from nanobot.charts.controller import chart_candles
        data = MarketCache.page(CandleSeries(id=chart.id, candles=chart_candles(chart)), count, before)
        return {"candles": [c.model_dump(mode="json") for c in data], "data_revision": chart.data_revision,
                "chart_id": chart.id, "timeframe": chart.timeframe, "before": before, "stale": True, "archived": True}
    market = BrokerMarket(TradingAccounts(config.tools.integrations).client(chart.account_id))
    cache = MarketCache(provider=chart.provider, account_id=chart.account_id)
    stale = False
    try:
        data = await market.candles(
            chart.provider_instrument, chart.canonical_instrument, chart.timeframe, count=count, before=before)
    except ProviderUnavailableError:
        stale = True
        if chart.history_window_id:
            from nanobot.charts.history import ChartHistory
            series = ChartHistory().get(chart)
        else:
            series = cache.get(chart.provider_instrument, chart.canonical_instrument, chart.timeframe)
        data = cache.page(series, count, before)
        if not data:
            raise ValueError("Market history is unavailable") from None
    if chart.history_window_id:
        from nanobot.charts.history import ChartHistory
        history = ChartHistory()
        series = history.get(chart)
        original_times = {c.time for c in series.candles}
        replacements = {c.time: c for c in data if c.time in original_times}
        if replacements:
            series = history.put(chart, [replacements.get(c.time, c) for c in series.candles])
    else:
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
    with request_context(RequestContext(channel=channel, chat_id=chat_id, session_key=principal, attributes={"chart_user_interaction": True})):
        result = await registry.execute("chart", parsed.model_dump(exclude_none=True))
    if getattr(result, "is_error", False):
        raise ValueError(str(result))
    if not parsed.chart_id:
        if parsed.operation != "create":
            raise ValueError("Client changes require an existing chart id")
        import json
        # The registered executor created this reference, never the client.
        reference = json.loads(str(result).removeprefix("```trading_chart\n").removesuffix("\n```"))
        parsed.chart_id = str(reference["chart_id"])
    if parsed.operation == "report_crosshair":
        return ChartService().get(parsed.chart_id, ChartActor(principal=principal)).model_dump(mode="json")
    return await chart_snapshot(config, parsed.chart_id, principal)


def resolve_approval(principal: str, approval_id: str, approve: bool) -> dict[str, object]:
    record = ActionStore().resolve(approval_id, principal=principal, approve=approve)
    return {"id": record.id, "status": record.status}
