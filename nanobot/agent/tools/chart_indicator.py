"""Discovery, safe indicator creation/import, immutable versions and chart instances."""
from __future__ import annotations

import asyncio
import json
import uuid
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.chart import current_chart_actor
from nanobot.agent.tools.context import ToolContext
from nanobot.agent.tools.path_utils import resolve_workspace_path
from nanobot.charts.capabilities import BUILTIN_DEFAULTS, indicator_descriptors
from nanobot.charts.controller import candle_time, chart_candles
from nanobot.charts.indicators import (
    IndicatorDefinition,
    IndicatorInstance,
    IndicatorRegistry,
    evaluate,
)
from nanobot.charts.native_indicators import native_values
from nanobot.charts.state import ChartService
from nanobot.charts.work import (
    put_temporary_indicator,
    remove_temporary_indicator,
    temporary_indicators,
)
from nanobot.session.records import RecordStore


class IndicatorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["discover", "create", "import", "publish", "get_definition", "add", "update", "remove", "values"]
    temporary: bool = False
    query: str = Field(default="", max_length=200)
    definition: IndicatorDefinition | None = None
    family_id: str | None = None
    path: str | None = None
    indicator_id: str | None = None
    chart_id: str | None = None
    instance_id: str | None = None
    expected_revision: int | None = None
    object_revision: int | None = None
    parameters: dict[str, Decimal] = Field(default_factory=dict, max_length=16)
    calc_params: list[float] = Field(default_factory=list, max_length=16)
    pane: Literal["main", "separate"] = "main"
    visible: bool = True


