import asyncio

from nanobot.cron.service import CronService
from nanobot.session.wake_schedule import WakeSchedule


def test_exact_relative_recurrence_and_calendar():
    assert WakeSchedule(kind="at", at_ms=20000).first(100) == 20000
    assert WakeSchedule(kind="after",delay_ms=7200000).first(100) == 7200100
    recurrence = WakeSchedule(kind="every",every_ms=900000)
    assert recurrence.first(100) == 900100
    assert recurrence.next_after(4500100) == 5400100
    calendar = WakeSchedule(kind="cron",expr="0 20 * * *",tz="UTC")
    import datetime
    now = int(datetime.datetime(2026,10,7,19,tzinfo=datetime.timezone.utc).timestamp()*1000)
    assert calendar.first(now) == now + 3600000


async def test_native_timer_uses_deadline_not_safety_sweep(tmp_path):
    import time
    cron = CronService(tmp_path / "cron.json")
    due = time.time_ns() // 1000000 + 30
    calls = []
    async def run():
        nonlocal due
        calls.append("work")
        due = None
    cron.register_deadline_source("responsibility", lambda: due, run)
    await cron.start()
    await asyncio.sleep(.08)
    assert calls == ["work"]
    cron.stop()
