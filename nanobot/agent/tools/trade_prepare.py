"""Analysis/intent and preview are distinct from any broker mutation."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.trading.accounts import TradingAccounts
from nanobot.trading.proposals import TradeIntent, TradeProposals


class ProposalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["create", "get", "preview", "journal"]
    proposal_id: str | None = None
    intent: TradeIntent | None = None
    rationale_summary: str = ""
    evidence_refs: list[str] = []
    chart_refs: list[str] = []
    mandate_id: str | None = None
    account_id: str | None = None


class TradePrepareTool(Tool):
    def __init__(self, service: TradeProposals, accounts: TradingAccounts | None = None):
        self.service = service
        self.accounts = accounts

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
        return bool(ctx.config.integrations.broker_accounts())

    @classmethod
    def create(cls, ctx: ToolContext) -> TradePrepareTool:
        accounts = TradingAccounts(ctx.config.integrations)
        return cls(TradeProposals(accounts.client()), accounts)

    async def execute(self, **kwargs: Any) -> str:
        request = ProposalRequest.model_validate(kwargs)
        context = current_request_context()
        if not context or not context.session_key:
            raise PermissionError("Trade proposals require a conversation")
        service = self.service
        if self.accounts:
            account_id = request.account_id
            if request.proposal_id:
                proposal = self.service.proposals.get(request.proposal_id)
                self.service.require_owner(context.session_key, proposal.principal)
                if account_id is not None and account_id != proposal.account_id:
                    raise PermissionError("An existing proposal cannot switch broker accounts")
                account_id = proposal.account_id
            elif request.mandate_id:
                from nanobot.session.records import RecordStore
                from nanobot.trading.mission_models import TradingMandate
                mandate = RecordStore("trading_mandates", TradingMandate, self.service.proposals.journal).get(request.mandate_id)
                self.service.require_owner(context.session_key, mandate.principal)
                if account_id is not None and account_id != mandate.envelope.account_id:
                    raise PermissionError("A mandate cannot switch broker accounts")
                account_id = mandate.envelope.account_id
            service = TradeProposals(self.accounts.client(account_id, principal=context.session_key),
                                     mappings=self.service.mappings, proposals=self.service.proposals,
                                     previews=self.service.previews)
        if request.operation == "create":
            if not request.intent:
                raise ValueError("Structured trade intent is required")
            record = service.create(context.session_key, request.intent,
                responsibility_id=next(iter(context.responsibility_scope.executions),None),
                rationale=request.rationale_summary,evidence=request.evidence_refs,charts=request.chart_refs,
                mandate_id=request.mandate_id)
            return record.model_dump_json()
        if not request.proposal_id:
            raise ValueError("Proposal id is required")
        if request.operation == "preview":
            return (await service.preview(request.proposal_id,context.session_key)).model_dump_json()
        proposal = service.proposals.get(request.proposal_id)
        service.require_owner(context.session_key,proposal.principal)
        if request.operation == "journal":
            import json

            from nanobot.session.records import RecordStore
            from nanobot.trading.execution import TradeJournalEntry
            entries = RecordStore("trade_journal", TradeJournalEntry, self.service.proposals.journal).list()
            approvals = self.service.proposals.journal.approvals_for_proposal(proposal.id)
            return json.dumps({"proposal": proposal.model_dump(mode="json"),
                "entries": [entry.model_dump(mode="json") for entry in entries if entry.proposal_id == proposal.id],
                "approvals": [approval.model_dump(mode="json") for approval in approvals]})
        return proposal.model_dump_json()
