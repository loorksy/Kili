"""Validated decimal market evidence, not strategy or execution authority."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from nanobot.config_base import Base


class Connection(Base):
    secret_ref: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,80}$")
    account_id: str = Field(pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    environment: Literal["practice", "live"] = "practice"
    region: str = Field(default="london", pattern=r"^[a-z][a-z0-9-]{1,30}$")
    name: str = Field(default="", max_length=80)


class IntegrationsConfig(Base):
    oanda: Connection | None = None
    metaapi: Connection | None = None
    metaapi_accounts: dict[str, Connection] = Field(default_factory=dict)
    default_metaapi_account: str | None = None
    charts_enabled: bool = False
    autonomous_trading_enabled: bool = False

    @model_validator(mode="after")
    def normalize_accounts(self) -> IntegrationsConfig:
        if self.metaapi is not None:
            self.metaapi_accounts.setdefault(self.metaapi.account_id, self.metaapi)
        for identity, connection in self.metaapi_accounts.items():
            if identity != connection.account_id:
                raise ValueError("Broker account key must match its exact MetaApi account ID")
        if self.default_metaapi_account is None and self.metaapi_accounts:
            self.default_metaapi_account = self.metaapi.account_id if self.metaapi else next(iter(self.metaapi_accounts))
        if self.default_metaapi_account is not None:
            if self.default_metaapi_account not in self.metaapi_accounts:
                raise ValueError("Default broker account is not configured")
            self.metaapi = self.metaapi_accounts[self.default_metaapi_account]
        return self

    def broker_accounts(self) -> dict[str, Connection]:
        accounts = dict(self.metaapi_accounts)
        if self.metaapi:
            accounts.setdefault(self.metaapi.account_id, self.metaapi)
        return accounts


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
    account_id: str | None = None


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
    account_id: str | None = None
