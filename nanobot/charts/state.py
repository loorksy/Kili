"""Backend chart identity, structured drawings, provenance and concurrency."""
from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    field_validator,
    model_validator,
)

from nanobot.charts.capabilities import DRAWING_ANCHORS
from nanobot.charts.indicators import IndicatorInstance
from nanobot.market.provider import TIMEFRAMES
from nanobot.security.actions import now_ms
from nanobot.session.records import RecordStore, RuntimeRecord

ChartTimestamp = Annotated[int, Field(ge=0, le=8640000000000000)]
ChartRange = tuple[ChartTimestamp, ChartTimestamp]


class ChartPoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    timestamp: int | None = Field(default=None, ge=0, le=8640000000000000)
    value: Decimal

    @field_validator("value")
    @classmethod
    def finite_price(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or abs(value) > Decimal("1e30"):
            raise ValueError("Chart prices must be finite and bounded")
        return value


class Annotation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^annotation_[a-f0-9]{32}$")
    type: Literal["horizontal_line", "trend_line", "price_zone", "marker", "note", "entry", "stop", "target", "drawing"]
    points: list[ChartPoint] = Field(min_length=1, max_length=9)
    library_name: str | None = None
    visible: bool = True
    locked: bool = False
    agent_editable: bool = False
    origin: Literal["USER", "NANOBOT", "SUBAGENT", "IMPORT"] = "NANOBOT"
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
        if self.library_name is not None and self.type != "drawing":
            raise ValueError("Library overlays must use the drawing type")
        if self.type == "drawing":
            if self.library_name not in DRAWING_ANCHORS:
                raise ValueError("Unavailable drawing tool")
            if len(self.points) != DRAWING_ANCHORS[self.library_name]:
                raise ValueError("Incorrect drawing anchor count")
            if any(point.timestamp is None for point in self.points):
                raise ValueError("Drawing anchors require explicit timestamps")
        if any(not point.value.is_finite() or abs(point.value) > Decimal("1e30") for point in self.points):
            raise ValueError("Drawing prices must be finite")
        if self.type in {"trend_line", "price_zone"} and len(self.points) != 2:
            raise ValueError("This annotation requires two points")
        if self.type == "trend_line" and any(point.timestamp is None for point in self.points):
            raise ValueError("Trend line requires explicit timestamps")
        return self


class CloudChart(RuntimeRecord):
    @model_validator(mode="before")
    @classmethod
    def legacy_provenance(cls, value: object) -> object:
        if isinstance(value, dict):
            parsed = TypeAdapter(dict[str, object]).validate_python(value)
            drawings = TypeAdapter(list[dict[str, object]]).validate_python(parsed.get("annotations", []))
            for drawing in drawings:
                # Older rows did not distinguish users from models: preserve them conservatively.
                drawing.setdefault("origin", "IMPORT")
            parsed["annotations"] = drawings
            return parsed
        return value

    owner_scope: Literal["MAIN", "SHARED", "WORKER", "RESPONSIBILITY"] = "MAIN"
    owner_reference: str
    session_key: str
    linked_responsibility_id: str | None = None
    canonical_instrument: str
    provider: Literal["oanda", "metaapi"] = "oanda"  # Retain legacy provenance; never relabel old evidence.
    account_id: str | None = None
    provider_instrument: str
    timeframe: str
    # Additive workstation format: legacy charts receive deterministic defaults.
    workstation_version: Literal[1] = 1
    history_window_id: str | None = None
    candle_count: int = Field(default=200, ge=2, le=5000)
    right_spacing: int = Field(default=40, ge=0, le=500)
    visible_range: ChartRange | None = None
    layout: dict[str, JsonValue] = Field(default_factory=dict)
    indicator_instances: list[IndicatorInstance] = Field(default_factory=list, max_length=20)
    studies: list[str] = Field(default_factory=list, max_length=20)
    annotations: list[Annotation] = Field(default_factory=list, max_length=500)
    annotation_revision: int = 0
    data_revision: str = ""

    def contract(self) -> dict[str, JsonValue]:
        return {"type": "trading_chart", "chart_id": self.id, "instrument": self.canonical_instrument,
                "provider": self.provider, "provider_instrument": self.provider_instrument,
                "account_id": self.account_id, "needs_account_binding": self.provider != "metaapi" or self.account_id is None,
                "timeframe": self.timeframe, "revision": self.revision,
                "annotations_revision": self.annotation_revision, "data_revision": self.data_revision,
                "session_key": self.session_key}


class ChartActor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    principal: str
    user_interaction: bool = False
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
            chart.data_revision = MarketCache(provider=chart.provider, account_id=chart.account_id).get(chart.provider_instrument, chart.canonical_instrument, chart.timeframe).data_revision
        except ValueError:
            pass
        if chart.history_window_id:
            from nanobot.charts.history import ChartHistory
            try:
                chart.data_revision = ChartHistory().get(chart).data_revision
            except ValueError:
                pass
        return chart

    def create(self, actor: ChartActor, canonical: str, symbol: str, timeframe: str,
               scope: Literal["MAIN", "SHARED", "WORKER", "RESPONSIBILITY"] = "MAIN", *,
               account_id: str | None = None) -> CloudChart:
        from nanobot.trading.metaapi import MetaApiClient
        MetaApiClient.validate_symbol(symbol)
        if timeframe not in TIMEFRAMES:
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
            provider="metaapi" if account_id else "oanda", account_id=account_id,
        ))

    def update(self, chart: CloudChart, actor: ChartActor, expected_revision: int) -> CloudChart:
        current = self.records.get(chart.id)
        self.require_access(current, actor, write=True)
        if not actor.user_interaction:
            proposed = {a.id: a for a in chart.annotations}
            for annotation in current.annotations:
                if annotation.origin in {"USER", "IMPORT"} and proposed.get(annotation.id) != annotation:
                    candidate = proposed.get(annotation.id)
                    if not annotation.agent_editable or (candidate and candidate.agent_editable != annotation.agent_editable):
                        raise PermissionError("User drawings require explicit user permission")
        for key in ("owner_scope", "owner_reference", "session_key", "linked_responsibility_id", "provider", "account_id"):
            if getattr(current, key) != getattr(chart, key):
                raise PermissionError("Chart ownership cannot change during an edit")
        if chart.revision != expected_revision:
            raise ValueError("Chart revision conflict")
        if chart.timeframe not in TIMEFRAMES:
            raise ValueError("Unsupported chart timeframe")
        if chart.visible_range and chart.visible_range[0] >= chart.visible_range[1]:
            raise ValueError("Invalid visible range")
        validated = CloudChart.model_validate(chart.model_dump())
        return self.records.save(validated)