class ChartIndicatorTool(Tool):
    _scopes = {"core", "subagent"}

    def __init__(self, ctx: ToolContext):
        self.ctx = ctx
        self.registry = IndicatorRegistry()
        self.charts = ChartService()

    @property
    def name(self) -> str:
        return "chart_indicator"

    @property
    def description(self) -> str:
        return "Discover/search chart indicators, create a validated safe data-IR definition from the user's description, import JSON IR (never scripts), add/configure/remove chart indicators, or inspect numerical built-in/custom indicator values. Definitions are immutable versions; edits need expected_revision."

    @property
    def parameters(self) -> dict[str, Any]:
        return IndicatorRequest.model_json_schema()

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.config.integrations.charts_enabled

    @classmethod
    def create(cls, ctx: ToolContext) -> ChartIndicatorTool:
        return cls(ctx)

    async def execute(self, **kwargs: Any) -> str:
        request = IndicatorRequest.model_validate(kwargs)
        actor = current_chart_actor()
        principal = actor.parent_principal or actor.principal
        if request.operation == "discover":
            custom = self.registry.search(principal, request.query)
            return json.dumps({"builtin": indicator_descriptors(request.query),
                "custom": [{"id": r.id, "name": r.definition.name, "version": r.indicator_version, "source": r.source, "description": r.definition.description, "scope": r.scope} for r in custom]})
        if request.operation in {"create", "import"}:
            definition = request.definition
            filename = None
            if request.operation == "import":
                if not request.path:
                    raise ValueError("Import requires an uploaded JSON IR file")
                path = resolve_workspace_path(request.path, workspace=Path(self.ctx.workspace), allowed_dir=Path(self.ctx.workspace))
                if path.suffix.lower() != ".json" or path.stat().st_size > 262144:
                    raise ValueError("Only bounded JSON indicator IR imports are supported; scripts are never executed")
                with path.open("rb") as handle:
                    raw = handle.read(262145)
                if len(raw) > 262144:
                    raise ValueError("Indicator import exceeds bounded size")
                definition = IndicatorDefinition.model_validate_json(raw)
                filename = path.name
            if definition is None:
                raise ValueError("Provide a safe final indicator definition, not executable code")
            result = self.registry.register(definition, principal, family_id=request.family_id,
                source="USER_IMPORTED" if request.operation == "import" else "CUSTOM", filename=filename)
            return result.model_dump_json()
        if request.operation == "publish":
            if not request.indicator_id:
                raise ValueError("Indicator id is required")
            original = self.registry.get(request.indicator_id, principal)
            if original.author != principal:
                raise PermissionError("Only the indicator owner can publish a definition")
            return self.registry.register(original.definition, principal, family_id=original.family_id,
                source=original.source, filename=original.original_filename, scope="SHARED").model_dump_json()
        if request.operation == "get_definition":
            if request.indicator_id is None:
                raise ValueError("Indicator id is required")
            return self.registry.get(request.indicator_id, principal).model_dump_json()
        if not request.chart_id:
            raise ValueError("Chart id is required")
        chart = self.charts.get(request.chart_id, actor)
        experiments = temporary_indicators(chart.id, actor.principal)
        instance = next((s for s in [*chart.indicator_instances, *experiments] if s.id == request.instance_id), None)
        existing_temporary = any(s.id == request.instance_id for s in experiments)
        if request.temporary and instance is not None and not existing_temporary:
            raise ValueError("Create a temporary copy instead of changing a durable indicator lifetime")
        is_temporary = request.temporary or existing_temporary
        if request.operation == "values":
            if instance is None:
                raise ValueError("Unknown indicator instance")
            if instance.indicator_id in BUILTIN_DEFAULTS:
                data = chart_candles(chart)
                native = await asyncio.to_thread(native_values, instance.indicator_id, data, instance.calc_params)
                return json.dumps({"timestamps": [candle_time(c) for c in data], "native": native.model_dump(mode="json"), "library": "klinecharts@9.8.12"})
            record = self.registry.get(instance.indicator_id, principal)
            candles = chart_candles(chart)
            result = evaluate(record.definition, candles, instance.parameters)
            return json.dumps({"timestamps": [candle_time(c) for c in candles], "values": {key: [str(v) if v is not None else None for v in values] for key, values in result.items()}, "definition_hash": record.definition_hash, "version": record.indicator_version})
        if request.expected_revision is None:
            raise ValueError("Expected chart revision is required")
        self.charts.require_access(chart, actor, write=True)
        if request.operation in {"update", "remove"}:
            if instance is None:
                raise ValueError("Unknown indicator instance")
            if request.object_revision is not None and instance.revision != request.object_revision:
                raise ValueError("Indicator instance revision conflict")
        if request.operation == "remove":
            if is_temporary and instance:
                with RecordStore.execution_write():
                    remove_temporary_indicator(chart.id, actor.principal, instance.id)
            else:
                chart.indicator_instances = [s for s in chart.indicator_instances if s.id != request.instance_id]
        else:
            identifier = request.indicator_id or (instance.indicator_id if instance else None)
            if identifier is None:
                raise ValueError("Indicator id is required")
            if identifier in BUILTIN_DEFAULTS:
                params = request.calc_params if "calc_params" in request.model_fields_set else instance.calc_params if instance else BUILTIN_DEFAULTS[identifier]
                pane = "main" if identifier in {"MA", "EMA", "BOLL", "SAR"} else "separate"
                if len(params) != len(BUILTIN_DEFAULTS[identifier]) or any(not 0 < p <= 512 for p in params):
                    raise ValueError("Invalid built-in indicator parameters")
            else:
                record = self.registry.get(identifier, principal)
                if chart.owner_scope == "SHARED" and record.scope != "SHARED":
                    raise PermissionError("Publish a shared indicator version before using it on a shared chart")
                parameters = request.parameters if "parameters" in request.model_fields_set else instance.parameters if instance else {}
                evaluate(record.definition, chart_candles(chart), parameters)
                params = []
                pane = record.definition.pane
            updated = IndicatorInstance(id=instance.id if instance else "study_" + uuid.uuid4().hex,
                indicator_id=identifier, parameters=request.parameters if "parameters" in request.model_fields_set else instance.parameters if instance else {}, calc_params=params,
                pane=request.pane if "pane" in request.model_fields_set else instance.pane if instance else pane,
                visible=request.visible if "visible" in request.model_fields_set else instance.visible if instance else True, created_by=instance.created_by if instance else actor.worker_id or actor.principal,
                revision=instance.revision + 1 if instance else 0)
            if is_temporary:
                with RecordStore.execution_write():
                    put_temporary_indicator(chart.id, actor.principal, updated)
            elif instance:
                chart.indicator_instances = [updated if s.id == instance.id else s for s in chart.indicator_instances]
            else:
                chart.indicator_instances.append(updated)
        if not is_temporary:
            chart = self.charts.update(chart, actor, request.expected_revision)
        if self.ctx.bus:
            from nanobot.bus.events import OutboundMessage
            from nanobot.bus.outbound_events import CloudChartChanged
            channel, _, chat_id = chart.session_key.partition(":")
            await self.ctx.bus.publish_outbound(OutboundMessage(channel=channel, chat_id=chat_id, content="",
                event=CloudChartChanged(chart_id=chart.id, revision=chart.revision, annotation_revision=chart.annotation_revision, operation="indicator_" + request.operation,
                                       occurred_at=chart.updated_at)))
        state = chart.model_dump(mode="json")
        state["temporary_indicator_instances"] = [s.model_dump(mode="json") for s in temporary_indicators(chart.id, actor.principal)]
        return json.dumps(state)
