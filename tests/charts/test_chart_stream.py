import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest
from websockets.asyncio.server import ServerConnection

from nanobot.bus.queue import MessageBus
from nanobot.channels.websocket.runtime import WebSocketChannel, WebSocketConfig
from nanobot.market.broker import BrokerMarket
from nanobot.market.models import Candle, Connection, Quote
from nanobot.session.manager import SessionManager
from nanobot.webui.chart_stream import ChartStreams, candle_end
from nanobot.webui.gateway_services import build_gateway_services


def gateway(tmp_path, actor):
    sessions = SessionManager(tmp_path / "workspace")
    sessions.save(sessions.get_or_create(actor.principal))
    services = build_gateway_services(config=WebSocketConfig(enabled=True), bus=MessageBus(),
        session_manager=sessions, static_dist_path=None, workspace_path=sessions.workspace,
        default_restrict_to_workspace=True, config_path=tmp_path / "config.json",
        runtime_model_name=None, runtime_surface="browser", runtime_capabilities_overrides=None)

    def configure(config):
        config.tools.integrations.charts_enabled = True
        config.tools.integrations.metaapi = Connection(secret_ref="fixture", account_id="practice")

    services.settings.config.update(configure)
    return services


async def test_live_quote_is_immediate_despite_slow_rest_and_scope_rechecked(workstation, tmp_path, monkeypatch):
    charts, _, actor, chart, data = workstation
    services = gateway(tmp_path, actor)
    monkeypatch.setattr("nanobot.webui.chart_stream.ChartService", lambda: charts)
    incoming = asyncio.Queue()
    rest_release = asyncio.Event()
    events = asyncio.Queue()
    calls = []

    async def prices(client, instruments):
        calls.append(instruments)
        while True:
            yield await incoming.get()

    async def candles(client, *args, **kwargs):
        await rest_release.wait()
        return [data[-1].model_copy(update={"complete": False})]

    async def send(connection, event, **fields):
        await events.put(fields)

    monkeypatch.setattr(BrokerMarket, "stream_prices", prices)
    monkeypatch.setattr(BrokerMarket, "candles", candles)
    streams = ChartStreams(services, send)
    connection = AsyncMock(spec=ServerConnection)
    payload = {"chart_id": chart.id, "session_key": actor.principal, "subscription_id": "open-chart"}
    try:
        await streams.change(connection, payload, subscribe=True)
        now = data[-1].time + timedelta(minutes=1)
        quote = Quote(canonical_instrument="gold", provider_instrument="XAU_USD", time=now,
            fetched_at=now, bid="200", ask="202", source="metaapi", account_id="practice")
        await incoming.put(quote)
        while True:
            first = await asyncio.wait_for(events.get(), 1)
            if first["status"] == "live":
                break
        assert first["quote"]["bid"] == "200" and first["candle"] is None
        assert not rest_release.is_set()  # REST cannot hold streaming prices hostage.
        rest_release.set()
        subscription = streams._feeds[connection]["open-chart"]
        await asyncio.wait_for(subscription.history_task, 1)
        later = quote.model_copy(update={"time": now + timedelta(seconds=1)})
        await incoming.put(later)
        second = await asyncio.wait_for(events.get(), 1)
        assert second["candle"]["close"] == str(data[-1].close) and second["provisional"]
        assert not second["candle"]["complete"]  # Never fabricate midpoint OHLC.
        assert chart.revision == charts.get(chart.id, actor).revision
        changed = charts.get(chart.id, actor)
        changed.timeframe = "H4"
        charts.update(changed, actor, changed.revision)
        await incoming.put(later.model_copy(update={"time": now + timedelta(seconds=2)}))
        assert (await asyncio.wait_for(events.get(), 1))["status"] == "stopped"
        await asyncio.gather(*streams._retire_tasks)
        assert connection not in streams._feeds
        assert streams._streams["practice"]._task is None
    finally:
        await streams.close()


async def test_chart_scope_and_existing_conversation_required(workstation, tmp_path, monkeypatch):
    charts, _, actor, chart, _ = workstation
    services = gateway(tmp_path, actor)
    monkeypatch.setattr("nanobot.webui.chart_stream.ChartService", lambda: charts)
    streams = ChartStreams(services, AsyncMock())
    connection = AsyncMock(spec=ServerConnection)
    payload = {"chart_id": chart.id, "session_key": "websocket:other", "subscription_id": "x"}
    with pytest.raises(PermissionError):
        await streams.change(connection, payload, subscribe=True)
    services.session_manager.save(services.session_manager.get_or_create("websocket:other"))
    with pytest.raises(PermissionError):
        await streams.change(connection, payload, subscribe=True)
    assert streams._streams == {}
    await streams.close()


async def test_subscription_requires_authenticated_webui_socket_not_generic_client(workstation, tmp_path):
    _, _, actor, chart, _ = workstation
    services = gateway(tmp_path, actor)
    channel = WebSocketChannel(WebSocketConfig(enabled=True), services.http.bus, gateway=services)
    socket = AsyncMock(spec=ServerConnection)
    channel._commands.send_webui_response = AsyncMock()
    channel._commands._chart_streams.change = AsyncMock(return_value={"subscribed": True})
    envelope = {"type": "webui_request", "request_id": "stream1", "action": "chart.price_subscribe",
        "payload": {"session_key": actor.principal, "chart_id": chart.id, "subscription_id": "x"}}
    await channel._commands.start_webui_request(socket, envelope)
    channel._commands._chart_streams.change.assert_not_awaited()
    assert channel._commands.send_webui_response.call_args.kwargs["status"] == 403
    channel._webui_connections.add(socket)
    await channel._commands.start_webui_request(socket, envelope)
    channel._commands._chart_streams.change.assert_awaited_once()
    assert not channel._commands.request_operations  # No cross-socket replay cache.
    await channel._commands.close()


@pytest.mark.parametrize("timeframe, expected", [("M1", 60), ("H4", 14400), ("D", 86400), ("W", 604800)])
def test_candle_boundaries_do_not_apply_oanda_new_york_alignment(timeframe, expected):
    # Saturday before the New York spring transition at 17:00 local.
    start = datetime(2026, 3, 7, 22, tzinfo=timezone.utc)
    candle = Candle(canonical_instrument="gold", provider_instrument="XAU_USD", time=start,
        open=1, high=1, low=1, close=1, complete=False, fetched_at=start, source="metaapi", account_id="practice")
    assert (candle_end(candle, timeframe) - start).total_seconds() == expected
