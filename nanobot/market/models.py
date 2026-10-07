"""Validated decimal market evidence, not strategy or execution authority."""
from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nanobot.config_base import Base


class Connection(Base):
    secret_ref: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    account_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    environment: Literal["practice", "live"] = "practice"


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


class InstrumentMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: Literal[1] = 1
    instrument: Instrument
    provider: Literal["oanda", "metaapi"]
    account_id: str
    provider_symbol: str
    status: Literal["UNVERIFIED", "VERIFIED", "AMBIGUOUS"] = "UNVERIFIED"
    verified_at: datetime | None = None


class Candle(BaseModel):
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


class Quote(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_instrument: str
    provider_instrument: str
    time: datetime
    bid: Decimal
    ask: Decimal
    source: str
    fetched_at: datetime
    tradable: bool = True
