from datetime import datetime, timezone

import pytest

from nanobot.market.cache import CandleSeries, MarketCache
from nanobot.market.models import Candle
from nanobot.security.actions import ActionStore
from nanobot.session.records import RecordStore


def test_normalized_evidence_survives_restart_and_revision_ignores_fetch_time(tmp_path):
    def cache():
        return MarketCache(RecordStore("candles", CandleSeries, ActionStore(tmp_path / "state.db")))
    candle = Candle(canonical_instrument="gold", provider_instrument="XAU_USD", time="2026-10-07T10:00:00Z",
                    open="2700.01", high="2701", low="2699", close="2700.5", volume=20,
                    complete=True, source="oanda", fetched_at=datetime.now(timezone.utc))
    first = cache().put("XAU_USD", "gold", "H1", [candle])
    second = cache().put("XAU_USD", "gold", "H1", [candle.model_copy(update={"fetched_at": datetime.now(timezone.utc)})])
    assert first.data_revision == second.data_revision
    assert cache().get("XAU_USD", "gold", "H1").candles[0].open == candle.open
    assert cache().page(second, 1, "2026-10-07T10:00:00Z") == []
    with pytest.raises(ValueError, match="timezone"):
        cache().page(second, 1, "2026-10-07T12:00:00")
    with pytest.raises(ValueError, match="timezone"):
        Candle.model_validate({**candle.model_dump(), "time": datetime(2026, 10, 7)})
