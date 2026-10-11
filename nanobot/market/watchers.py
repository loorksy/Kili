"""Cheap deterministic observation; only a satisfied logical condition wakes the agent.

Responsibility records and watcher records live in different stores, so a pause
cannot commit both atomically. The responsibility write notifies this scheduler,
and every due pass reconciles again. A paused or finished parent therefore cannot
keep a runnable watcher across a crash or a restart.

``ACTIVE`` watchers are the only ones ``nearest`` schedules. ``SUSPENDED_BY_PARENT``
can be re-armed when that parent can accept wakeups again. ``CANCELLED`` and
``FIRED`` never become runnable because a parent was inspected or resumed.
"""
from __future__ import annotations

import hashlib
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal, cast
from weakref import WeakKeyDictionary

from loguru import logger
from pydantic import Field, model_validator

from nanobot.agent.tools.context import isolated_from_request_context
from nanobot.market.broker import BrokerMarket
from nanobot.market.models import Quote
from nanobot.market.provider import TIMEFRAMES, ProviderUnavailableError
from nanobot.session.records import RecordStore, RuntimeRecord
from nanobot.session.responsibilities import (
    TERMINAL_STATES,
    Responsibility,
    ResponsibilityStore,
    StaleExecutionError,
)
from nanobot.trading.metaapi import MetaApiClient

WatcherLifecycle = Literal["ACTIVE", "SUSPENDED_BY_PARENT", "CANCELLED", "FIRED"]
_BOUND_WATCHERS: WeakKeyDictionary[ResponsibilityStore, set[int]] = WeakKeyDictionary()


class LifecycleLog:
    """One warning per watcher and category, then a quiet interval.

    Logging is not the lifecycle fix. Transitions are persisted before this
    runs; a repeated stale scope must not print a stack trace on every tick.
    """

    def __init__(self, interval_s: float = 60.0) -> None:
        self.interval_s = interval_s
        self.emitted: dict[tuple[str, str], float] = {}

    def warning(self, watcher_id: str, category: str, message: str) -> bool:
        now = time.monotonic()
        key = (watcher_id, category)
        previous = self.emitted.get(key)
        if previous is not None and now - previous < self.interval_s:
            return False
        self.emitted[key] = now
        logger.warning("{}", message)
        return True


lifecycle_log = LifecycleLog()


