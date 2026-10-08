"""Backend chart identity, structured drawings, provenance and concurrency."""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from nanobot.market.oanda import GRANULARITIES
from nanobot.security.actions import now_ms
from nanobot.session.records import RecordStore, RuntimeRecord


class ChartPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: int | None = None
    value: Decimal


class Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^annotation_[a-f0-9]{32}$")
    type: Literal["horizontal_line", "trend_line", "price_zone", "marker", "note", "entry", "stop", "target"]
    points: list[ChartPoint] = Field(min_length=1, max_length=2)
    text: str = Field(default="", max_length=2000)
    created_by: str
    responsibility_id: str | None = None
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)
    created_at: int = Field(default_factory=now_ms)
    updated_at: int = Field(default_factory=now_ms)
    revision: int = 0
    updated_by: str | None = None

    @model_validator(mode="after")
    def geometry(self) -> Annotation:
        if self.type in {"trend_line", "price_zone"} and len(self.points) != 2:
            raise ValueError("This annotation requires two points")
        if self.type == "trend_line" and any(point.timestamp is None for point in self.points):
            raise ValueError("Trend line requires explicit timestamps")
        return self


class CloudChart(RuntimeRecord):
    owner_scope: Literal["MAIN", "SHARED", "WORKER", "RESPONSIBILITY"] = "MAIN"
    owner_reference: str
    session_key: str
    linked_responsibility_id: str | None = None
    canonical_instrument: str
    provider: Literal["oanda"] = "oanda"
    provider_instrument: str
    timeframe: str
    visible_range: tuple[int, int] | None = None
    layout: dict[str, JsonValue] = Field(default_factory=dict)
    studies: list[str] = Field(default_factory=list, max_length=20)
    annotations: list[Annotation] = Field(default_factory=list, max_length=500)
    annotation_revision: int = 0
    data_revision: str = ""

    def contract(self) -> dict[str, JsonValue]:
        return {"type": "trading_chart", "chart_id": self.id, "instrument": self.canonical_instrument,
                "provider": self.provider, "provider_instrument": self.provider_instrument,
                "timeframe": self.timeframe, "revision": self.revision,
                "annotations_revision": self.annotation_revision, "data_revision": self.data_revision,
                "session_key": self.session_key}


class ChartActor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    principal: str
    worker_id: str | None = None
    responsibility_id: str | None = None
    parent_principal: str | None = None


class ChartService:
    def __init__(self, records: RecordStore[CloudChart] | None = None):
        self.records = records or RecordStore("charts", CloudChart)

    @staticmethod
    def require_access(chart: CloudChart, actor: ChartActor, *, write: bool = False) -> None:
        if chart.owner_scope == "WORKER":
            if chart.owner_reference != actor.worker_id and not (not write and chart.session_key == actor.principal):
                raise PermissionError("Private worker chart is outside this scope")
        elif chart.owner_scope == "RESPONSIBILITY":
            if chart.owner_reference != actor.responsibility_id and chart.session_key != actor.principal:
                raise PermissionError("Responsibility chart is outside this scope")
        elif chart.owner_scope != "SHARED" and chart.owner_reference != actor.principal:
            raise PermissionError("Private chart belongs to another conversation")

    def get(self, chart_id: str, actor: ChartActor) -> CloudChart:
        chart = self.records.get(chart_id)
        self.require_access(chart, actor)
        from nanobot.market.cache import MarketCache
        try:
            chart.data_revision = MarketCache().get(chart.provider_instrument, chart.canonical_instrument, chart.timeframe).data_revision
        except ValueError:
            pass
        return chart

    def create(self, actor: ChartActor, canonical: str, symbol: str, timeframe: str,
               scope: Literal["MAIN", "SHARED", "WORKER", "RESPONSIBILITY"] = "MAIN") -> CloudChart:
        from nanobot.market.oanda import OandaClient
        OandaClient.validate_symbol(symbol)
        if timeframe not in GRANULARITIES:
            raise ValueError("Unsupported chart timeframe")
        if actor.worker_id and scope == "MAIN":
            scope = "WORKER"
        owner = actor.worker_id if scope == "WORKER" else (
            actor.responsibility_id if scope == "RESPONSIBILITY" else actor.principal)
        if not owner:
            raise PermissionError("Chart scope requires a live owner")
        return self.records.create(CloudChart(
            id="chart_" + uuid.uuid4().hex, owner_scope=scope, owner_reference=owner,
            session_key=actor.parent_principal or actor.principal,
            linked_responsibility_id=actor.responsibility_id, canonical_instrument=canonical,
            provider_instrument=symbol, timeframe=timeframe,
        ))

    def update(self, chart: CloudChart, actor: ChartActor, expected_revision: int) -> CloudChart:
        current = self.records.get(chart.id)
        self.require_access(current, actor, write=True)
        for key in ("owner_scope", "owner_reference", "session_key", "linked_responsibility_id"):
            if getattr(current, key) != getattr(chart, key):
                raise PermissionError("Chart ownership cannot change during an edit")
        if chart.revision != expected_revision:
            raise ValueError("Chart revision conflict")
        if chart.timeframe not in GRANULARITIES:
            raise ValueError("Unsupported chart timeframe")
        if chart.visible_range and chart.visible_range[0] >= chart.visible_range[1]:
            raise ValueError("Invalid visible range")
        validated = CloudChart.model_validate(chart.model_dump())
        return self.records.save(validated)
