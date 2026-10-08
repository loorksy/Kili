"""Validated chart operations; no model-authored JavaScript."""
from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import CloudChartChanged
from nanobot.charts.capabilities import (
    BUILTIN_DEFAULTS,
    DRAWING_ANCHORS,
    drawing_descriptors,
    indicator_descriptors,
)
from nanobot.charts.controller import ChartController, ViewOperation
from nanobot.charts.state import Annotation, ChartActor, ChartPoint, ChartService
from nanobot.charts.work import (
    get_presence,
    put_temporary,
    remove_temporary,
    set_presence,
    temporary_drawings,
)
from nanobot.security.actions import now_ms
from nanobot.session.records import RecordStore


class ChartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["create", "get", "set_instrument", "set_timeframe", "set_visible_range", "set_studies", "add_annotation", "update_annotation", "remove_annotation", "clear_annotations", "view", "inspect_candle", "capabilities", "duplicate_annotation", "configure_annotation", "load_history", "clear_temporary", "publish_annotation", "cursor", "select_drawing_tool", "inspect_presence"]
    history_count: int = Field(default=500, ge=2, le=5000)
    history_before: str | None = None
    view: ViewOperation | None = None
    candle_timestamp: int | None = None
    candle_index: int | None = None
    temporary: bool = False
    drawing_name: str | None = None
    object_revision: int | None = None
    visible: bool | None = None
    locked: bool | None = None
    chart_id: str | None = None
    expected_revision: int | None = None
    canonical_instrument: str | None = None
    provider_instrument: str | None = None
    timeframe: str | None = None
    owner_scope: Literal["MAIN", "SHARED", "WORKER", "RESPONSIBILITY"] = "MAIN"
    visible_range: tuple[int, int] | None = None
    studies: list[str] | None = None
    annotation_id: str | None = None
    annotation_type: Literal["horizontal_line", "trend_line", "price_zone", "marker", "note", "entry", "stop", "target", "drawing"] = "note"
    points: list[ChartPoint] | None = Field(default=None, min_length=1, max_length=9)
    text: str = Field(default="", max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


def current_chart_actor() -> ChartActor:
    request = current_request_context()
    if not request or not request.session_key:
        raise PermissionError("Chart requires a conversation")
    actor = ChartActor(principal=request.session_key, user_interaction=request.attributes.get("chart_user_interaction") is True)
    for execution in request.responsibility_scope.executions.values():
        child = execution.store.assert_owner(execution.claim)
        if child.parent_responsibility_id:
            parent = execution.store.get(child.parent_responsibility_id)
            if parent.execution_generation != child.parent_execution_generation:
                raise PermissionError("Delegation was superseded")
            actor = ChartActor(principal=request.session_key, worker_id=child.delegation_id,
                               responsibility_id=child.id, parent_principal=parent.session_key)
        else:
            actor = ChartActor(principal=request.session_key, responsibility_id=child.id)
    return actor


class ChartTool(Tool):
    _scopes = {"core", "subagent"}

    def __init__(self, ctx: ToolContext):
        self.ctx = ctx
        self.service = ChartService()
        self.bus = ctx.bus

    @property
    def name(self) -> str:
        return "chart"

    @property
    def description(self) -> str:
        return "Create/get/update a persistent cloud chart, instrument/timeframe/range or structured annotations. Include expected_revision for edits. Return the trading_chart code fence to embed it in chat."

    @property
    def parameters(self) -> dict[str, Any]:
        return ChartRequest.model_json_schema()

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.config.integrations.charts_enabled

    @classmethod
    def create(cls, ctx: ToolContext) -> ChartTool:
        return cls(ctx)

    async def execute(self, **kwargs: Any) -> str:
        request = ChartRequest.model_validate(kwargs)
        actor = current_chart_actor()
        if request.operation == "capabilities":
            return json.dumps({"version": 1, "library": "klinecharts@9.8.12+pro@0.1.1",
                "drawings": drawing_descriptors(),
                "indicators": indicator_descriptors(),
                "viewport": ["reframe", "zoom", "pan", "jump", "range"], "custom_indicator_format": "nanobot-indicator-ir-v1"})
        if request.operation == "create":
            if not request.canonical_instrument or not request.provider_instrument or not request.timeframe:
                raise ValueError("Chart requires explicit instruments and timeframe")
            chart = self.service.create(actor, request.canonical_instrument, request.provider_instrument,
                                         request.timeframe, request.owner_scope)
        else:
            if not request.chart_id:
                raise ValueError("Chart id is required")
            chart = self.service.get(request.chart_id, actor)
            if request.operation == "load_history":
                from nanobot.market.oanda import OandaClient
                connection = self.ctx.config.integrations.oanda
                if connection is None:
                    raise ValueError("OANDA connection is not configured")
                candles = await OandaClient(connection).candles(chart.provider_instrument, chart.canonical_instrument, chart.timeframe, count=request.history_count, before=request.history_before)
                return json.dumps({"chart_id": chart.id, "timeframe": chart.timeframe, "candles": [c.model_dump(mode="json") for c in candles]})
            if request.operation == "get":
                state = chart.model_dump(mode="json")
                state["temporary_annotations"] = [a.model_dump(mode="json") for a in temporary_drawings(chart.id, actor.principal)]
                return json.dumps(state)
            if request.operation == "inspect_presence":
                cursor, selected = get_presence(chart.id, actor.principal)
                return json.dumps({"cursor": cursor.model_dump(mode="json") if cursor else None, "drawing_tool": selected, "visible_range": chart.visible_range, "candle_count": chart.candle_count})
            if request.operation == "inspect_candle":
                return ChartController(self.service).inspect(chart, timestamp=request.candle_timestamp, index=request.candle_index).model_dump_json()
            if request.expected_revision is None:
                raise ValueError("Expected chart revision is required")
            if request.operation in {"update_annotation", "remove_annotation", "configure_annotation"} and request.object_revision is not None:
                # Object CAS can merge an unrelated newer chart edit; it never authorizes a stale object.
                request.expected_revision = chart.revision
            temporary_changed = False
            if request.operation in {"cursor", "select_drawing_tool"}:
                self.service.require_access(chart, actor, write=True)
                if request.operation == "select_drawing_tool" and request.drawing_name not in DRAWING_ANCHORS:
                    raise ValueError("Unavailable drawing tool")
                if request.operation == "cursor" and (not request.points or request.points[0].timestamp is None):
                    raise ValueError("Cursor requires a market timestamp and price")
                with RecordStore.execution_write():
                    set_presence(chart.id, actor.principal, request.points[0] if request.points else None, request.drawing_name)
                temporary_changed = True
            elif request.operation == "clear_temporary":
                self.service.require_access(chart, actor, write=True)
                with RecordStore.execution_write():
                    remove_temporary(chart.id, actor.principal)
                temporary_changed = True
            elif request.operation == "publish_annotation":
                annotation = next((a for a in temporary_drawings(chart.id, actor.principal) if a.id == request.annotation_id), None)
                if annotation is None:
                    raise ValueError("Unknown temporary annotation")
                chart.annotations.append(annotation)
                chart.annotation_revision += 1
            elif request.operation == "view":
                if request.view is None:
                    raise ValueError("Structured viewport operation is required")
                chart = ChartController(self.service).view(chart, actor, request.expected_revision, request.view)
            elif request.operation == "set_timeframe":
                if not request.timeframe:
                    raise ValueError("Timeframe is required")
                chart.timeframe = request.timeframe
            elif request.operation == "set_instrument":
                if not request.canonical_instrument or not request.provider_instrument:
                    raise ValueError("Explicit instruments are required")
                from nanobot.market.oanda import OandaClient
                OandaClient.validate_symbol(request.provider_instrument)
                chart.canonical_instrument, chart.provider_instrument = request.canonical_instrument, request.provider_instrument
                chart.data_revision = ""
            elif request.operation == "set_visible_range":
                chart.visible_range = request.visible_range
            elif request.operation == "set_studies":
                if request.studies is None:
                    raise ValueError("Structured studies are required")
                if len(request.studies) > 20 or any(name not in BUILTIN_DEFAULTS for name in request.studies):
                    raise ValueError("Unavailable or excessive chart studies")
                chart.studies = list(request.studies)
            else:
                chart.annotation_revision += 1
                existing = next((a for a in chart.annotations if a.id == request.annotation_id), None)
                if request.operation in {"update_annotation", "remove_annotation", "configure_annotation", "duplicate_annotation"}:
                    if existing is None:
                        raise ValueError("Unknown annotation")
                    if request.object_revision is not None and existing.revision != request.object_revision:
                        raise ValueError("Drawing revision conflict")
                if request.operation == "configure_annotation":
                    if existing is None:
                        raise ValueError("Unknown annotation")
                    if request.visible is not None:
                        existing.visible = request.visible
                    if request.locked is not None:
                        existing.locked = request.locked
                    existing.revision += 1
                    existing.updated_at = now_ms()
                elif request.operation == "duplicate_annotation":
                    if existing is None:
                        raise ValueError("Unknown annotation")
                    copy = existing.model_copy(deep=True)
                    copy.id = "annotation_" + uuid.uuid4().hex
                    copy.created_by = actor.worker_id or actor.principal
                    copy.origin = "USER" if actor.user_interaction else "SUBAGENT" if actor.worker_id else "NANOBOT"
                    copy.revision = 0
                    copy.created_at = copy.updated_at = now_ms()
                    chart.annotations.append(copy)
                elif request.operation == "clear_annotations":
                    chart.annotations = []
                elif request.operation in {"add_annotation", "update_annotation"}:
                    if not request.points:
                        raise ValueError("Annotation points are required")
                    annotation = Annotation(id="annotation_" + uuid.uuid4().hex,
                                            type=request.annotation_type, points=request.points,
                                            library_name=request.drawing_name or (existing.library_name if existing else None),
                                            origin="USER" if actor.user_interaction else "SUBAGENT" if actor.worker_id else "NANOBOT",
                                            text=request.text, evidence_refs=request.evidence_refs,
                                            created_by=actor.worker_id or actor.principal,
                                            responsibility_id=actor.responsibility_id)
                    if request.operation == "update_annotation":
                        existing = next((a for a in chart.annotations if a.id == request.annotation_id), None)
                        if existing is None:
                            raise ValueError("Unknown annotation")
                        annotation.id, annotation.created_at = existing.id, existing.created_at
                        annotation.created_by = existing.created_by
                        annotation.origin = existing.origin
                        annotation.visible, annotation.locked = existing.visible, existing.locked
                        annotation.library_name = request.drawing_name or existing.library_name
                        annotation.responsibility_id = existing.responsibility_id
                        annotation.updated_by = actor.worker_id or actor.principal
                        annotation.revision = existing.revision + 1
                        annotation.updated_at = now_ms()
                        chart.annotations = [annotation if a.id == existing.id else a for a in chart.annotations]
                    else:
                        if request.temporary:
                            self.service.require_access(chart, actor, write=True)
                            with RecordStore.execution_write():
                                put_temporary(chart.id, actor.principal, annotation)
                            temporary_changed = True
                        else:
                            chart.annotations.append(annotation)
                elif request.operation == "remove_annotation":
                    if not any(a.id == request.annotation_id for a in chart.annotations):
                        raise ValueError("Unknown annotation")
                    chart.annotations = [a for a in chart.annotations if a.id != request.annotation_id]
            if request.operation != "view" and not temporary_changed:
                chart = self.service.update(chart, actor, request.expected_revision)
                if request.operation == "publish_annotation":
                    remove_temporary(chart.id, actor.principal, request.annotation_id)
            if temporary_changed:
                chart = self.service.get(chart.id, actor)
        if self.bus:
            session_key = chart.session_key
            channel, _, chat_id = session_key.partition(":")
            await self.bus.publish_outbound(OutboundMessage(channel=channel, chat_id=chat_id, content="",
                event=CloudChartChanged(chart_id=chart.id, revision=chart.revision,
                                       annotation_revision=chart.annotation_revision,
                                       operation=None if actor.user_interaction else request.operation,
                                       anchors=tuple((p.timestamp, str(p.value)) for p in (request.points or []) if p.timestamp is not None),
                                       occurred_at=now_ms())))
        return "```trading_chart\n" + json.dumps(chart.contract()) + "\n```"
