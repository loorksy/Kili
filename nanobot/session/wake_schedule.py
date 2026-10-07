"""Durable user timing, resolved independently of recovery sweep cadence."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nanobot.cron.scheduling import compute_next_run, validate_schedule
from nanobot.cron.types import CronSchedule


class WakeSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    kind: Literal["at", "after", "every", "cron"]
    at_ms: int | None = None
    delay_ms: int | None = Field(default=None, gt=0)
    every_ms: int | None = Field(default=None, gt=0)
    expr: str | None = None
    tz: str | None = None
    anchor_ms: int | None = None

    @model_validator(mode="after")
    def check_schedule(self) -> WakeSchedule:
        if self.kind == "at" and self.at_ms is None:
            raise ValueError("Exact schedules require at_ms")
        if self.kind == "after" and self.delay_ms is None:
            raise ValueError("Relative schedules require delay_ms")
        if self.kind == "every" and self.every_ms is None:
            raise ValueError("Recurrence requires every_ms")
        if self.kind == "cron":
            validate_schedule(CronSchedule(kind="cron", expr=self.expr, tz=self.tz))
        elif self.tz is not None:
            raise ValueError("Timezone is only meaningful for calendar schedules")
        return self

    def first(self, now_ms: int) -> int:
        self.anchor_ms = now_ms
        if self.kind == "at":
            assert self.at_ms is not None
            return self.at_ms
        if self.kind == "after":
            assert self.delay_ms is not None
            return now_ms + self.delay_ms
        due = self.next_after(now_ms)
        assert due is not None
        return due

    def next_after(self, now_ms: int) -> int | None:
        if self.kind == "every":
            assert self.every_ms is not None
            anchor = self.anchor_ms if self.anchor_ms is not None else now_ms
            return anchor + (max(0, (now_ms - anchor) // self.every_ms) + 1) * self.every_ms
        if self.kind == "cron":
            return compute_next_run(CronSchedule(kind="cron", expr=self.expr, tz=self.tz), now_ms)
        return None
