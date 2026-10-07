"""Validated chart operations; no model-authored JavaScript."""
from __future__ import annotations

import json
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.bus.events import OutboundMessage
from nanobot.bus.outbound_events import CloudChartChanged
from nanobot.charts.state import Annotation, ChartActor, ChartPoint, ChartService
from nanobot.security.actions import now_ms


class ChartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["create", "get", "set_instrument", "set_timeframe", "set_visible_range", "add_annotation", "update_annotation", "remove_annotation", "clear_annotations"]
    chart_id: str | None = None
    expected_revision: int | None = None
    canonical_instrument: str | None = None
    provider_instrument: str | None = None
    timeframe: str | None = None
    owner_scope: Literal["MAIN", "SHARED", "WORKER", "RESPONSIBILITY"] = "MAIN"
    visible_range: tuple[int, int] | None = None
    annotation_id: str | None = None
    annotation_type: Literal["horizontal_line", "trend_line", "price_zone", "marker", "note", "entry", "stop", "target"] = "note"
    points: list[ChartPoint] | None = None
    text: str = ""
    evidence_refs: list[str] = []


def current_chart_actor() -> ChartActor:
    request = current_request_context()
    if not request or not request.session_key:
        raise PermissionError("Chart requires a conversation")
    actor = ChartActor(principal=request.session_key)
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
        if request.operation == "create":
            if not request.canonical_instrument or not request.provider_instrument or not request.timeframe:
                raise ValueError("Chart requires explicit instruments and timeframe")
            chart = self.service.create(actor, request.canonical_instrument, request.provider_instrument,
                                         request.timeframe, request.owner_scope)
        else:
            if not request.chart_id:
                raise ValueError("Chart id is required")
            chart = self.service.get(request.chart_id, actor)
            if request.operation == "get":
                return chart.model_dump_json()
            if request.expected_revision is None:
                raise ValueError("Expected chart revision is required")
            if request.operation == "set_timeframe":
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
            else:
                chart.annotation_revision += 1
                if request.operation == "clear_annotations":
                    chart.annotations = []
                elif request.operation in {"add_annotation", "update_annotation"}:
                    if not request.points:
                        raise ValueError("Annotation points are required")
                    annotation = Annotation(id="annotation_" + uuid.uuid4().hex,
                                            type=request.annotation_type, points=request.points,
                                            text=request.text, evidence_refs=request.evidence_refs,
                                            created_by=actor.worker_id or actor.principal,
                                            responsibility_id=actor.responsibility_id)
                    if request.operation == "update_annotation":
                        existing = next((a for a in chart.annotations if a.id == request.annotation_id), None)
                        if existing is None:
                            raise ValueError("Unknown annotation")
                        annotation.id, annotation.created_at = existing.id, existing.created_at
                        annotation.updated_at = now_ms()
                        chart.annotations = [annotation if a.id == existing.id else a for a in chart.annotations]
                    else:
                        chart.annotations.append(annotation)
                elif request.operation == "remove_annotation":
                    if not any(a.id == request.annotation_id for a in chart.annotations):
                        raise ValueError("Unknown annotation")
                    chart.annotations = [a for a in chart.annotations if a.id != request.annotation_id]
            chart = self.service.update(chart, actor, request.expected_revision)
        if self.bus:
            session_key = chart.session_key
            channel, _, chat_id = session_key.partition(":")
            await self.bus.publish_outbound(OutboundMessage(channel=channel, chat_id=chat_id, content="",
                event=CloudChartChanged(chart_id=chart.id, revision=chart.revision,
                                       annotation_revision=chart.annotation_revision)))
        return "```trading_chart\n" + json.dumps(chart.contract()) + "\n```"
