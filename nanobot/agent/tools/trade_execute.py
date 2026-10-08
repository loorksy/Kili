"""Financial mutations require canonical preview policy, approval and effect ownership."""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.trading.execution import TradeExecutor
from nanobot.trading.metaapi import MetaApiClient
from nanobot.trading.proposals import TradeProposals


class ExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preview_id: str


class ReconcileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    effect_id: str


def principal() -> str:
    context = current_request_context()
    if not context or not context.session_key:
        raise PermissionError("Trading requires a conversation")
    return context.session_key


class TradeExecuteTool(Tool):
    action_class = "consequential"
    manages_effects = True

    def __init__(self, executor: TradeExecutor):
        self.executor = executor

    @property
    def name(self) -> str:
        return "trade_execute"

    @property
    def description(self) -> str:
        return "Execute the exact immutable broker-verified preview through policy, user approval and effects journal. Open/modify/cancel/close use distinct approved intents. Interrupted effects are never blindly resent."

    @property
    def parameters(self) -> dict[str, Any]:
        return ExecuteRequest.model_json_schema()

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.config.integrations.metaapi is not None

    @classmethod
    def create(cls, ctx: ToolContext) -> TradeExecuteTool:
        connection = ctx.config.integrations.metaapi
        assert connection is not None
        return cls(TradeExecutor(TradeProposals(MetaApiClient(connection))))

    def action_parameters(self, params: dict[str, Any]) -> dict[str, Any]:
        request = ExecuteRequest.model_validate(params)
        return self.executor.proposals.require_preview(request.preview_id,principal()).material_action()

    async def execute(self, **kwargs: Any) -> str:
        request = ExecuteRequest.model_validate(kwargs)
        return json.dumps(await self.executor.execute(request.preview_id,principal()))


class TradeReconcileTool(Tool):
    def __init__(self, executor: TradeExecutor):
        self.executor = executor

    @property
    def name(self) -> str:
        return "trade_reconcile"

    @property
    def description(self) -> str:
        return "Reconcile an uncertain external effect against MetaApi orders/positions/history using its client identity. Never sends another trade. Ambiguity remains explicit."

    @property
    def parameters(self) -> dict[str, Any]:
        return ReconcileRequest.model_json_schema()

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.config.integrations.metaapi is not None

    @classmethod
    def create(cls, ctx: ToolContext) -> TradeReconcileTool:
        return cls(TradeExecuteTool.create(ctx).executor)

    async def execute(self, **kwargs: Any) -> str:
        request = ReconcileRequest.model_validate(kwargs)
        return json.dumps(await self.executor.reconcile(request.effect_id,principal()))
