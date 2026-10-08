"""Approved effects, no blind replay, and conservative provider reconciliation."""
from __future__ import annotations

import hashlib
from datetime import datetime, timedelta, timezone
from typing import Literal

from loguru import logger
from pydantic import Field, JsonValue

from nanobot.agent.tools.context import current_request_context
from nanobot.market.provider import ProviderUnavailableError
from nanobot.security.actions import (
    ActionStore,
    Effect,
    EffectOwner,
    current_authorized_action,
    now_ms,
)
from nanobot.session.records import RecordStore, RuntimeRecord
from nanobot.trading.delegation import MandateAuthority
from nanobot.trading.metaapi import ProviderRejectedError
from nanobot.trading.proposals import TradePreview, TradeProposals
from nanobot.trading.retcodes import ProviderDiagnostic, diagnostic_result, trade_outcome
from nanobot.trading.sdk_bridge import SDKUnavailableError


class TradeJournalEntry(RuntimeRecord):
    proposal_id: str
    responsibility_id: str | None = None
    preview_id: str | None = None
    approval_id: str | None = None
    effect_id: str | None = None
    kind: str
    provider_reference: str | None = None
    evidence_refs: list[str] = Field(default_factory=list)
    mandate_id: str | None = None
    goal_id: str | None = None
    plan_id: str | None = None
    risk_reservation_id: str | None = None
    autonomous: bool = False
    plan_version: int | None = None
    mission_pnl: str | None = None
    risk_assessment: dict[str, JsonValue] = Field(default_factory=dict)
    review_decision: str | None = None
    review_source: str | None = None
    mission_budget_before: str | None = None
    mission_budget_after: str | None = None
    account_budget_before: str | None = None
    account_budget_after: str | None = None


def current_effect_owner() -> EffectOwner | None:
    request = current_request_context()
    if not request:
        raise PermissionError("Execution requires a gateway request")
    if request.responsibility_scope.closed:
        raise PermissionError("Execution scope is closed")
    execution = next(iter(request.responsibility_scope.executions.values()),None)
    if execution is None:
        return None
    execution.store.assert_owner(execution.claim)
    claim = execution.claim
    return EffectOwner(workspace=str(execution.store.workspace),responsibility_id=claim.responsibility_id,
                       wake_id=claim.wake_id,generation=claim.generation,token=claim.token)


