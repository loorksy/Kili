"""Connection-owned chart feeds on the existing authenticated WebSocket transport."""
from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field
from websockets.asyncio.server import ServerConnection

from nanobot.charts.state import ChartActor, ChartService
from nanobot.market.broker import BrokerMarket
from nanobot.market.models import Candle, Quote
from nanobot.market.provider import ProviderUnavailableError
from nanobot.market.streaming import PriceStream, StreamUpdate
from nanobot.trading.accounts import TradingAccounts
from nanobot.webui.session_identity import is_webui_session_key

if TYPE_CHECKING:
    from nanobot.webui.gateway_services import GatewayServices


class ChartSubscription(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_key: str
    chart_id: str = Field(pattern=r"^chart_[a-f0-9]{32}$")
    subscription_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")


def candle_end(candle: Candle, timeframe: str) -> datetime:
    """Broker bar start plus its declared duration, never OANDA alignment."""
    match = re.fullmatch(r"([SMH])(\d+)", timeframe)
    if match:
        unit, count = match.groups()
        return candle.time + timedelta(seconds=int(count) * {"S": 1, "M": 60, "H": 3600}[unit])
    local = candle.time
    if timeframe in {"D", "W"}:
        return (local + timedelta(days=1 if timeframe == "D" else 7)).astimezone(candle.time.tzinfo)
    if timeframe == "M":
        month = local.month % 12 + 1
        year = local.year + (local.month == 12)
        return local.replace(year=year, month=month, day=1).astimezone(candle.time.tzinfo)
    raise ValueError("Unsupported candle timeframe")


@dataclass
class _Subscription:
    request: ChartSubscription
    key: str
    symbol: str
    timeframe: str
    account_id: str
    history_count: int = 200
    candle: Candle | None = None
    reconciled_at: float = 0
    retry_history_at: float = 0
    valid: bool = True
    history_task: asyncio.Task[None] | None = None


class ChartStreams:
    def __init__(self, gateway: GatewayServices, send: Callable[..., Awaitable[None]]):
        self.gateway, self.send = gateway, send
        self._feeds: dict[ServerConnection, dict[str, _Subscription]] = {}
        self._streams: dict[str, PriceStream] = {}
        self._retire_tasks: set[asyncio.Task[None]] = set()

    def _authorize(self, subscription: _Subscription) -> None:
        request = subscription.request
        # Authorization needs chart ownership, not the full 5,000-candle cache
        # enrichment performed by a chart snapshot on every tick.
        service = ChartService()
        current = service.records.get(request.chart_id)
        service.require_access(current, ChartActor(principal=request.session_key))
        active_config = self.gateway.settings.config.load().tools.integrations
        stream = self._streams.get(subscription.account_id)
        if (not active_config.charts_enabled or stream is None
                or active_config.broker_accounts().get(subscription.account_id) != stream.client.connection):
            raise PermissionError("Market connection changed")
        sessions = self.gateway.session_manager
        if sessions is None or sessions.get_existing(request.session_key) is None:
            raise PermissionError("Conversation unavailable")
        if (current.provider != "metaapi" or current.account_id != subscription.account_id
                or current.provider_instrument != subscription.symbol or current.timeframe != subscription.timeframe):
            raise PermissionError("Chart binding changed")

    async def change(self, connection: ServerConnection, payload: dict[str, object], *, subscribe: bool) -> dict[str, bool]:
        request = ChartSubscription.model_validate(payload)
        if not subscribe:
            await self.remove(connection, request.subscription_id)
            return {"subscribed": False}
        config = self.gateway.settings.config.load()
        if not config.tools.integrations.charts_enabled:
            raise ValueError("Broker chart streaming is disabled")
        if not is_webui_session_key(request.session_key) or self.gateway.session_manager is None:
            raise PermissionError("Conversation unavailable")
        if self.gateway.session_manager.get_existing(request.session_key) is None:
            raise PermissionError("Conversation unavailable")
        chart = ChartService().get(request.chart_id, ChartActor(principal=request.session_key))
        if chart.provider != "metaapi" or chart.account_id is None:
            raise ValueError("Legacy chart is archived; open a broker-bound chart")
        market = BrokerMarket(TradingAccounts(config.tools.integrations).client(chart.account_id))
        feeds = self._feeds.setdefault(connection, {})
        if request.subscription_id not in feeds and len(feeds) >= 16:
            raise ValueError("Too many open charts on this connection")
        await self.remove(connection, request.subscription_id)
        if chart.account_id not in self._streams:
            self._streams[chart.account_id] = PriceStream(market)
        stream = self._streams[chart.account_id]
        subscription = _Subscription(request, f"{id(connection)}:{request.subscription_id}", chart.provider_instrument,
            chart.timeframe, chart.account_id, history_count=chart.candle_count)
        self._feeds.setdefault(connection, {})[request.subscription_id] = subscription

        async def update(value: StreamUpdate) -> None:
            if not subscription.valid:
                return
            try:
                # Revalidate durable scope/binding for every outgoing update.
                self._authorize(subscription)
                fields: dict[str, object] = {"chart_id": request.chart_id, "session_key": request.session_key,
                    "subscription_id": request.subscription_id, "timeframe": subscription.timeframe}
                if isinstance(value, Quote):
                    fields.update(status="live" if value.tradable else "market_closed", quote=value.model_dump(mode="json"))
                    candle = self._candle(subscription, value)
                    fields["candle"] = candle.model_dump(mode="json") if candle else None
                    fields["provisional"] = True
                else:
                    fields["status"] = value
                await self.send(connection, "cloud_chart_price", **fields)
            except (PermissionError, ValueError):
                # No quotes after deletion, revoked access or changed binding.
                subscription.valid = False
                await self.send(connection, "cloud_chart_price", chart_id=request.chart_id,
                    subscription_id=request.subscription_id, session_key=request.session_key, status="stopped")
                task = asyncio.create_task(self._retire(connection, subscription))
                self._retire_tasks.add(task)
                task.add_done_callback(self._retire_tasks.discard)

        try:
            await stream.add(subscription.key, chart.provider_instrument, chart.canonical_instrument, update)
        except Exception:
            self._feeds[connection].pop(request.subscription_id, None)
            raise
        return {"subscribed": True}

    def _candle(self, subscription: _Subscription, quote: Quote) -> Candle | None:
        now = time.monotonic()
        candle = subscription.candle
        if candle is None or quote.time >= candle_end(candle, subscription.timeframe) or now - subscription.reconciled_at >= 60:
            if now >= subscription.retry_history_at and (subscription.history_task is None or subscription.history_task.done()):
                # A REST read must never delay delivery of the streaming quote.
                subscription.history_task = asyncio.create_task(self._reconcile_candle(subscription, quote))
        if candle is None or candle.complete or not candle.time <= quote.time < candle_end(candle, subscription.timeframe):
            return None
        # Broker bar conventions differ (bid/last and session boundaries).
        # A quote updates the live price independently, not invented OHLC.
        # Return the latest official SDK bar while reconciliation fetches new
        # broker bars; never synthesize broker candles from midpoint quotes.
        return candle

    async def _reconcile_candle(self, subscription: _Subscription, quote: Quote) -> None:
        try:
            client = self._streams[subscription.account_id].client
            if not isinstance(client, BrokerMarket):
                raise ValueError("Broker chart requires broker market data")
            candles = await client.candles(subscription.symbol, quote.canonical_instrument,
                subscription.timeframe, count=subscription.history_count if subscription.reconciled_at == 0 else 2)
            if subscription.valid:
                self._authorize(subscription)
                subscription.candle = candles[-1] if candles else None
                subscription.reconciled_at = time.monotonic()
                subscription.retry_history_at = subscription.reconciled_at + 2
                # Correct completed bars from REST, never from sampled ticks.
                completed = [c.model_dump(mode="json") for c in candles if c.complete]
                if completed:
                    request = subscription.request
                    for connection, feeds in self._feeds.items():
                        if feeds.get(request.subscription_id) is subscription:
                            await self.send(connection, "cloud_chart_price", chart_id=request.chart_id,
                                subscription_id=request.subscription_id, session_key=request.session_key,
                                timeframe=subscription.timeframe, provider_instrument=subscription.symbol,
                                status="live", candles=completed, provisional=False)
                            break
        except (ProviderUnavailableError, ValueError, PermissionError):
            subscription.retry_history_at = time.monotonic() + 5

    async def _retire(self, connection: ServerConnection, subscription: _Subscription) -> None:
        if self._feeds.get(connection, {}).get(subscription.request.subscription_id) is subscription:
            await self.remove(connection, subscription.request.subscription_id)

    async def remove(self, connection: ServerConnection, identifier: str) -> None:
        subscription = self._feeds.get(connection, {}).pop(identifier, None)
        if subscription:
            subscription.valid = False
            if subscription.history_task:
                subscription.history_task.cancel()
                await asyncio.gather(subscription.history_task, return_exceptions=True)
            stream = self._streams.get(subscription.account_id)
            if stream:
                await stream.remove(subscription.key)
        if not self._feeds.get(connection):
            self._feeds.pop(connection, None)

    async def disconnect(self, connection: ServerConnection) -> None:
        for identifier in tuple(self._feeds.get(connection, {})):
            await self.remove(connection, identifier)

    async def close(self) -> None:
        for task in self._retire_tasks:
            task.cancel()
        await asyncio.gather(*self._retire_tasks, return_exceptions=True)
        self._retire_tasks.clear()
        history = [s.history_task for feeds in self._feeds.values() for s in feeds.values() if s.history_task]
        for task in history:
            task.cancel()
        await asyncio.gather(*history, return_exceptions=True)
        for stream in self._streams.values():
            await stream.close()
        self._feeds.clear()
        self._streams.clear()