class MarketWatcher(RuntimeRecord):
    provider: Literal["oanda", "metaapi"] = "oanda"  # Archived legacy evidence only.
    account_id: str | None = None
    responsibility_id: str
    provider_instrument: str
    canonical_instrument: str
    condition: Literal["above", "below", "cross_above", "cross_below", "new_completed_candle"]
    threshold: Decimal | None = None
    timeframe: str = "H1"
    last_completed_time: datetime | None = None
    interval_ms: int = Field(default=60_000, ge=1000)
    next_check_ms: int
    last_price: Decimal | None = None
    active: bool = True
    fired: bool = False
    observation: Quote | None = None
    failures: int = 0
    needs_account_binding: bool = False
    lifecycle: WatcherLifecycle = "ACTIVE"
    stop_reason: str = Field(default="", max_length=80)

    @model_validator(mode="before")
    @classmethod
    def legacy_lifecycle(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data
        payload = cast(dict[str, object], data)
        if "lifecycle" in payload:
            return payload
        if payload.get("fired"):
            payload["lifecycle"] = "FIRED"
            payload.setdefault("stop_reason", "condition_met")
        elif payload.get("needs_account_binding") or payload.get("active") is False:
            payload["lifecycle"] = "CANCELLED"
            payload.setdefault(
                "stop_reason",
                "account_binding" if payload.get("needs_account_binding") else "legacy_inactive",
            )
        else:
            payload["lifecycle"] = "ACTIVE"
        return payload

    @model_validator(mode="after")
    def check_condition(self) -> MarketWatcher:
        MetaApiClient.validate_symbol(self.provider_instrument)
        if self.condition != "new_completed_candle" and self.threshold is None:
            raise ValueError("Price conditions require a threshold")
        if self.timeframe not in TIMEFRAMES:
            raise ValueError("Unsupported watcher timeframe")
        if self.lifecycle == "ACTIVE":
            self.active, self.fired = True, False
        elif self.lifecycle == "FIRED":
            self.active, self.fired = False, True
        else:
            self.active, self.fired = False, False
        return self


def watcher_namespace(workspace: Path | str) -> str:
    """Same namespace the gateway and the model tool already share.

    The input is hashed as given. Callers pass the workspace path they already
    persist; resolving it again would orphan existing watcher rows.
    """
    return "market_watchers:" + hashlib.sha256(str(workspace).encode()).hexdigest()


def open_watcher_records(workspace: Path | str) -> RecordStore[MarketWatcher]:
    return RecordStore(watcher_namespace(workspace), MarketWatcher)


def watcher_public(watcher: MarketWatcher) -> dict[str, object]:
    return {
        "id": watcher.id,
        "responsibility_id": watcher.responsibility_id,
        "lifecycle": watcher.lifecycle,
        "active": watcher.active,
        "fired": watcher.fired,
        "stop_reason": watcher.stop_reason,
        "account_id": watcher.account_id,
        "provider_instrument": watcher.provider_instrument,
        "canonical_instrument": watcher.canonical_instrument,
        "condition": watcher.condition,
        "next_check_ms": watcher.next_check_ms,
        "needs_account_binding": watcher.needs_account_binding,
    }


class MarketWatchers:
    def __init__(self, client: BrokerMarket, responsibilities: ResponsibilityStore,
                 records: RecordStore[MarketWatcher] | None = None):
        self.client, self.responsibilities = client, responsibilities
        self.records = records or RecordStore("market_watchers", MarketWatcher)
        self._bind_parent_listener()
        self.reconcile()

    def _bind_parent_listener(self) -> None:
        markers = _BOUND_WATCHERS.setdefault(self.responsibilities, set())
        marker = id(self.records)
        if marker in markers:
            return
        markers.add(marker)
        self.responsibilities.lifecycle_listeners.append(self._on_parent)

    def _on_parent(self, responsibility: Responsibility) -> None:
        now = time.time_ns() // 1_000_000
        for watcher in self.records.list():
            if watcher.responsibility_id != responsibility.id:
                continue
            if self._sync(watcher, responsibility, now):
                self._persist(watcher)

    def reconcile(self, now_ms: int | None = None) -> None:
        """Idempotent alignment of watcher rows with parent responsibility state."""
        now = now_ms if now_ms is not None else time.time_ns() // 1_000_000
        parents = {item.id: item for item in self.responsibilities.list()}
        for watcher in self.records.list():
            parent = parents.get(watcher.responsibility_id)
            if parent is None:
                if watcher.lifecycle == "ACTIVE":
                    self._cancel(watcher, "parent_missing")
                    self._persist(watcher)
                continue
            if self._sync(watcher, parent, now):
                self._persist(watcher)

    def nearest(self) -> int | None:
        self.reconcile()
        account_id = self.client.connection.account_id
        due = [
            watcher.next_check_ms for watcher in self.records.list()
            if self._runnable_here(watcher, account_id)
        ]
        return min(due) if due else None

    async def run_due(self, now_ms: int | None = None) -> None:
        now = now_ms if now_ms is not None else time.time_ns() // 1_000_000
        with isolated_from_request_context():
            self.reconcile(now)
            quotes: dict[str, Quote] = {}
            account_id = self.client.connection.account_id
            for watcher in self.records.list():
                if not self._runnable_here(watcher, account_id) or watcher.next_check_ms > now:
                    continue
                try:
                    await self._tick(watcher, now, quotes)
                except StaleExecutionError:
                    self._settle_stale(watcher.id, now)

    def _runnable_here(self, watcher: MarketWatcher, account_id: str) -> bool:
        return (watcher.lifecycle == "ACTIVE" and watcher.active and not watcher.needs_account_binding
                and watcher.provider == "metaapi" and watcher.account_id == account_id)

    def _sync(self, watcher: MarketWatcher, parent: Responsibility, now: int) -> bool:
        if watcher.provider != "metaapi" or not watcher.account_id:
            if watcher.lifecycle in {"CANCELLED", "FIRED"} and not watcher.active:
                return False
            watcher.needs_account_binding = True
            self._cancel(watcher, "account_binding")
            return True
        if watcher.lifecycle in {"CANCELLED", "FIRED"}:
            changed = watcher.active or (watcher.lifecycle == "FIRED" and not watcher.fired)
            watcher.active = False
            watcher.fired = watcher.lifecycle == "FIRED"
            return changed
        # WAITING_FOR_USER can still accept a queued market wake once the user
        # returns. PAUSED and interrupted recovery cannot.
        if parent.state in TERMINAL_STATES:
            self._cancel(watcher, "parent_terminal")
            return True
        if parent.state == "PAUSED" or parent.recovery_required:
            if watcher.lifecycle == "SUSPENDED_BY_PARENT":
                return False
            reason = "parent_paused" if parent.state == "PAUSED" else "parent_recovery"
            self._suspend(watcher, reason)
            return True
        if watcher.lifecycle == "SUSPENDED_BY_PARENT":
            self._rearm(watcher, parent, now)
            return True
        return False

    def _cancel(self, watcher: MarketWatcher, reason: str) -> None:
        watcher.lifecycle = "CANCELLED"
        watcher.active = False
        watcher.fired = False
        watcher.stop_reason = reason
        lifecycle_log.warning(
            watcher.id, f"CANCELLED:{reason}",
            f"Market watcher {watcher.id} cancelled ({reason})",
        )

    def _suspend(self, watcher: MarketWatcher, reason: str) -> None:
        watcher.lifecycle = "SUSPENDED_BY_PARENT"
        watcher.active = False
        watcher.fired = False
        watcher.stop_reason = reason
        lifecycle_log.warning(
            watcher.id, f"SUSPENDED_BY_PARENT:{reason}",
            f"Market watcher {watcher.id} suspended ({reason})",
        )

    def _rearm(self, watcher: MarketWatcher, parent: Responsibility, now: int) -> None:
        watcher.lifecycle = "ACTIVE"
        watcher.active = True
        watcher.fired = False
        watcher.stop_reason = ""
        # One fresh observation. Missed intervals are not replayed.
        if watcher.next_check_ms < now:
            watcher.next_check_ms = now
        logger.info("Re-armed market watcher {} for responsibility {}", watcher.id, parent.id)

    def _persist(self, watcher: MarketWatcher) -> MarketWatcher:
        try:
            return self.records.save_trusted(watcher)
        except ValueError:
            fresh = self.records.get(watcher.id)
            if fresh.lifecycle != "ACTIVE":
                return fresh
            watcher.revision = fresh.revision
            return self.records.save_trusted(watcher)

    def _settle_stale(self, watcher_id: str, now: int) -> None:
        try:
            watcher = self.records.get(watcher_id)
            parent = self.responsibilities.get(watcher.responsibility_id)
        except (OSError, ValueError):
            lifecycle_log.warning(
                watcher_id, "stale_execution",
                f"Market watcher {watcher_id} stopped after a closed execution scope",
            )
            return
        if self._sync(watcher, parent, now):
            self._persist(watcher)
            return
        if watcher.lifecycle != "ACTIVE":
            return
        watcher.next_check_ms = now + watcher.interval_ms
        self._persist(watcher)
        lifecycle_log.warning(
            watcher.id, "stale_execution",
            f"Market watcher {watcher.id} skipped a tick because its execution scope closed",
        )

    async def _tick(self, watcher: MarketWatcher, now: int, quotes: dict[str, Quote]) -> None:
        parent = self.responsibilities.get(watcher.responsibility_id)
        if self._sync(watcher, parent, now):
            self._persist(watcher)
            return
        if watcher.condition == "new_completed_candle":
            await self._tick_candle(watcher, now)
            return
        await self._tick_price(watcher, now, quotes)

    async def _tick_candle(self, watcher: MarketWatcher, now: int) -> None:
        try:
            candles = await self.client.candles(
                watcher.provider_instrument, watcher.canonical_instrument, watcher.timeframe, count=2,
            )
        except ProviderUnavailableError:
            self._backoff(watcher, now)
            self._persist(watcher)
            return
        except StaleExecutionError:
            self._settle_stale(watcher.id, now)
            return
        current = self._fresh_active(watcher, now)
        if current is None:
            return
        latest = max((candle.time for candle in candles if candle.complete), default=None)
        if latest is not None:
            if current.last_completed_time is not None and latest > current.last_completed_time:
                if not self._wake(current, (
                    f"New completed {current.timeframe} candle on {current.provider_instrument} "
                    f"at {latest.isoformat()}."
                ), now):
                    return
                current.lifecycle = "FIRED"
                current.active = False
                current.fired = True
                current.stop_reason = "condition_met"
                lifecycle_log.warning(current.id, "FIRED", f"Market watcher {current.id} fired")
            current.last_completed_time = latest
        current.failures = 0
        if current.lifecycle == "ACTIVE":
            current.next_check_ms = now + current.interval_ms
        self._persist(current)

    async def _tick_price(self, watcher: MarketWatcher, now: int, quotes: dict[str, Quote]) -> None:
        assert watcher.threshold is not None
        try:
            quote = quotes.get(watcher.provider_instrument)
            if quote is None:
                quote = await self.client.quote(watcher.provider_instrument, watcher.canonical_instrument)
                quotes[watcher.provider_instrument] = quote
        except ProviderUnavailableError:
            self._backoff(watcher, now)
            self._persist(watcher)
            return
        except StaleExecutionError:
            self._settle_stale(watcher.id, now)
            return
        current = self._fresh_active(watcher, now)
        if current is None or current.threshold is None:
            return
        price, previous = quote.bid, current.last_price
        hit = ((current.condition == "above" and price >= current.threshold)
               or (current.condition == "below" and price <= current.threshold)
               or (current.condition == "cross_above" and previous is not None
                   and previous < current.threshold <= price)
               or (current.condition == "cross_below" and previous is not None
                   and previous > current.threshold >= price))
        current.last_price, current.observation, current.failures = price, quote, 0
        current.next_check_ms = now + current.interval_ms
        if hit:
            if not self._wake(current, (
                f"Market condition {current.condition} {current.threshold} satisfied on "
                f"{current.provider_instrument}; observed {price}, broker account {current.account_id} "
                f"at {quote.time.isoformat()}."
            ), now):
                return
            current.lifecycle = "FIRED"
            current.active = False
            current.fired = True
            current.stop_reason = "condition_met"
            lifecycle_log.warning(current.id, "FIRED", f"Market watcher {current.id} fired")
        self._persist(current)

    def _fresh_active(self, watcher: MarketWatcher, now: int) -> MarketWatcher | None:
        current = self.records.get(watcher.id)
        if current.lifecycle != "ACTIVE":
            return None
        parent = self.responsibilities.get(current.responsibility_id)
        if self._sync(current, parent, now):
            self._persist(current)
            return None
        return current

    def _wake(self, watcher: MarketWatcher, content: str, now: int) -> bool:
        parent = self.responsibilities.get(watcher.responsibility_id)
        if self._sync(watcher, parent, now):
            self._persist(watcher)
            return False
        # Persist the wake FIRST. A crash before watcher save repeats the same key.
        self.responsibilities.enqueue(watcher.responsibility_id, f"market:{watcher.id}", content)
        return True

    @staticmethod
    def _backoff(watcher: MarketWatcher, now: int) -> None:
        watcher.failures += 1
        watcher.next_check_ms = now + min(3_600_000, watcher.interval_ms * 2 ** min(watcher.failures, 6))
