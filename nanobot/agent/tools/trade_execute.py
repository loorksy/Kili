"""Financial mutations require canonical preview policy, approval and effect ownership."""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.security.actions import Action, ActionAuthority, DelegatedAuthorization
from nanobot.trading.accounts import TradingAccounts
from nanobot.trading.execution import TradeExecutor
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

    def __init__(self, executor: TradeExecutor, accounts: TradingAccounts | None = None):
        self.executor = executor
        self.accounts = accounts

    def executor_for(self, preview_id: str, owner: str) -> TradeExecutor:
        preview = self.executor.proposals.previews.get(preview_id)
        self.executor.proposals.require_owner(owner, preview.principal)
        if self.accounts is None:
            return self.executor
        proposals = TradeProposals(self.accounts.client(preview.account_id),
            mappings=self.executor.proposals.mappings, proposals=self.executor.proposals.proposals,
            previews=self.executor.proposals.previews)
        return TradeExecutor(proposals, self.executor.effects, self.executor.journal,
                             live_enabled=self.executor.authority.missions.live_enabled)

    async def evaluate(self, action: Action) -> DelegatedAuthorization | None:
        identity = action.parameters.get("preview_id")
        if not isinstance(identity, str):
            raise ValueError("Exact preview ID is required")
        return await self.executor_for(identity, action.principal).authority.evaluate(action)

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
        return bool(ctx.config.integrations.broker_accounts())

    @classmethod
    def create(cls, ctx: ToolContext) -> TradeExecuteTool:
        accounts = TradingAccounts(ctx.config.integrations)
        return cls(TradeExecutor(TradeProposals(accounts.client()),
            live_enabled=ctx.config.integrations.autonomous_trading_enabled), accounts)

    def action_parameters(self, params: dict[str, Any]) -> dict[str, Any]:
        request = ExecuteRequest.model_validate(params)
        owner = principal()
        return self.executor_for(request.preview_id, owner).proposals.require_preview(request.preview_id, owner).material_action()

    def action_authority(self) -> ActionAuthority:
        return self if self.accounts else self.executor.authority

    async def execute(self, **kwargs: Any) -> str:
        request = ExecuteRequest.model_validate(kwargs)
        owner = principal()
        return json.dumps(await self.executor_for(request.preview_id, owner).execute(request.preview_id, owner))


class TradeReconcileTool(Tool):
    def __init__(self, executor: TradeExecutor, accounts: TradingAccounts | None = None):
        self.executor = executor
        self.accounts = accounts

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
        return bool(ctx.config.integrations.broker_accounts())

    @classmethod
    def create(cls, ctx: ToolContext) -> TradeReconcileTool:
        tool = TradeExecuteTool.create(ctx)
        return cls(tool.executor, tool.accounts)

    async def execute(self, **kwargs: Any) -> str:
        request = ReconcileRequest.model_validate(kwargs)
        owner = principal()
        executor = self.executor
        if self.accounts:
            effect = executor.effects.get_effect(request.effect_id)
            if effect.action.principal != owner:
                raise PermissionError("Effect belongs to another conversation")
            account_id = effect.action.parameters.get("account_id")
            if not isinstance(account_id, str):
                raise ValueError("Effect has no broker account binding")
            proposals = TradeProposals(self.accounts.client(account_id), mappings=executor.proposals.mappings,
                proposals=executor.proposals.proposals, previews=executor.proposals.previews)
            executor = TradeExecutor(proposals, executor.effects, executor.journal,
                                     live_enabled=executor.authority.missions.live_enabled)
        return json.dumps(await executor.reconcile(request.effect_id, owner))
