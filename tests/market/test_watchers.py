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
    records.create(MarketWatcher(id="watch_1", responsibility_id=parent.id,
                                provider_instrument="XAU_USD", canonical_instrument="gold-usd",
                                condition="cross_above", threshold=Decimal("2700"), interval_ms=1000, next_check_ms=0))
    def quote(value):
        return Quote(canonical_instrument="gold-usd",provider_instrument="XAU_USD",time=datetime.now(timezone.utc),bid=Decimal(value),ask=Decimal(value),source="oanda",fetched_at=datetime.now(timezone.utc))
    client = AsyncMock()
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