class TradeExecutor:
    def __init__(self, proposals: TradeProposals, effects: ActionStore | None = None,
                 journal: RecordStore[TradeJournalEntry] | None = None, *, live_enabled: bool = False):
        self.proposals = proposals
        self.effects = effects or ActionStore()
        self.journal = journal or RecordStore("trade_journal",TradeJournalEntry,self.effects)
        self.authority = MandateAuthority(proposals,live_enabled=live_enabled)

    def record(self, preview: TradePreview, kind: str, effect: Effect | None = None) -> None:
        logger.info("Trading transition kind={} proposal={} preview={} effect={} responsibility={}",
                    kind, preview.proposal_id, preview.id, effect.id if effect else "none", preview.responsibility_id)
        identity = f"{preview.id}:{kind}:{effect.generation if effect else 0}"
        entry_id = "journal_" + hashlib.sha256(identity.encode()).hexdigest()
        try:
            self.journal.get(entry_id)
            return
        except ValueError:
            pass
        mandate = self.authority.missions.mandates.get(preview.mandate_id) if preview.mandate_id else None
        reservation = self.authority.missions.reservations.get(effect.reservation_id) if effect and effect.reservation_id else None
        self.journal.create(TradeJournalEntry(id=entry_id,proposal_id=preview.proposal_id,
            responsibility_id=preview.responsibility_id,preview_id=preview.id,
            approval_id=effect.approval_id if effect else None, effect_id=effect.id if effect else None,
            kind=kind,provider_reference=effect.provider_reference if effect else None,
            mandate_id=preview.mandate_id,plan_id=preview.plan_id,
            goal_id=self.authority.missions.mandates.get(preview.mandate_id).goal_id if preview.mandate_id else None,
            risk_reservation_id=effect.reservation_id if effect else None,autonomous=bool(effect and effect.mandate_id),
            plan_version=self.authority.missions.plans.get(preview.plan_id).plan_version if preview.plan_id else None,
            mission_pnl=str(mandate.realized_pnl+mandate.unrealized_pnl) if mandate else None,
            risk_assessment=reservation.assessment if reservation else {},
            review_decision=reservation.review_decision if reservation else None,
            review_source=reservation.review_source if reservation else None,
            mission_budget_before=str(reservation.mission_budget_before) if reservation and reservation.mission_budget_before is not None else None,
            mission_budget_after=str(reservation.mission_budget_after) if reservation and reservation.mission_budget_after is not None else None,
            account_budget_before=str(reservation.account_budget_before) if reservation and reservation.account_budget_before is not None else None,
            account_budget_after=str(reservation.account_budget_after) if reservation and reservation.account_budget_after is not None else None))

    @staticmethod
    def public_effect(effect: Effect) -> dict[str, JsonValue]:
        return {"effect_id": effect.id,"state":effect.state,"provider_reference":effect.provider_reference,
                "result":effect.result}

    def _update_proposal(self, preview: TradePreview, effect: Effect) -> None:
        proposal = self.proposals.proposals.get(preview.proposal_id)
        proposal.effect_id = effect.id
        proposal.status = "EXECUTED" if effect.state == "SUCCEEDED" else (
            "FAILED" if effect.state == "FAILED" else "UNCERTAIN")
        self.proposals.proposals.save(proposal)

    async def execute(self, preview_id: str, principal: str) -> dict[str, JsonValue]:
        preview = self.proposals.require_preview(preview_id,principal)
        authorization = current_authorized_action()
        if (authorization is None or authorization.action.tool != "trade_execute"
                or authorization.action.parameters != preview.material_action()):
            raise PermissionError("Trade execution must pass through gateway policy")
        effect = self.effects.propose_effect(authorization.action,preview.effect_key)
        if effect.state != "PROPOSED":
            return self.public_effect(effect)
        if now_ms() >= preview.expires_at:
            raise ValueError("Trade preview expired; new preview and approval required")
        await self.proposals.validate_current(preview.intent,preview.broker_symbol,mandate_id=preview.mandate_id)
        self.proposals.require_preview(preview_id,principal)  # No replaced preview during remote validation.
        owner = current_effect_owner()
        delegated = await self.authority.evaluate(authorization.action) if preview.mandate_id else None
        if delegated is not None:
            reviewed = authorization.delegation
            delegated = delegated.model_copy(update={"review_decision":reviewed.review_decision if reviewed else "ASK_USER",
                "review_source":reviewed.review_source if reviewed else "user",
                "review_reason":reviewed.review_reason if reviewed else "Exact per-action user approval after escalation"})
        effect = self.effects.start_effect(effect.id,approval_id=authorization.approval_id,owner=owner,delegation=delegated)
        self.record(preview,"STARTED",effect)
        state: Literal["SUCCEEDED","FAILED","UNCERTAIN"] = "UNCERTAIN"
        result: JsonValue = None
        reference: str | None = None
        try:
            if preview.mandate_id and self.authority.missions.mandates.get(preview.mandate_id).envelope.mode == "SIMULATION":
                from nanobot.trading.simulation import MissionSimulation
                response = await MissionSimulation(self.authority.missions,self.authority.missions.mandates.get(preview.mandate_id)).execute(preview,effect)
            else:
                response = await self.proposals.client.mutate(preview.broker_request, effect=effect, journal=self.effects)
            reference = response.order_id or response.position_id
            result = response.model_dump(mode="json")
            state = trade_outcome(response.string_code, response.numeric_code)
            if state != "SUCCEEDED":
                result.update(diagnostic_result(ProviderDiagnostic(kind="TradeResponse",
                    string_code=response.string_code, numeric_code=response.numeric_code)))
        except (ProviderRejectedError, SDKUnavailableError) as exc:
            diagnostic = exc.provider_error
            state = (trade_outcome(diagnostic.string_code, diagnostic.numeric_code, kind=diagnostic.kind)
                     if diagnostic else ("FAILED" if isinstance(exc, ProviderRejectedError) else "UNCERTAIN"))
            # Unavailable transport/synchronization never proves non-execution.
            if isinstance(exc, SDKUnavailableError):
                state = "UNCERTAIN"
            result = {"message": "Provider rejected the action" if state == "FAILED" else "Outcome uncertain; reconcile before any retry"}
            if diagnostic:
                result.update(diagnostic_result(diagnostic))
                logger.warning("Trade response effect={} kind={} code={}/{} state={}",
                               effect.id, diagnostic.kind, diagnostic.string_code, diagnostic.numeric_code, state)
        except ProviderUnavailableError:
            result = {"message":"Outcome uncertain; reconcile before any retry"}
        except BaseException:
            # Cancellation saves uncertainty where possible; process death is recovered on startup.
            self.effects.finish_effect(effect,state="UNCERTAIN")
            raise
        finished = self.effects.finish_effect(effect,state=state,result=result,provider_reference=reference)
        with self.effects.owner_scope(finished.owner):
            self.record(preview,state,finished)
            self._update_proposal(preview,finished)
        return self.public_effect(finished)

    async def reconcile(self, effect_id: str, principal: str) -> dict[str, JsonValue]:
        effect = self.effects.get_effect(effect_id)
        if effect.action.principal != principal:
            raise PermissionError("Effect belongs to another conversation")
        if effect.action.parameters.get("account_id") != self.proposals.client.connection.account_id:
            raise PermissionError("Effect belongs to another account")
        if effect.state in {"SUCCEEDED","FAILED"}:
            return self.public_effect(effect)
        if effect.state == "STARTED":
            # Do not steal a live request. Gateway-exclusive recovery invalidates it.
            raise ValueError("An in-flight request must finish or undergo gateway recovery first")
        preview_id = effect.action.parameters.get("preview_id")
        if not isinstance(preview_id,str):
            raise ValueError("Effect has no immutable preview reference")
        preview = self.proposals.previews.get(preview_id)
        claimed = self.effects.claim_reconciliation(effect_id,owner=current_effect_owner())
        self.record(preview,"RECONCILING",claimed)
        if preview.mandate_id:
            mandate = self.authority.missions.mandates.get(preview.mandate_id)
            if mandate.envelope.mode == "SIMULATION":
                from nanobot.trading.simulation import MissionSimulation
                receipt = MissionSimulation(self.authority.missions,mandate).get().receipts.get(effect.id)
                finished = self.effects.finish_effect(claimed,state="SUCCEEDED" if receipt else "UNCERTAIN",
                    result=receipt.model_dump(mode="json") if receipt else {"message":"No exact simulation receipt; outcome remains uncertain"},
                    provider_reference=(receipt.position_id or receipt.order_id) if receipt else None)
                with self.effects.owner_scope(finished.owner):
                    self.record(preview,finished.state,finished)
                    self._update_proposal(preview,finished)
                return self.public_effect(finished)
        state: Literal["SUCCEEDED","FAILED","UNCERTAIN"] = "UNCERTAIN"
        reference: str | None = None
        try:
            positions = await self.proposals.client.items("positions")
            orders = await self.proposals.client.items("orders")
            start = datetime.fromtimestamp(effect.created_at/1000,timezone.utc) - timedelta(minutes=5)
            end = datetime.now(timezone.utc) + timedelta(minutes=1)
            history = await self.proposals.client.history_orders(start.isoformat(),end.isoformat())
            client_id = preview.broker_request.get("clientId")
            expected_side = "BUY" if preview.intent.side == "buy" else "SELL"
            candidates = [*positions, *orders, *[item for item in history
                          if item.state in {"ORDER_STATE_FILLED", "ORDER_STATE_PARTIAL"}]]
            matches = {item.id:item for item in candidates
                       if item.client_id == client_id and item.symbol == preview.broker_symbol
                       and expected_side in item.type.split("_")
                       and (preview.intent.volume is None or item.volume == preview.intent.volume)}
            if len(matches) == 1 and preview.intent.operation == "open":
                state, reference = "SUCCEEDED", next(iter(matches))
        except (ProviderUnavailableError,ProviderRejectedError):
            pass
        except BaseException:
            self.effects.finish_effect(claimed,state="UNCERTAIN")
            raise
        finished = self.effects.finish_effect(claimed,state=state,provider_reference=reference,
            result={"message":"Provider evidence matched the client identity" if state == "SUCCEEDED" else "Ambiguous provider evidence; user attention required"})
        with self.effects.owner_scope(finished.owner):
            self.record(preview,state,finished)
            self._update_proposal(preview,finished)
        return self.public_effect(finished)
