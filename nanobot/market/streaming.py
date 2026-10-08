"""One bounded provider stream for active consumers; no inference or durable ticks."""
from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from nanobot.market.models import Quote
from nanobot.market.oanda import OandaClient, ProviderUnavailableError

StreamStatus = Literal["connecting", "live", "reconnecting", "stopped"]
StreamUpdate = Quote | StreamStatus
StreamConsumer = Callable[[StreamUpdate], Awaitable[None]]


@dataclass
class _Consumer:
    symbol: str
    canonical: str
    callback: StreamConsumer
    queue: asyncio.Queue[StreamUpdate]
    worker: asyncio.Task[None]


class PriceStream:
    """Share one account stream and coalesce slow consumers to their newest tick."""

    def __init__(self, client: OandaClient):
        self.client = client
        self._consumers: dict[str, _Consumer] = {}
        self._task: asyncio.Task[None] | None = None
        self._last: dict[str, Quote] = {}
        self._lock = asyncio.Lock()

    def _symbols(self) -> dict[str, str]:
        return {c.symbol: c.canonical for c in self._consumers.values()}

    @staticmethod
    def _offer(consumer: _Consumer, update: StreamUpdate) -> None:
        if consumer.queue.full():
            consumer.queue.get_nowait()
        consumer.queue.put_nowait(update)

    async def _consume(self, queue: asyncio.Queue[StreamUpdate], callback: StreamConsumer) -> None:
        while True:
            await callback(await queue.get())

    async def add(self, key: str, symbol: str, canonical: str, callback: StreamConsumer) -> None:
        async with self._lock:
            await self._add(key, symbol, canonical, callback)

    async def _add(self, key: str, symbol: str, canonical: str, callback: StreamConsumer) -> None:
        self.client.validate_symbol(symbol)
        before = self._symbols()
        if key in self._consumers:
            await self._remove(key)
            before = self._symbols()
        if len(self._consumers) >= 256 or (symbol not in before and len(before) >= 100):
            raise ValueError("Active price subscriptions exceed bounded limits")
        queue: asyncio.Queue[StreamUpdate] = asyncio.Queue(maxsize=1)
        consumer = _Consumer(symbol, canonical, callback, queue, asyncio.create_task(self._consume(queue, callback)))
        self._consumers[key] = consumer
        self._offer(consumer, "connecting")
        if symbol in self._last:
            self._offer(consumer, self._last[symbol].model_copy(update={"canonical_instrument": canonical}))
        if before.keys() != self._symbols().keys() or self._task is None:
            await self._restart()

    async def remove(self, key: str) -> None:
        async with self._lock:
            await self._remove(key)

    async def _remove(self, key: str) -> None:
        before = self._symbols()
        consumer = self._consumers.pop(key, None)
        if consumer:
            consumer.worker.cancel()
            await asyncio.gather(consumer.worker, return_exceptions=True)
        if before.keys() != self._symbols().keys():
            self._last = {symbol: quote for symbol, quote in self._last.items() if symbol in self._symbols()}
            await self._restart()

    async def _restart(self) -> None:
        if self._task:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
            self._task = None
        if self._consumers:
            self._task = asyncio.create_task(self._run())

    async def _run(self) -> None:
        delay = 1.0
        while self._consumers:
            for consumer in self._consumers.values():
                self._offer(consumer, "connecting" if delay == 1 else "reconnecting")
            try:
                async for quote in self.client.stream_prices(self._symbols()):
                    previous = self._last.get(quote.provider_instrument)
                    if previous is not None and quote.time <= previous.time:
                        continue
                    self._last[quote.provider_instrument] = quote
                    delay = 1.0
                    for consumer in self._consumers.values():
                        if consumer.symbol == quote.provider_instrument:
                            self._offer(consumer, quote.model_copy(update={"canonical_instrument": consumer.canonical}))
            except (ProviderUnavailableError, ValueError, OSError):
                # Never expose HTTP objects, provider bodies or credentials.
                for consumer in self._consumers.values():
                    self._offer(consumer, "reconnecting")
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def close(self) -> None:
        async with self._lock:
            await self._close()

    async def _close(self) -> None:
        consumers, self._consumers = self._consumers, {}
        for consumer in consumers.values():
            consumer.worker.cancel()
        if self._task:
            self._task.cancel()
        tasks = [c.worker for c in consumers.values()]
        if self._task:
            tasks.append(self._task)
        await asyncio.gather(*tasks, return_exceptions=True)
        self._task = None
        self._last.clear()
