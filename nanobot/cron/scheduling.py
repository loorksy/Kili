"""Pure schedule semantics shared by cron jobs and durable responsibilities."""
from datetime import datetime

from nanobot.cron.types import CronSchedule


def compute_next_run(schedule: CronSchedule, now_ms: int) -> int | None:
    """Compute next run time in ms."""
    if schedule.kind == "at":
        return schedule.at_ms if schedule.at_ms and schedule.at_ms > now_ms else None

    if schedule.kind == "every":
        if not schedule.every_ms or schedule.every_ms <= 0:
            return None
        # Next interval from now
        return now_ms + schedule.every_ms

    if schedule.kind == "cron" and schedule.expr:
        try:
            from zoneinfo import ZoneInfo

            from croniter import croniter
            # Use caller-provided reference time for deterministic scheduling
            base_time = now_ms / 1000
            tz = ZoneInfo(schedule.tz) if schedule.tz else datetime.now().astimezone().tzinfo
            base_dt = datetime.fromtimestamp(base_time, tz=tz)
            cron = croniter(schedule.expr, base_dt)
            next_dt = cron.get_next(datetime)
            return int(next_dt.timestamp() * 1000)
        except Exception:
            return None

    return None


def validate_schedule(schedule: CronSchedule) -> None:
    """Validate schedule fields that would otherwise create non-runnable jobs."""
    if schedule.tz and schedule.kind != "cron":
        raise ValueError("tz can only be used with cron schedules")
    if schedule.kind == "every" and (schedule.every_ms is None or schedule.every_ms <= 0):
        raise ValueError("every schedule requires a positive 'every_ms'")

    if schedule.kind == "cron":
        if not schedule.expr or not schedule.expr.strip():
            raise ValueError("cron schedule requires a non-empty 'expr'")
        try:
            from croniter import croniter

            croniter(schedule.expr)
        except Exception as exc:
            raise ValueError(f"invalid cron expression '{schedule.expr}': {exc}") from None
        if schedule.tz:
            try:
                from zoneinfo import ZoneInfo

                ZoneInfo(schedule.tz)
            except Exception:
                raise ValueError(f"unknown timezone '{schedule.tz}'") from None


