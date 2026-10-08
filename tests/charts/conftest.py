from datetime import datetime, timedelta, timezone

import pytest

from nanobot.charts.controller import ChartController
from nanobot.charts.state import ChartActor, ChartService, CloudChart
from nanobot.market.cache import CandleSeries, MarketCache
from nanobot.market.models import Candle
from nanobot.security.actions import ActionStore
from nanobot.session.records import RecordStore


@pytest.fixture
def workstation(tmp_path):
    journal = ActionStore(tmp_path / "state.db")
    service = ChartService(RecordStore("charts", CloudChart, journal))
    cache = MarketCache(RecordStore("candles", CandleSeries, journal))
    actor = ChartActor(principal="websocket:main")
    chart = service.create(actor, "gold", "XAU_USD", "H1")
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    data = [Candle(canonical_instrument="gold", provider_instrument="XAU_USD", time=start + timedelta(hours=i),
                   open="100", high="110", low="90", close=str(100 + i), complete=True,
                   source="oanda", fetched_at=start) for i in range(100)]
    cache.put("XAU_USD", "gold", "H1", data)
    return service, ChartController(service, cache), actor, chart, data
