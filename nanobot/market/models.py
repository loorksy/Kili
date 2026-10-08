"""Validated decimal market evidence, not strategy or execution authority."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from nanobot.config_base import Base


class Connection(Base):
    secret_ref: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    account_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    environment: Literal["practice", "live"] = "practice"
    region: str = Field(default="london", pattern=r"^[a-z][a-z0-9-]{1,30}$")


class IntegrationsConfig(Base):
    oanda: Connection | None = None
    metaapi: Connection | None = None
    charts_enabled: bool = False


class Instrument(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    display_symbol: str
    asset_class: str
    base: str | None = None
    quote: str | None = None


class TimedEvidence(BaseModel):
    @field_validator("time", "fetched_at", check_fields=False)
    @classmethod
    def aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("Market evidence requires an explicit timezone")
        return value.astimezone(timezone.utc)


class Candle(TimedEvidence):
    model_config = ConfigDict(extra="forbid")
    canonical_instrument: str
    provider_instrument: str
    time: datetime  # UTC candle start, not close time
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int | None = None
    complete: bool
    source: str
    fetched_at: datetime


class Quote(TimedEvidence):
    model_config = ConfigDict(extra="forbid")
    canonical_instrument: str
    provider_instrument: str
    time: datetime
    bid: Decimal
    ask: Decimal
    source: str
    fetched_at: datetime
    tradable: bool = True
