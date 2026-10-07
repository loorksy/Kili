"""Analysis/intent and preview are distinct from any broker mutation."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.trading.metaapi import MetaApiClient
from nanobot.trading.proposals import TradeIntent, TradeProposals


class ProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["create", "get", "preview"]
    proposal_id: str | None = None
    intent: TradeIntent | None = None
    rationale_summary: str = ""
    evidence_refs: list[str] = []
    chart_refs: list[str] = []


class TradePrepareTool(Tool):
    def __init__(self, service: TradeProposals):
        self.service = service

    @property
    def name(self) -> str:
        return "trade_prepare"

    @property
    def description(self) -> str:
        return "Create/read a durable trade proposal or generate a broker-verified preview. No broker mutation. Exact instrument mapping must first be verified by the user in Settings."

    @property
    def parameters(self) -> dict[str, Any]:
        return ProposalRequest.model_json_schema()

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.config.integrations.metaapi is not None

    @classmethod
    def create(cls, ctx: ToolContext) -> TradePrepareTool:
        connection = ctx.config.integrations.metaapi
        assert connection is not None
        return cls(TradeProposals(MetaApiClient(connection)))

    async def execute(self, **kwargs: Any) -> str:
        request = ProposalRequest.model_validate(kwargs)
        context = current_request_context()
        if not context or not context.session_key:
            raise PermissionError("Trade proposals require a conversation")
        if request.operation == "create":
            if not request.intent:
                raise ValueError("Structured trade intent is required")
            record = self.service.create(context.session_key, request.intent,
                responsibility_id=next(iter(context.responsibility_scope.executions),None),
                rationale=request.rationale_summary,evidence=request.evidence_refs,charts=request.chart_refs)
            return record.model_dump_json()
        if not request.proposal_id:
            raise ValueError("Proposal id is required")
        if request.operation == "preview":
            return (await self.service.preview(request.proposal_id,context.session_key)).model_dump_json()
        proposal = self.service.proposals.get(request.proposal_id)
        self.service.require_owner(context.session_key,proposal.principal)
        return proposal.model_dump_json()
