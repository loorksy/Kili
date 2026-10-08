"""Validated chart operations; no model-authored JavaScript."""
from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

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
from nanobot.charts.state import Annotation, ChartActor, ChartPoint, ChartRange, ChartService
from nanobot.charts.work import (
    get_presence,
    get_user_cursor,
    put_temporary,
    remove_temporary,
    report_user_cursor,
    set_presence,
    temporary_drawings,
    temporary_indicators,
)
from nanobot.security.actions import now_ms
from nanobot.session.records import RecordStore


class ChartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["create", "get", "set_instrument", "set_timeframe", "set_visible_range", "set_studies", "add_annotation", "update_annotation", "remove_annotation", "clear_annotations", "view", "inspect_candle", "capabilities", "duplicate_annotation", "configure_annotation", "load_history", "clear_temporary", "publish_annotation", "cursor", "select_drawing_tool", "inspect_presence", "set_animation_mode", "report_crosshair"]
    history_count: int = Field(default=500, ge=2, le=5000)
    history_before: str | None = None
    view: ViewOperation | None = None
    candle_timestamp: int | None = Field(default=None, ge=0, le=8640000000000000)
    candle_index: int | None = None
    pointer_pane: str = Field(default="candle_pane", max_length=80)
    animation_mode: Literal["normal", "fast", "instant"] = "fast"
    temporary: bool = False
    drawing_name: str | None = None
    object_revision: int | None = None
    visible: bool | None = None
    locked: bool | None = None
    agent_editable: bool | None = None
    chart_id: str | None = None
    account_id: str | None = None
    expected_revision: int | None = None
    canonical_instrument: str | None = None
    provider_instrument: str | None = None
    timeframe: str | None = None
    owner_scope: Literal["MAIN", "SHARED", "WORKER", "RESPONSIBILITY"] = "MAIN"
    visible_range: ChartRange | None = None
    studies: list[str] | None = None
    annotation_id: str | None = None
    annotation_type: Literal["horizontal_line", "trend_line", "price_zone", "marker", "note", "entry", "stop", "target", "drawing"] = "note"
    points: list[ChartPoint] | None = Field(default=None, min_length=1, max_length=9)
    text: str = Field(default="", max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=20)


    @field_validator("drawing_name")
    @classmethod
    def supported_drawing(cls, value: str | None) -> str | None:
        if value is not None and value not in DRAWING_ANCHORS:
            raise ValueError("Unavailable drawing tool")
        return value

    @field_validator("history_before")
    @classmethod
    def aware_history_boundary(cls, value: str | None) -> str | None:
        if value is not None and datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
            raise ValueError("Historical boundary requires an explicit timezone")
        return value


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
        return "Operate the persistent cloud chart with semantic timestamps/prices: capabilities discovery, historical loading, view zoom/pan/jump/range, exact candle inspection, drawings and virtual cursor. Include expected_revision for edits and object_revision for drawing edits. Temporary drawings require explicit publication. Return the trading_chart code fence when the user requests chart analysis or a recommendation benefits from a visual chart; it opens the collapsible chart workspace. Do not open charts for greetings, simple quotes, or every background tick. A chart reference is not an image attachment; use chart_snapshot format=attachment and message media when the user asks for a picture."

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
            from nanobot.market.broker import BrokerMarket
            from nanobot.trading.accounts import TradingAccounts
            market = BrokerMarket(TradingAccounts(self.ctx.config.integrations).client(request.account_id, principal=actor.principal))
            await market.verify(request.provider_instrument, request.canonical_instrument)
            if request.timeframe not in await market.timeframes():
                raise ValueError("Timeframe is not supported by this broker account")
            chart = self.service.create(actor, request.canonical_instrument, request.provider_instrument,
                                         request.timeframe, request.owner_scope, account_id=market.connection.account_id)
        else:
            if not request.chart_id:
                raise ValueError("Chart id is required")
            chart = self.service.get(request.chart_id, actor)
            if request.account_id and request.account_id != chart.account_id:
                raise PermissionError("Chart remains bound to its original broker account")
            if chart.provider != "metaapi" or chart.account_id is None:
                if request.operation != "get":
                    raise ValueError("Legacy chart is archived: create a broker chart with an explicit symbol; old evidence is not relabelled")
            from nanobot.market.broker import BrokerMarket
            from nanobot.trading.accounts import TradingAccounts
            if request.operation == "load_history":
                market = BrokerMarket(TradingAccounts(self.ctx.config.integrations).client(chart.account_id))
                self.service.require_access(chart, actor, write=True)
                if request.expected_revision is None:
                    raise ValueError("Expected revision is required to select a historical window")
                candles = await market.candles(chart.provider_instrument, chart.canonical_instrument, chart.timeframe, count=request.history_count, before=request.history_before)
                if not candles:
                    raise ValueError("Broker returned no history in this range")
                from nanobot.charts.history import ChartHistory
                window = ChartHistory().put(chart, candles)
                chart.history_window_id = window.id
                chart.candle_count = len(window.candles)
                chart.visible_range = (int(window.candles[0].time.timestamp() * 1000), int(window.candles[-1].time.timestamp() * 1000))
                chart = self.service.update(chart, actor, request.expected_revision)
                if self.bus:
                    channel, _, chat_id = chart.session_key.partition(":")
                    await self.bus.publish_outbound(OutboundMessage(channel=channel, chat_id=chat_id, content="", event=CloudChartChanged(chart_id=chart.id, revision=chart.revision, annotation_revision=chart.annotation_revision, operation="load_history", occurred_at=now_ms())))
                return json.dumps({"chart_id": chart.id, "timeframe": chart.timeframe, "candles": [c.model_dump(mode="json") for c in candles]})
            if request.operation == "get":
                state = chart.model_dump(mode="json")
                state["temporary_indicator_instances"] = [s.model_dump(mode="json") for s in temporary_indicators(chart.id, actor.principal)]
                state["temporary_annotations"] = [a.model_dump(mode="json") for a in temporary_drawings(chart.id, actor.principal)]
                return json.dumps(state)
            if request.operation == "report_crosshair":
                if not actor.user_interaction:
                    raise PermissionError("Only an authenticated user client can report its crosshair")
                if request.points and (len(request.points) != 1 or request.points[0].timestamp is None):
                    raise ValueError("Crosshair requires one semantic point")
                with RecordStore.execution_write():
                    report_user_cursor(chart.id, actor.principal, request.points[0] if request.points else None, request.pointer_pane)
                return json.dumps({"reported": True})
            if request.operation == "inspect_presence":
                cursor, selected = get_presence(chart.id, actor.principal)
                user_cursor, age, pane = get_user_cursor(chart.id, actor.principal)
                return json.dumps({"user_crosshair": user_cursor.model_dump(mode="json") if user_cursor else None, "user_crosshair_age_ms": age, "user_crosshair_pane": pane, "cursor": cursor.model_dump(mode="json") if cursor else None, "drawing_tool": selected, "visible_range": chart.visible_range, "candle_count": chart.candle_count})
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
                if request.drawing_name is not None and request.drawing_name not in DRAWING_ANCHORS:
                    raise ValueError("Unavailable drawing tool")
                if request.operation == "cursor" and (not request.points or len(request.points) != 1 or request.points[0].timestamp is None):
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
                market = BrokerMarket(TradingAccounts(self.ctx.config.integrations).client(chart.account_id))
                if request.timeframe not in await market.timeframes():
                    raise ValueError("Timeframe is not supported by this broker account")
                chart.timeframe = request.timeframe
                chart.history_window_id = None
            elif request.operation == "set_instrument":
                if not request.canonical_instrument or not request.provider_instrument:
                    raise ValueError("Explicit instruments are required")
                market = BrokerMarket(TradingAccounts(self.ctx.config.integrations).client(chart.account_id))
                await market.verify(request.provider_instrument, request.canonical_instrument)
                chart.canonical_instrument, chart.provider_instrument = request.canonical_instrument, request.provider_instrument
                chart.data_revision = ""
                chart.history_window_id = None
                chart.visible_range = None
            elif request.operation == "set_visible_range":
                chart.visible_range = request.visible_range
            elif request.operation == "set_animation_mode":
                chart.layout["agent_animation_mode"] = request.animation_mode
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
                    if request.agent_editable is not None:
                        if not actor.user_interaction:
                            raise PermissionError("Only the user can authorize edits to user drawings")
                        existing.agent_editable = request.agent_editable
                    if request.visible is not None:
                        existing.visible = request.visible
                    if request.locked is not None:
                        existing.locked = request.locked
                    existing.revision += 1
                    existing.updated_at = now_ms()
                    existing.updated_by = actor.worker_id or actor.principal
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
                        annotation.agent_editable = existing.agent_editable
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
