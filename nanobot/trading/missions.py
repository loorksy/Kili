"""Durable user delegation using the existing protected journal and responsibilities."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import uuid
from decimal import Decimal
from typing import TypeVar

from pydantic import JsonValue

from nanobot.security.actions import (
    Action,
    ActionStore,
    Approval,
    DelegatedAuthorization,
    Effect,
    EffectOwner,
    current_authorized_action,
    now_ms,
)
from nanobot.session.records import RecordStore, RuntimeRecord
from nanobot.trading.metaapi import MetaApiClient
from nanobot.trading.mission_models import (
    AccountGuardrails,
    AccountObservation,
    MandateEnvelope,
    RiskAssessment,
    RiskReservation,
    TradingGoal,
    TradingMandate,
    TradingPlan,
)

_T = TypeVar("_T", bound=RuntimeRecord)


def read_record(db: sqlite3.Connection, namespace: str, identity: str, model: type[_T]) -> _T:
    row = db.execute("SELECT record FROM records WHERE namespace=? AND id=?",(namespace,identity)).fetchone()
    if row is None:
        raise ValueError("Unknown runtime record")
    return model.model_validate_json(row[0])


def write_record(db: sqlite3.Connection, namespace: str, record: RuntimeRecord) -> None:
    record.revision += 1
    record.updated_at = now_ms()
    cursor = db.execute("UPDATE records SET revision=?,record=? WHERE namespace=? AND id=? AND revision=?",
        (record.revision,record.model_dump_json(),namespace,record.id,record.revision-1))
    if cursor.rowcount != 1:
        raise ValueError("Runtime record revision conflict")


def insert_record(db: sqlite3.Connection, namespace: str, record: RuntimeRecord) -> None:
    db.execute("INSERT INTO records VALUES (?,?,?,?)",(namespace,record.id,record.revision,record.model_dump_json()))


def reject_mandate_approval(db: sqlite3.Connection, approval: Approval) -> None:
    identity = approval.action.parameters.get("mandate_id")
    if not isinstance(identity,str):
        return
    if db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='records'").fetchone() is None:
        return
    try:
        mandate = read_record(db,"trading_mandates",identity,TradingMandate)
    except ValueError:
        return  # Denial still succeeds if a draft was already removed.
    if (mandate.status == "AWAITING_MANDATE_APPROVAL" and mandate.principal == approval.resolved_by
            and TradingMissions.approval_action(mandate).fingerprint == approval.fingerprint):
        mandate.status = "CANCELLED"
        write_record(db,"trading_mandates",mandate)


class TradingMissions:
    def __init__(self, client: MetaApiClient, journal: ActionStore | None = None, *, live_enabled: bool = False):
        self.client, self.journal, self.live_enabled = client, journal or ActionStore(), live_enabled
        self.goals = RecordStore("trading_goals",TradingGoal,self.journal)
        self.plans = RecordStore("trading_plans",TradingPlan,self.journal)
        self.mandates = RecordStore("trading_mandates",TradingMandate,self.journal)
        self.guardrails = RecordStore("account_guardrails",AccountGuardrails,self.journal)
        self.reservations = RecordStore("risk_reservations",RiskReservation,self.journal)

    @staticmethod
    def owner(principal: str, record: TradingGoal | TradingMandate) -> None:
        if record.principal != principal:
            raise PermissionError("Trading mission belongs to another conversation")

    def audit(self, mandate: TradingMandate, kind: str) -> None:
        from nanobot.trading.execution import TradeJournalEntry
        entries = RecordStore("trade_journal",TradeJournalEntry,self.journal)
        identity = "mission_journal_"+hashlib.sha256(f"{mandate.id}:{mandate.revision}:{kind}".encode()).hexdigest()
        try:
            entries.get(identity)
            return
        except ValueError:
            pass
        plan = self.plans.get(mandate.plan_id)
        entries.create(TradeJournalEntry(id=identity,proposal_id="",responsibility_id=mandate.responsibility_id,
            approval_id=mandate.approval_id,kind=kind,mandate_id=mandate.id,goal_id=mandate.goal_id,
            plan_id=plan.id,plan_version=plan.plan_version,
            mission_pnl=str(mandate.realized_pnl+mandate.unrealized_pnl),evidence_refs=plan.evidence_refs))

    async def observe(self, *, simulation: bool = False) -> AccountObservation:
        connected = await self.client.connection_state()
        if (connected.id != self.client.connection.account_id or connected.connection_status != "CONNECTED"
                or connected.region != self.client.connection.region):
            raise ValueError("Authenticated account connection is unavailable")
        account = await self.client.account()
        positions = await self.client.items("positions")
        orders = await self.client.items("orders")
        observed = AccountObservation(fetched_at=now_ms(),account=account,positions=positions,orders=orders)
        if simulation:
            from nanobot.trading.mission_observation import simulated_account
            observed,_,_ = await simulated_account(self,observed)
        return observed

    def create_goal(self, goal: TradingGoal) -> TradingGoal:
        if goal.account_id != self.client.connection.account_id:
            raise ValueError("Goal account differs from configured account")
        return self.goals.create(goal)

    def create_plan(self, principal: str, plan: TradingPlan) -> TradingPlan:
        goal = self.goals.get(plan.goal_id)
        self.owner(principal,goal)
        with RecordStore.execution_write(), self.journal.transaction() as db:
            existing = [TradingPlan.model_validate_json(row[0]) for row in db.execute("SELECT record FROM records WHERE namespace='trading_plans'")]
            expected = max((p.plan_version for p in existing if p.goal_id == goal.id),default=0)+1
            if plan.plan_version != expected:
                raise ValueError("Plan versions are immutable and sequential")
            insert_record(db,"trading_plans",plan)
            for row in db.execute("SELECT record FROM records WHERE namespace='trading_mandates'").fetchall():
                mandate = TradingMandate.model_validate_json(row[0])
                if mandate.goal_id == goal.id and mandate.approved_envelope is not None and mandate.status in {"ACTIVE","PAUSED","NEEDS_ATTENTION"}:
                    mandate.plan_id = plan.id
                    write_record(db,"trading_mandates",mandate)
        return plan

    @staticmethod
    def approval_action(mandate: TradingMandate) -> Action:
        return Action(tool="trading_mandate",action_class="consequential",principal=mandate.principal,
            responsibility_id=mandate.responsibility_id,policy_version=mandate.policy_version,
            parameters={"mandate_id":mandate.id,"goal_id":mandate.goal_id,"plan_id":mandate.plan_id,
                "envelope":mandate.envelope.model_dump(mode="json"),"scope_fingerprint":mandate.scope_fingerprint,
                "supervision_baseline": [p.model_dump(mode="json") for p in mandate.baseline.positions
                    if p.id == mandate.envelope.supervision_position_id],
                "profit_target_is_aspirational":True,"capital_is_accounting_allocation":True})

    async def propose(self, principal: str, goal_id: str, plan_id: str, envelope: MandateEnvelope) -> tuple[TradingMandate, Approval]:
        goal, plan = self.goals.get(goal_id), self.plans.get(plan_id)
        self.owner(principal,goal)
        if plan.goal_id != goal.id or not plan.evidence_refs:
            raise ValueError("A goal-linked plan with evidence references is required")
        if (envelope.account_id != goal.account_id or envelope.currency != goal.currency
                or envelope.start_at < goal.start_at or envelope.expires_at > goal.end_at
                or (goal.allowed_instruments and not set(envelope.allowed_instruments) <= set(goal.allowed_instruments))):
            raise ValueError("Mandate differs from the resolved goal/account/time scope")
        baseline = await self.observe(simulation=envelope.mode == "SIMULATION")
        if baseline.account.currency != envelope.currency or not baseline.account.trade_allowed:
            raise ValueError("Mandate account currency/permission is not verified")
        if envelope.allocated_capital > baseline.account.equity:
            raise ValueError("Accounting allocation exceeds current equity")
        if envelope.supervision_position_id:
            position = next((p for p in baseline.positions if p.id == envelope.supervision_position_id),None)
            if position is None or position.stop_loss is None or position.profit is None:
                raise ValueError("Supervision requires an exact protected position with authoritative P&L")
        record = self.mandates.create(TradingMandate(id="mandate_"+uuid.uuid4().hex,
            goal_id=goal_id,plan_id=plan_id,principal=principal,responsibility_id=goal.responsibility_id,
            envelope=envelope,scope_fingerprint=envelope.fingerprint,baseline=baseline,next_check_at=now_ms()))
        approval = self.journal.request(self.approval_action(record))
        goal.status = "AWAITING_MANDATE_APPROVAL"
        self.goals.save(goal)
        self.audit(record,"MANDATE_PROPOSED")
        return record, approval

    async def activate(self, principal: str, mandate_id: str) -> TradingMandate:
        mandate = self.mandates.get(mandate_id)
        self.owner(principal,mandate)
        if mandate.envelope.account_id != self.client.connection.account_id:
            raise PermissionError("Mandate account differs from the configured connection")
        if mandate.envelope.mode == "LIVE" and not self.live_enabled:
            raise PermissionError("Live delegated trading is disabled in operator settings")
        observed = await self.observe(simulation=mandate.envelope.mode == "SIMULATION")
        if observed.account.currency != mandate.envelope.currency or not observed.account.trade_allowed:
            raise ValueError("Account changed before activation")
        if mandate.envelope.supervision_position_id:
            original = next(p for p in mandate.baseline.positions if p.id == mandate.envelope.supervision_position_id)
            current = next((p for p in observed.positions if p.id == original.id),None)
            if current is None or (current.symbol,current.type,current.volume,current.stop_loss,current.take_profit) != (original.symbol,original.type,original.volume,original.stop_loss,original.take_profit):
                raise ValueError("Supervised position changed; propose a new exact mandate")
        action = self.approval_action(mandate)
        with RecordStore.execution_write(), self.journal.transaction() as db:
            current = read_record(db,"trading_mandates",mandate.id,TradingMandate)
            if current.revision != mandate.revision or current.status != "AWAITING_MANDATE_APPROVAL" or now_ms() >= current.envelope.expires_at:
                raise ValueError("Mandate activation is stale or expired")
            approved = next((Approval.model_validate_json(row[0]) for row in db.execute("SELECT record FROM approvals WHERE fingerprint=?",(action.fingerprint,))
                if Approval.model_validate_json(row[0]).status == "APPROVED" and Approval.model_validate_json(row[0]).expires_at > now_ms()),None)
            if approved is None:
                raise PermissionError("Exact explicit user mandate approval is required")
            active = [TradingMandate.model_validate_json(row[0]) for row in db.execute("SELECT record FROM records WHERE namespace='trading_mandates'")]
            if any(m.goal_id == current.goal_id and m.status in {"ACTIVE","PAUSED","NEEDS_ATTENTION","RISK_STOPPED"} for m in active):
                raise PermissionError("A mission already owns this goal; cancel before new authorization")
            held = {RiskReservation.model_validate_json(row[0]).mandate_id for row in db.execute(
                "SELECT record FROM records WHERE namespace='risk_reservations'")
                if RiskReservation.model_validate_json(row[0]).state != "RELEASED"}
            if any(m.envelope.account_id == current.envelope.account_id and m.envelope.mode != current.envelope.mode
                    and (m.status in {"ACTIVE","PAUSED","NEEDS_ATTENTION","RISK_STOPPED"} or m.id in held) for m in active):
                raise PermissionError("Live and simulation missions cannot share an active account risk ledger")
            try:
                guard = read_record(db,"account_guardrails",current.envelope.account_id,AccountGuardrails)
            except ValueError:
                guard = AccountGuardrails(id=current.envelope.account_id,enabled=True,max_open_risk=current.envelope.max_open_risk,
                    max_account_loss=current.envelope.max_mission_loss,baseline_equity=observed.account.equity)
                insert_record(db,"account_guardrails",guard)
            if guard.emergency_stop or not guard.enabled or sum(m.envelope.account_id == current.envelope.account_id and m.status in {"ACTIVE","PAUSED","NEEDS_ATTENTION","RISK_STOPPED"} for m in active) >= guard.max_active_mandates:
                raise PermissionError("Account guardrail blocks mandate activation")
            approved.status = "CONSUMED"
            db.execute("UPDATE approvals SET record=? WHERE id=?",(approved.model_dump_json(),approved.id))
            current.status,current.approval_id,current.approved_at,current.approved_by = "ACTIVE",approved.id,now_ms(),principal
            current.approved_envelope,current.observed = current.envelope,observed
            write_record(db,"trading_mandates",current)
            goal = read_record(db,"trading_goals",current.goal_id,TradingGoal)
            goal.status = "ACTIVE"
            write_record(db,"trading_goals",goal)
        self.audit(current,"MANDATE_ACTIVATED")
        return current

    def reduce(self, principal: str, mandate_id: str, envelope: MandateEnvelope) -> TradingMandate:
        mandate = self.mandates.get(mandate_id)
        self.owner(principal,mandate)
        if mandate.approved_envelope is None or mandate.status in {"CANCELLED","EXPIRED","COMPLETED"}:
            raise PermissionError("No active authorization to reduce")
        old, new = mandate.envelope.model_dump(), envelope.model_dump()
        money_fields = {"allocated_capital","max_mission_loss","max_daily_loss","max_drawdown","max_open_risk","max_risk_per_trade","max_margin_usage","max_notional"}
        counts = {"max_concurrent_positions","max_pending_orders","expires_at"}
        scopes = {"allowed_instruments","allowed_order_types","allowed_actions","risk_increase_permissions"}
        for field in old:
            if field in money_fields:
                if old[field] is not None and (new[field] is None or new[field] > old[field]):
                    raise PermissionError("Mandate expansion requires a new user approval")
            elif field in counts:
                if new[field] > old[field]:
                    raise PermissionError("Mandate expansion requires a new user approval")
            elif field in scopes:
                if not set(new[field]) <= set(old[field]):
                    raise PermissionError("Mandate scope expansion requires new approval")
            elif new[field] != old[field]:
                raise PermissionError("Material mandate change requires new approval")
        mandate.envelope,mandate.scope_fingerprint = envelope,envelope.fingerprint
        reduced = self.mandates.save(mandate)
        self.audit(reduced,"MANDATE_REDUCED")
        return reduced

    def control(self, principal: str, mandate_id: str, operation: str, *, user: bool) -> TradingMandate:
        mandate = self.mandates.get(mandate_id)
        self.owner(principal,mandate)
        if operation == "resume":
            if not user or mandate.status != "PAUSED" or now_ms() >= mandate.envelope.expires_at:
                raise PermissionError("Only the user can resume a valid paused mandate")
            mandate.status = "ACTIVE"
        elif operation == "pause":
            if mandate.status not in {"ACTIVE", "PAUSED", "NEEDS_ATTENTION"}:
                raise PermissionError("Terminal or unapproved mandates cannot be paused and resumed")
            if mandate.status != "NEEDS_ATTENTION":
                mandate.status = "PAUSED"
        elif operation == "cancel":
            mandate.status,mandate.finish_pending = "CANCELLED",False
        elif operation == "emergency_stop":
            if not user:
                raise PermissionError("Emergency account control is a user interaction")
            guard = self.guardrails.get(mandate.envelope.account_id)
            guard.emergency_stop = True
            self.guardrails.save(guard)
            mandate.status,mandate.finish_pending = "RISK_STOPPED",True
            mandate.finish_kind = "emergency"
        else:
            raise ValueError("Unsupported mission control")
        changed = self.mandates.save(mandate)
        self.audit(changed,"MANDATE_"+operation.upper())
        return changed

    @staticmethod
    def reserve_in_transaction(db: sqlite3.Connection, risk: RiskAssessment, effect_id: str,
                               *, operation: str, pending: bool) -> RiskReservation:
        mandate = read_record(db,"trading_mandates",risk.mandate_id,TradingMandate)
        if mandate.revision != risk.mandate_revision or now_ms()-risk.fetched_at > 30_000:
            raise PermissionError("Stale mandate/risk observation")
        envelope = mandate.envelope
        if risk.risk_increasing and (mandate.status != "ACTIVE" or not envelope.start_at <= now_ms() < envelope.expires_at):
            raise PermissionError("Mandate no longer admits risk")
        unresolved = [RiskReservation.model_validate_json(row[0]) for row in db.execute("SELECT record FROM records WHERE namespace='risk_reservations'")]
        held = [r for r in unresolved if r.account_id == risk.account_id and r.state != "RELEASED"]
        if any(r.state == "UNCERTAIN" for r in held):
            raise PermissionError("Account effect uncertainty must be reconciled first")
        # ACTIVE entries already present in the fresh broker observation are not
        # counted twice. RESERVED entries cover requests accepted but not observed.
        outstanding = [r for r in held if r.state == "RESERVED"]
        own = [r for r in outstanding if r.mandate_id == mandate.id]
        if risk.risk_increasing:
            if risk.open_risk is None or risk.account_open_risk is None:
                raise PermissionError("Cannot add risk with ambiguous exposure")
            uncertain = [Effect.model_validate_json(row[0]) for row in db.execute("SELECT record FROM effects")]
            if any(e.state in {"UNCERTAIN","RECONCILING"} and e.action.parameters.get("account_id") == risk.account_id for e in uncertain):
                raise PermissionError("Account has unresolved financial effects")
            guard = read_record(db,"account_guardrails",risk.account_id,AccountGuardrails)
            if not guard.enabled or guard.emergency_stop or guard.baseline_equity-risk.account_equity >= guard.max_account_loss:
                raise PermissionError("Global account safety guardrail reached")
            mission_risk = risk.open_risk+risk.incremental_risk+sum((r.risk for r in own),Decimal(0))
            if risk.proposed_risk > envelope.max_risk_per_trade or mission_risk > min(envelope.max_open_risk,risk.remaining_loss):
                raise PermissionError("Hard mission open/per-trade/loss budget exceeded")
            if risk.account_open_risk+risk.incremental_risk+sum((r.risk for r in outstanding),Decimal(0)) > guard.max_open_risk:
                raise PermissionError("Account risk budget already reserved by exposure/another mandate")
            if operation == "open":
                if pending and risk.order_count+sum(r.entry_kind == "pending" for r in own)+1 > envelope.max_pending_orders:
                    raise PermissionError("Pending order limit exceeded")
                if risk.position_count+risk.order_count+sum(r.entry_kind is not None for r in own)+1 > envelope.max_concurrent_positions:
                    raise PermissionError("Possible simultaneous fills exceed position limit")
            margin = risk.margin_usage+risk.proposed_margin+sum((r.margin for r in outstanding),Decimal(0))
            if margin > min(envelope.allocated_capital,envelope.max_margin_usage or envelope.allocated_capital,guard.max_margin_usage or envelope.allocated_capital):
                raise PermissionError("Margin/accounting allocation limit exceeded")
            mission_exposure = risk.mission_notional+risk.proposed_notional+sum((r.notional for r in own),Decimal(0))
            account_exposure = risk.account_notional+risk.proposed_notional+sum((r.notional for r in outstanding),Decimal(0))
            if (envelope.max_notional is not None and mission_exposure > envelope.max_notional) or (guard.max_notional is not None and account_exposure > guard.max_notional):
                raise PermissionError("Notional exposure limit exceeded")
        reservation = RiskReservation(id="risk_"+effect_id,account_id=risk.account_id,mandate_id=mandate.id,
            effect_id=effect_id,action_fingerprint=risk.fingerprint,risk=risk.incremental_risk,
            notional=risk.proposed_notional,margin=risk.proposed_margin,risk_increasing=risk.risk_increasing,
            assessment=risk.model_dump(mode="json"),
            entry_kind=("pending" if pending else "market") if operation == "open" else None)
        if risk.open_risk is not None:
            before = min(envelope.max_open_risk,risk.remaining_loss)-risk.open_risk-sum((r.risk for r in own),Decimal(0))
            reservation.mission_budget_before = before
            reservation.mission_budget_after = before-risk.incremental_risk
        if risk.account_open_risk is not None:
            account_guard = read_record(db,"account_guardrails",risk.account_id,AccountGuardrails)
            before = account_guard.max_open_risk-risk.account_open_risk-sum((r.risk for r in outstanding),Decimal(0))
            reservation.account_budget_before = before
            reservation.account_budget_after = before-risk.incremental_risk
        insert_record(db,"risk_reservations",reservation)
        return reservation

    @staticmethod
    def event_hash(observation: AccountObservation) -> str:
        payload: dict[str, JsonValue] = {"positions":[p.model_dump(mode="json") for p in observation.positions],
            "orders":[p.model_dump(mode="json") for p in observation.orders]}
        return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


def admit_delegation(journal: ActionStore, db: sqlite3.Connection, effect: Effect,
                     grant: DelegatedAuthorization, owner: EffectOwner | None) -> None:
    """Risk reservation and STARTED share one SQLite commit, never two stores."""
    current = current_authorized_action()
    if (current is None or current.action.fingerprint != effect.fingerprint
            or grant.action_fingerprint != effect.fingerprint or effect.action.tool != "trade_execute"):
        raise PermissionError("No exact gateway delegation authorization")
    if effect.idempotency_key != effect.action.parameters.get("effect_key"):
        raise PermissionError("Financial effect identity differs from the canonical action")
    if current.delegation is None:
        if current.approval_id is None:
            raise PermissionError("No central policy decision or exact user escalation approval")
        row = db.execute("SELECT record FROM approvals WHERE id=?",(current.approval_id,)).fetchone()
        escalation = Approval.model_validate_json(row[0]) if row else None
        if escalation is None or escalation.status != "CONSUMED" or escalation.fingerprint != effect.fingerprint or escalation.expires_at <= now_ms():
            raise PermissionError("Invalid exact escalation approval")
        db.execute("INSERT INTO approval_uses VALUES (?,?)",(escalation.id,effect.id))
    elif current.delegation.review_decision != "ALLOW":
        raise PermissionError("Independent policy decision does not allow execution")
    mandate = read_record(db,"trading_mandates",grant.mandate_id,TradingMandate)
    if (mandate.principal != effect.action.principal or owner is None
            or owner.responsibility_id != mandate.responsibility_id
            or effect.action.responsibility_id != mandate.responsibility_id
            or effect.action.parameters.get("account_id") != mandate.envelope.account_id
            or mandate.scope_fingerprint != grant.scope_fingerprint
            or mandate.approval_id is None or mandate.approved_envelope is None):
        raise PermissionError("Mandate ownership/fingerprint is invalid")
    row = db.execute("SELECT record FROM approvals WHERE id=?",(mandate.approval_id,)).fetchone()
    if row is None:
        raise PermissionError("Mandate approval record is missing")
    approval = Approval.model_validate_json(row[0])
    if (approval.status != "CONSUMED" or approval.resolved_by != mandate.principal
            or approval.action.parameters.get("mandate_id") != mandate.id
            or approval.action.parameters.get("envelope") != mandate.approved_envelope.model_dump(mode="json")):
        raise PermissionError("No exact previously user-approved mandate envelope")
    risk = RiskAssessment.model_validate(grant.risk)
    if risk.fingerprint != effect.fingerprint or risk.mandate_id != mandate.id:
        raise PermissionError("Risk assessment belongs to another action")
    intent = effect.action.parameters.get("intent")
    if not isinstance(intent,dict):
        raise PermissionError("Missing canonical financial intent")
    reservation = TradingMissions.reserve_in_transaction(db,risk,effect.id,
        operation=str(intent.get("operation")),pending=intent.get("order_type") != "market")
    reservation.review_decision,reservation.review_source,reservation.review_reason = grant.review_decision,grant.review_source,grant.review_reason
    write_record(db,"risk_reservations",reservation)
    effect.mandate_id,effect.reservation_id = mandate.id,reservation.id


def validate_delegated_outbound(journal: ActionStore, effect: Effect) -> None:
    with journal.transaction() as db:
        mandate = read_record(db,"trading_mandates",effect.mandate_id or "",TradingMandate)
        reservation = read_record(db,"risk_reservations",effect.reservation_id or "",RiskReservation)
        if (mandate.envelope.mode != "LIVE" or reservation.effect_id != effect.id or reservation.action_fingerprint != effect.fingerprint
                or effect.action.parameters.get("account_id") != mandate.envelope.account_id):
            raise PermissionError("Simulation or unbound reservation cannot send a live mutation")
        if reservation.risk_increasing:
            guard = read_record(db,"account_guardrails",reservation.account_id,AccountGuardrails)
            if (not guard.enabled or guard.emergency_stop or mandate.status != "ACTIVE"
                    or now_ms() >= mandate.envelope.expires_at):
                raise PermissionError("Autonomous risk stopped before outbound execution")
