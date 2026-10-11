"""Market watcher lifecycle: pause, stale scope, owner cancel, resume, restart."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
from loguru import logger
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.agent.tools.context import (
    RequestContext,
    ResponsibilityExecution,
    bind_request_context,
    reset_request_context,
)
from nanobot.agent.tools.market_watch import MarketWatchTool
from nanobot.market.models import Quote
from nanobot.market.provider import ProviderUnavailableError
from nanobot.market.watch_control import cancel_owned_watcher
from nanobot.market.watchers import (
    MarketWatcher,
    MarketWatchers,
    lifecycle_log,
    open_watcher_records,
)
from nanobot.security.actions import ActionStore
from nanobot.session.manager import SessionManager
from nanobot.session.records import RecordStore
from nanobot.session.responsibilities import ResponsibilityStore, StaleExecutionError
from nanobot.webui.ws_http import GatewayHTTPHandler


@pytest.fixture(autouse=True)
def _reset_lifecycle_log():
    lifecycle_log.emitted.clear()
    yield
    lifecycle_log.emitted.clear()


def _quote(value: str) -> Quote:
    now = datetime.now(timezone.utc)
    return Quote(
        canonical_instrument="gold-usd", provider_instrument="XAU_USD", time=now,
        bid=Decimal(value), ask=Decimal(value), source="metaapi", account_id="demo", fetched_at=now,
    )


def _watcher(responsibility_id: str, watcher_id: str = "watch_1", **overrides: object) -> MarketWatcher:
    payload: dict[str, object] = {
        "provider": "metaapi", "account_id": "demo", "id": watcher_id,
        "responsibility_id": responsibility_id, "provider_instrument": "XAU_USD",
        "canonical_instrument": "gold-usd", "condition": "above", "threshold": Decimal("2700"),
        "interval_ms": 1000, "next_check_ms": 0,
    }
    payload.update(overrides)
    return MarketWatcher.model_validate(payload)


def _stack(tmp_path):
    responsibilities = ResponsibilityStore(tmp_path)
    parent = responsibilities.create(
        objective="Watch gold", session_key="websocket:main", channel="websocket", chat_id="main",
    )
    records = RecordStore("watchers", MarketWatcher, ActionStore(tmp_path / "state.db"))
    records.create(_watcher(parent.id))
    client = type("Client", (), {})()
    client.connection = type("Connection", (), {"account_id": "demo"})()
    client.quote = None
    return responsibilities, parent, records, client


def _bind_quote(client, values: list[str] | None = None, side_effect=None):
    from unittest.mock import AsyncMock
    client.quote = AsyncMock(side_effect=side_effect or [_quote(value) for value in (values or ["2690"])])
    return client


def _pause(store: ResponsibilityStore, responsibility_id: str):
    record = store.get(responsibility_id)
    record.state = "PAUSED"
    record.next_wake_ms = None
    return store.control_update(record)


def _resume(store: ResponsibilityStore, responsibility_id: str):
    record = store.get(responsibility_id)
    record.state = "SCHEDULED"
    record.recovery_required = False
    record.waiting_for = None
    record.next_wake_ms = 5_000
    return store.control_update(record)


def _warnings() -> tuple[list[str], int]:
    found: list[str] = []
    sink = logger.add(lambda message: found.append(str(message)), level="WARNING")
    return found, sink


async def test_pause_suspends_watcher_and_does_not_poll(tmp_path):
    store, parent, records, client = _stack(tmp_path)
    _bind_quote(client)
    watchers = MarketWatchers(client, store, records)
    _pause(store, parent.id)
    saved = records.get("watch_1")
    assert saved.lifecycle == "SUSPENDED_BY_PARENT"
    assert saved.stop_reason == "parent_paused"
    assert not saved.active
    assert watchers.nearest() is None
    request = RequestContext(channel="websocket", chat_id="main", session_key="websocket:main")
    request.responsibility_scope.closed = True
    token = bind_request_context(request)
    try:
        await watchers.run_due(10_000)
    finally:
        reset_request_context(token)
    client.quote.assert_not_awaited()
    assert not store.get(parent.id).wakes
    assert records.get("watch_1").lifecycle == "SUSPENDED_BY_PARENT"


async def test_closed_scope_during_tick_suspends_once(tmp_path):
    store, parent, records, client = _stack(tmp_path)
    warnings, sink = _warnings()
    try:
        async def quote(*_args, **_kwargs):
            _pause(store, parent.id)
            raise StaleExecutionError("Execution scope is closed")

        _bind_quote(client, side_effect=quote)
        watchers = MarketWatchers(client, store, records)
        await watchers.run_due(100)
        await watchers.run_due(100_000)
    finally:
        logger.remove(sink)
    assert records.get("watch_1").lifecycle == "SUSPENDED_BY_PARENT"
    assert client.quote.await_count == 1
    assert sum("Market watcher" in item for item in warnings) == 1
    assert not any("Traceback" in item for item in warnings)


async def test_owner_cancel_without_live_claim_and_model_path_stays_fenced(tmp_path):
    store, parent, records, client = _stack(tmp_path)
    _bind_quote(client)
    MarketWatchers(client, store, records)
    claim = store.claim_foreground(parent.id)
    tool = MarketWatchTool.__new__(MarketWatchTool)
    tool.records = records
    tool.cron = None
    request = RequestContext(channel="websocket", chat_id="main", session_key="websocket:main")
    request.responsibility_scope.executions[parent.id] = ResponsibilityExecution(store, claim)
    request.responsibility_scope.closed = True
    token = bind_request_context(request)
    try:
        with pytest.raises(StaleExecutionError, match="Execution scope is closed"):
            await tool.execute(operation="cancel", responsibility_id=parent.id, watcher_id="watch_1")
        assert records.get("watch_1").lifecycle == "ACTIVE"
        cancelled = cancel_owned_watcher(
            tmp_path, "websocket:main", "watch_1", records=records, responsibilities=store,
        )
    finally:
        reset_request_context(token)
    assert cancelled["lifecycle"] == "CANCELLED"
    assert cancelled["stop_reason"] == "owner_cancel"
    again = cancel_owned_watcher(
        tmp_path, "websocket:main", "watch_1", records=records, responsibilities=store,
    )
    assert again["lifecycle"] == "CANCELLED"
    with pytest.raises(PermissionError):
        cancel_owned_watcher(
            tmp_path, "websocket:other", "watch_1", records=records, responsibilities=store,
        )
    _pause(store, parent.id)
    _resume(store, parent.id)
    assert records.get("watch_1").lifecycle == "CANCELLED"


async def test_resume_rearms_only_parent_suspended_watchers(tmp_path):
    store, parent, records, client = _stack(tmp_path)
    records.create(_watcher(parent.id, "watch_cancelled"))
    records.create(_watcher(parent.id, "watch_fired"))
    fired = records.get("watch_fired")
    fired.lifecycle = "FIRED"
    fired.active = False
    fired.fired = True
    fired.stop_reason = "condition_met"
    records.save_trusted(fired)
    cancelled = records.get("watch_cancelled")
    cancelled.lifecycle = "CANCELLED"
    cancelled.active = False
    cancelled.stop_reason = "model_cancel"
    records.save_trusted(cancelled)
    _bind_quote(client, ["2690"])
    MarketWatchers(client, store, records)
    _pause(store, parent.id)
    assert records.get("watch_1").lifecycle == "SUSPENDED_BY_PARENT"
    assert records.get("watch_cancelled").lifecycle == "CANCELLED"
    assert records.get("watch_fired").lifecycle == "FIRED"
    _resume(store, parent.id)
    assert records.get("watch_1").lifecycle == "ACTIVE"
    assert records.get("watch_1").next_check_ms >= 0
    assert records.get("watch_cancelled").lifecycle == "CANCELLED"
    assert records.get("watch_fired").fired
    assert records.get("watch_fired").lifecycle == "FIRED"


async def test_manual_cancel_stays_cancelled_across_pause_and_resume(tmp_path):
    store, parent, records, client = _stack(tmp_path)
    MarketWatchers(client, store, records)
    cancel_owned_watcher(tmp_path, "websocket:main", "watch_1", records=records, responsibilities=store)
    _pause(store, parent.id)
    _resume(store, parent.id)
    saved = records.get("watch_1")
    assert saved.lifecycle == "CANCELLED"
    assert saved.stop_reason == "owner_cancel"
    assert not saved.active


async def test_fired_watcher_is_not_rearmed(tmp_path):
    store, parent, records, client = _stack(tmp_path)
    _bind_quote(client, ["2699", "2701", "2800"])
    watchers = MarketWatchers(client, store, records)
    await watchers.run_due(100)
    await watchers.run_due(1_100)
    assert records.get("watch_1").lifecycle == "FIRED"
    assert list(store.get(parent.id).wakes) == ["market:watch_1"]
    _pause(store, parent.id)
    _resume(store, parent.id)
    await watchers.run_due(50_000)
    assert client.quote.await_count == 2
    assert records.get("watch_1").lifecycle == "FIRED"
    assert list(store.get(parent.id).wakes) == ["market:watch_1"]


async def test_terminal_parent_stops_watcher_permanently(tmp_path):
    store, parent, records, client = _stack(tmp_path)
    _bind_quote(client, ["2800"])
    watchers = MarketWatchers(client, store, records)
    record = store.get(parent.id)
    record.state = "COMPLETED"
    store.control_update(record)
    assert records.get("watch_1").lifecycle == "CANCELLED"
    assert records.get("watch_1").stop_reason == "parent_terminal"
    await watchers.run_due(10_000)
    client.quote.assert_not_awaited()
    inspected = store.get(parent.id)
    inspected.state = "SCHEDULED"
    store.control_update(inspected)
    assert records.get("watch_1").lifecycle == "CANCELLED"
    await watchers.run_due(20_000)
    client.quote.assert_not_awaited()


async def test_restart_reconciles_paused_parent(tmp_path):
    store, parent, records, client = _stack(tmp_path)
    _bind_quote(client, ["2800"])
    MarketWatchers(client, store, records)
    store.lifecycle_listeners.clear()
    _pause(store, parent.id)
    assert records.get("watch_1").lifecycle == "ACTIVE"
    restarted = MarketWatchers(client, store, records)
    assert records.get("watch_1").lifecycle == "SUSPENDED_BY_PARENT"
    assert restarted.nearest() is None
    await restarted.run_due(10_000)
    client.quote.assert_not_awaited()


async def test_provider_timeout_keeps_bounded_backoff(tmp_path):
    store, parent, records, client = _stack(tmp_path)
    _bind_quote(client, side_effect=ProviderUnavailableError("MetaApi timeout"))
    watchers = MarketWatchers(client, store, records)
    await watchers.run_due(1_000)
    saved = records.get("watch_1")
    assert saved.lifecycle == "ACTIVE"
    assert saved.failures == 1
    assert saved.next_check_ms == 1_000 + min(3_600_000, 1000 * 2)
    await watchers.run_due(saved.next_check_ms - 1)
    assert client.quote.await_count == 1
    await watchers.run_due(saved.next_check_ms)
    assert records.get("watch_1").failures == 2
    assert client.quote.await_count == 2


async def test_repeated_stale_scope_does_not_flood_or_tight_loop(tmp_path):
    store, parent, records, client = _stack(tmp_path)
    warnings, sink = _warnings()
    calls = {"n": 0}

    async def quote(*_args, **_kwargs):
        calls["n"] += 1
        raise StaleExecutionError("Execution scope is closed")

    try:
        _bind_quote(client, side_effect=quote)
        watchers = MarketWatchers(client, store, records)
        await watchers.run_due(0)
        for _ in range(40):
            await watchers.run_due(0)
        assert calls["n"] == 1
        for step in range(1, 15):
            await watchers.run_due(step * 1000)
    finally:
        logger.remove(sink)
    assert records.get("watch_1").lifecycle == "ACTIVE"
    assert records.get("watch_1").failures == 0
    assert sum("skipped a tick" in item for item in warnings) == 1
    assert not any("Traceback" in item or "Execution scope is closed" in item for item in warnings)


def test_legacy_inactive_watcher_is_not_treated_as_suspended(tmp_path):
    store = ResponsibilityStore(tmp_path)
    parent = store.create(objective="Legacy", session_key="websocket:main", channel="websocket", chat_id="main")
    records = RecordStore("watchers", MarketWatcher, ActionStore(tmp_path / "state.db"))
    legacy = {
        "version": 1, "id": "watch_legacy", "revision": 0, "responsibility_id": parent.id,
        "provider_instrument": "XAU_USD", "canonical_instrument": "gold-usd",
        "condition": "above", "threshold": "100", "next_check_ms": 0,
        "active": False, "fired": False,
    }
    with records.journal.transaction() as db:
        db.execute(
            "INSERT INTO records VALUES (?,?,?,?)",
            ("watchers", "watch_legacy", 0, json.dumps(legacy)),
        )
    loaded = records.get("watch_legacy")
    assert loaded.lifecycle == "CANCELLED"
    assert loaded.stop_reason == "legacy_inactive"
    client = type("Client", (), {})()
    client.connection = type("Connection", (), {"account_id": "demo"})()
    MarketWatchers(client, store, records)
    record = store.get(parent.id)
    record.state = "PAUSED"
    store.control_update(record)
    record = store.get(parent.id)
    record.state = "SCHEDULED"
    record.recovery_required = False
    store.control_update(record)
    assert records.get("watch_legacy").lifecycle == "CANCELLED"


def _internal_root(tmp_path):
    root = tmp_path / "internal"

    def fake(*, create: bool = False):
        root.mkdir(parents=True, exist_ok=True)
        return root

    return fake


async def test_owner_cancel_http_is_authenticated_and_scoped(tmp_path, monkeypatch):
    fake_root = _internal_root(tmp_path)
    monkeypatch.setattr("nanobot.session.responsibilities.internal_state_root", fake_root)
    monkeypatch.setattr("nanobot.security.actions.internal_state_root", fake_root)
    manager = SessionManager(tmp_path / "workspace")
    manager.save(manager.get_or_create("websocket:main"))
    manager.save(manager.get_or_create("websocket:other"))
    parent = manager.responsibilities.create(
        objective="Watch gold", session_key="websocket:main", channel="websocket", chat_id="main",
    )
    records = open_watcher_records(manager.workspace)
    records.create(_watcher(parent.id))
    handler = object.__new__(GatewayHTTPHandler)
    handler.tokens = type("Tokens", (), {"check_api_token": staticmethod(lambda request: request.headers.get("Authorization") == "Bearer fixture")})()
    handler.session_manager = manager
    path = "/api/webui/market-watchers/cancel"
    query = "?session_key=websocket:main&watcher_id=watch_1"
    anonymous = Request(path + query, Headers())
    assert (await handler._handle_cloud_resource(anonymous, path)).status_code == 401
    headers = Headers({"Authorization": "Bearer fixture"})
    missing = Request(path + query, headers)
    assert (await handler._handle_cloud_resource(missing, path)).status_code == 405
    assert records.get("watch_1").lifecycle == "ACTIVE"

    def mutate(session_key: str) -> Request:
        request = Request(path, headers)
        setattr(request, "_nanobot_webui_mutation_request", True)
        setattr(request, "_nanobot_webui_mutation_payload", {
            "session_key": session_key, "watcher_id": "watch_1",
        })
        return request

    other = await handler._handle_cloud_resource(mutate("websocket:other"), path)
    assert other.status_code == 403
    allowed = await handler._handle_cloud_resource(mutate("websocket:main"), path)
    assert allowed.status_code == 200
    assert records.get("watch_1").lifecycle == "CANCELLED"
    assert records.get("watch_1").stop_reason == "owner_cancel"
    revision = records.get("watch_1").revision
    repeated = await handler._handle_cloud_resource(mutate("websocket:main"), path)
    assert repeated.status_code == 200
    assert records.get("watch_1").revision == revision
