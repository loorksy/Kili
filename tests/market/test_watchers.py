from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock

from nanobot.market.models import Quote
from nanobot.market.watchers import MarketWatcher, MarketWatchers
from nanobot.security.actions import ActionStore
from nanobot.session.records import RecordStore
from nanobot.session.responsibilities import ResponsibilityStore


async def test_cheap_crossing_persists_one_wake(tmp_path):
    responsibilities = ResponsibilityStore(tmp_path)
    parent = responsibilities.create(objective="Gold crossing", session_key=None, channel="", chat_id="")
    records = RecordStore("watchers", MarketWatcher, ActionStore(tmp_path / "state.db"))
    records.create(MarketWatcher(provider="metaapi", account_id="demo", id="watch_1", responsibility_id=parent.id,
                                provider_instrument="XAU_USD", canonical_instrument="gold-usd",
                                condition="cross_above", threshold=Decimal("2700"), interval_ms=1000, next_check_ms=0))
    def quote(value):
        return Quote(canonical_instrument="gold-usd",provider_instrument="XAU_USD",time=datetime.now(timezone.utc),bid=Decimal(value),ask=Decimal(value),source="metaapi", account_id="demo",fetched_at=datetime.now(timezone.utc))
    client = AsyncMock()
    client.connection.account_id = "demo"
    client.quote.side_effect = [quote("2699"),quote("2701")]
    watchers = MarketWatchers(client, responsibilities, records)
    await watchers.run_due(100)
    assert not responsibilities.get(parent.id).wakes
    await watchers.run_due(1100)
    assert list(responsibilities.get(parent.id).wakes) == ["market:watch_1"]
    await watchers.run_due(2100)
    assert client.quote.await_count == 2 and watchers.nearest() is None
    restarted = RecordStore("watchers", MarketWatcher, ActionStore(tmp_path / "state.db"))
    assert restarted.get("watch_1").fired


async def test_completed_candle_wakes_once_after_restart_and_coalesces_downtime(tmp_path):
    from nanobot.market.models import Candle
    responsibilities = ResponsibilityStore(tmp_path)
    parent = responsibilities.create(objective="New gold candle", session_key=None, channel="", chat_id="")
    records = RecordStore("watchers", MarketWatcher, ActionStore(tmp_path / "state.db"))
    records.create(MarketWatcher(provider="metaapi", account_id="demo", id="watch_candle", responsibility_id=parent.id,
        provider_instrument="XAU_USD", canonical_instrument="gold-usd", condition="new_completed_candle",
        timeframe="H1", interval_ms=1000, next_check_ms=0))
    def candle(time):
        return Candle(canonical_instrument="gold-usd", provider_instrument="XAU_USD", time=time,
                      open="2700", high="2701", low="2699", close="2700", complete=True, source="metaapi", account_id="demo",
                      fetched_at=datetime.now(timezone.utc))
    client = AsyncMock()
    client.connection.account_id = "demo"
    client.candles.side_effect = [[candle("2026-10-07T10:00:00Z")], [candle("2026-10-07T14:00:00Z")]]
    await MarketWatchers(client, responsibilities, records).run_due(100)
    assert not responsibilities.get(parent.id).wakes
    await MarketWatchers(client, responsibilities, records).run_due(10000)
    await MarketWatchers(client, responsibilities, records).run_due(20000)
    assert list(responsibilities.get(parent.id).wakes) == ["market:watch_candle"]
    assert client.candles.await_count == 2 and client.quote.await_count == 0


async def test_retired_watcher_preserves_responsibility_and_different_account_does_not_observe(tmp_path):
    responsibilities = ResponsibilityStore(tmp_path)
    parent = responsibilities.create(objective="Legacy monitor", session_key=None, channel="", chat_id="")
    records = RecordStore("watchers", MarketWatcher, ActionStore(tmp_path / "state.db"))
    records.create(MarketWatcher(id="old", responsibility_id=parent.id, provider_instrument="GOLD",
        canonical_instrument="gold", condition="above", threshold="100", next_check_ms=0))
    records.create(MarketWatcher(id="other", provider="metaapi", account_id="other-account",
        responsibility_id=parent.id, provider_instrument="GOLD", canonical_instrument="gold",
        condition="above", threshold="100", next_check_ms=0))
    client = AsyncMock()
    client.connection.account_id = "current-account"
    watchers = MarketWatchers(client, responsibilities, records)
    await watchers.run_due(100)
    assert not records.get("old").active and records.get("old").needs_account_binding
    assert records.get("other").active
    assert not responsibilities.get(parent.id).wakes
    assert responsibilities.get(parent.id).state != "CANCELLED"
    client.quote.assert_not_awaited()
