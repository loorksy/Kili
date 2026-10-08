"""Authenticated lot editing creates a fresh preview and revokes old authority."""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from nanobot.config.schema import Config
from nanobot.security.actions import Action, ActionStore
from nanobot.session.records import RecordStore
from nanobot.trading.accounts import TradingAccounts
from nanobot.trading.proposals import TradeIntent, TradePreview, TradeProposals


class LotApprovalEdit(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    session_key: str
    approval_id: str = Field(pattern=r"^approval_[a-f0-9]{32}$")
    volume: Decimal = Field(gt=0, max_digits=30, decimal_places=18)


async def edit_approval(config: Config, principal: str, approval_id: str, volume: Decimal,
                        journal: ActionStore | None = None) -> dict[str, object]:
    journal = journal or ActionStore()
    record = journal.read_approval(approval_id, principal)
    if record["status"] != "PENDING":
        raise ValueError("Only a pending approval can be edited")
    parameters = record["action"]
    if not isinstance(parameters, dict):
        raise ValueError("This approval is not an editable trade preview")
    identity = parameters.get("preview_id")
    if not isinstance(identity, str):
        raise ValueError("This approval is not an editable trade preview")
    old = RecordStore("trade_previews", TradePreview, journal).get(identity)
    TradeProposals.require_owner(principal, old.principal)
    if old.intent.operation not in {"open", "close_position"}:
        raise ValueError("This operation has no editable lot size")
    if journal.find_effect(old.effect_key) is not None:
        raise PermissionError("A started or reconciled action cannot be edited")
    from nanobot.trading.proposals import TradeProposal
    service = TradeProposals(TradingAccounts(config.tools.integrations, journal).client(old.account_id),
        proposals=RecordStore("trade_proposals", TradeProposal, journal),
        previews=RecordStore("trade_previews", TradePreview, journal))
    original = service.proposals.get(old.proposal_id)
    intent = TradeIntent.model_validate({**old.intent.model_dump(), "volume": volume})
    proposal = service.create(principal, intent, responsibility_id=original.responsibility_id,
        rationale=original.rationale_summary, evidence=original.evidence_refs, charts=original.chart_refs,
        mandate_id=original.mandate_id)
    preview = await service.preview(proposal.id, principal)
    # Revalidate pending state after awaited broker reads. A concurrent user
    # approval wins the race; editing never revokes consumed/executing authority.
    action = Action(tool="trade_execute", action_class="consequential", principal=principal,
        responsibility_id=original.responsibility_id, parameters=preview.material_action())
    fresh = journal.replace_pending(str(record["id"]), principal=principal, action=action)
    return {"id": fresh.id, "status": fresh.status, "action": fresh.action.parameters}
