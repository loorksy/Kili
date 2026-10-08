"""Natural-language goals become structured proposals, never financial authority."""
from __future__ import annotations

import json
import uuid
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.trading.accounts import TradingAccounts
from nanobot.trading.metaapi import MetaApiClient
from nanobot.trading.mission_models import MandateEnvelope, TradingGoal, TradingPlan
from nanobot.trading.missions import TradingMissions


class GoalInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    objective: str = Field(min_length=1,max_length=2000)
    objective_type: Literal["profit","supervision"] = "profit"
    target_profit: Decimal | None = Field(default=None,gt=0,allow_inf_nan=False)
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    start_at: int
    end_at: int
    allowed_instruments: list[str] = Field(default_factory=list,max_length=50)
    capital_preference: Decimal | None = Field(default=None,gt=0,allow_inf_nan=False)


class PlanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    market_scope: list[str] = Field(max_length=50)
    monitoring_summary: str = Field(max_length=2000)
    execution_summary: str = Field(max_length=2000)
    risk_proposal_summary: str = Field(max_length=2000)
    reevaluation_summary: str = Field(max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list,max_length=30)
    chart_refs: list[str] = Field(default_factory=list,max_length=10)


class MissionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["create_goal","create_plan","propose","activate","get","list","reduce","pause","cancel","resume","emergency_stop"]
    goal: GoalInput | None = None
    plan: PlanInput | None = None
    envelope: MandateEnvelope | None = None
    responsibility_id: str | None = None
    goal_id: str | None = None
    plan_id: str | None = None
    mandate_id: str | None = None
    account_id: str | None = None


class TradingMissionTool(Tool):
    def __init__(self, ctx: ToolContext):
        self.ctx = ctx
        self.accounts = TradingAccounts(ctx.config.integrations)
        connection = ctx.config.integrations.metaapi
        if connection is None:
            raise ValueError("Configure an account reference before creating a trading mission")
        self.service = TradingMissions(MetaApiClient(connection),live_enabled=ctx.config.integrations.autonomous_trading_enabled)

    @property
    def name(self) -> str:
        return "trading_mission"

    @property
    def description(self) -> str:
        return ("Create durable Trading Goal and immutable Plan versions, inspect/propose a bounded Trading Mandate, "
            "and activate only after exact user approval. A desired profit is aspirational, never a guarantee or authority. "
            "Resolve account, maximum loss, duration and breach/target/expiry/emergency behavior explicitly. "
            "Capital is accounting allocation, not a segregated balance. Inspect account and market/chart evidence before planning. "
            "Plans may adapt or choose WAIT without raising limits. reduce only tightens existing authority. "
            "Supervision binds one exact protected position and cannot open unrelated entries. "
            "SIMULATION never calls broker mutations; LIVE also requires the operator's enabled setting. "
            "resume/emergency_stop are user-only interactions. Use existing goal scheduling/watchers; no continuous inference.")

    @property
    def parameters(self) -> dict[str,Any]:
        return MissionRequest.model_json_schema()

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return bool(ctx.config.integrations.broker_accounts())

    @classmethod
    def create(cls, ctx: ToolContext) -> TradingMissionTool:
        return cls(ctx)

    async def execute(self, **kwargs: Any) -> str:
        request = MissionRequest.model_validate(kwargs)
        context = current_request_context()
        if context is None or context.session_key is None:
            raise PermissionError("Trading missions require a conversation")
        principal = context.session_key
        account_id = request.account_id
        if request.mandate_id:
            bound = self.service.mandates.get(request.mandate_id)
            self.service.owner(principal, bound)
            bound_account = bound.envelope.account_id
        elif request.goal_id or request.plan_id:
            goal_id = request.goal_id or self.service.plans.get(request.plan_id or "").goal_id
            goal = self.service.goals.get(goal_id)
            self.service.owner(principal, goal)
            bound_account = goal.account_id
        else:
            bound_account = None
        if bound_account is not None:
            if account_id is not None and account_id != bound_account:
                raise PermissionError("An existing trading mission cannot switch broker accounts")
            account_id = bound_account
        connection = self.accounts.connection(account_id, principal=principal)
        service = self.service if connection.account_id == self.service.client.connection.account_id else TradingMissions(
            MetaApiClient(connection), self.service.journal, live_enabled=self.service.live_enabled)
        if request.operation == "create_goal":
            if request.goal is None or self.ctx.sessions is None:
                raise ValueError("Resolved goal and durable session infrastructure are required")
            identity = request.responsibility_id or next(iter(context.responsibility_scope.executions),None)
            if identity is None:
                raise ValueError("Create/bind a persistent responsibility using existing goal tools first")
            responsibility = self.ctx.sessions.responsibilities.get(identity)
            if responsibility.session_key != principal:
                raise PermissionError("Responsibility belongs to another conversation; relink first")
            goal = TradingGoal.model_validate({**request.goal.model_dump(),"id":"trading_goal_"+uuid.uuid4().hex,
                "principal":principal,"responsibility_id":identity,"account_id":service.client.connection.account_id})
            return service.create_goal(goal).model_dump_json()
        if request.operation == "create_plan":
            if request.goal_id is None or request.plan is None:
                raise ValueError("Goal id and final structured plan are required")
            version = max((p.plan_version for p in service.plans.list() if p.goal_id == request.goal_id),default=0)+1
            plan = TradingPlan.model_validate({**request.plan.model_dump(),"id":"trading_plan_"+uuid.uuid4().hex,
                "goal_id":request.goal_id,"plan_version":version})
            return service.create_plan(principal,plan).model_dump_json()
        if request.operation == "propose":
            if request.goal_id is None or request.plan_id is None or request.envelope is None:
                raise ValueError("Goal, inspected plan and explicit bounded envelope are required")
            mandate,approval = await service.propose(principal,request.goal_id,request.plan_id,request.envelope)
            return ("Profit target is not guaranteed; allocated capital is not physically segregated.\n"
                "```trading_mission\n"+json.dumps({"mandate_id":mandate.id,"session_key":principal})+"\n```\n"
                "```action_approval\n"+json.dumps({"approval_id":approval.id,"session_key":principal})+"\n```")
        if request.operation == "list":
            return json.dumps([m.model_dump(mode="json") for m in service.mandates.list() if m.principal == principal])
        if request.mandate_id is None:
            raise ValueError("Mandate id is required")
        mandate = service.mandates.get(request.mandate_id)
        service.owner(principal,mandate)
        if request.operation == "activate":
            mandate = await service.activate(principal,mandate.id)
        elif request.operation == "reduce":
            if request.envelope is None:
                raise ValueError("Exact reduced envelope required")
            mandate = service.reduce(principal,mandate.id,request.envelope)
        elif request.operation in {"pause","cancel","resume","emergency_stop"}:
            mandate = service.control(principal,mandate.id,request.operation,
                user=context.attributes.get("mission_user_interaction") is True)
        return mandate.model_dump_json()
