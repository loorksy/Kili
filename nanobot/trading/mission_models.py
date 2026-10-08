"""Versioned goals and plans are intent; a signed mandate alone grants authority."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from nanobot.session.records import RuntimeRecord
from nanobot.trading.metaapi import AccountState, BrokerItem

Money = Annotated[Decimal, Field(gt=0, le=Decimal("1e12"), allow_inf_nan=False)]
Operation = Literal["open", "modify_position", "modify_order", "cancel_order", "close_position"]
MissionStatus = Literal["DRAFT", "AWAITING_MANDATE_APPROVAL", "ACTIVE", "PAUSED",
                        "RISK_STOPPED", "TARGET_REACHED", "EXPIRED", "CANCELLED",
                        "NEEDS_ATTENTION", "COMPLETED"]


class TradingGoal(RuntimeRecord):
    principal: str
    responsibility_id: str
    account_id: str
    objective: str = Field(min_length=1, max_length=2000)
    objective_type: Literal["profit", "supervision"] = "profit"
    target_profit: Money | None = None
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    start_at: int = Field(ge=0)
    end_at: int = Field(gt=0)
    allowed_instruments: list[str] = Field(default_factory=list, max_length=50)
    capital_preference: Money | None = None
    status: MissionStatus = "DRAFT"

    @model_validator(mode="after")
    def duration(self) -> TradingGoal:
        if not self.start_at < self.end_at:
            raise ValueError("An explicit end after start is required")
        return self


class TradingPlan(RuntimeRecord):
    goal_id: str
    plan_version: int = Field(ge=1)
    market_scope: list[str] = Field(max_length=50)
    monitoring_summary: str = Field(max_length=2000)
    execution_summary: str = Field(max_length=2000)
    risk_proposal_summary: str = Field(max_length=2000)
    reevaluation_summary: str = Field(max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=30)
    chart_refs: list[str] = Field(default_factory=list, max_length=10)


class FinishBehavior(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    cancel_pending: bool
    close_positions: bool
    notify: bool = True


class MandateEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    mode: Literal["SIMULATION", "LIVE"]
    account_id: str
    currency: str = Field(pattern=r"^[A-Z]{3}$")
    start_at: int = Field(ge=0)
    expires_at: int = Field(gt=0)
    allocated_capital: Money
    max_mission_loss: Money
    max_daily_loss: Money | None = None
    max_drawdown: Money | None = None
    max_open_risk: Money
    max_risk_per_trade: Money
    max_concurrent_positions: int = Field(ge=0, le=100)
    max_pending_orders: int = Field(ge=0, le=100)
    max_margin_usage: Money | None = None
    max_notional: Money | None = None
    allowed_instruments: list[str] = Field(min_length=1, max_length=50)
    allowed_order_types: list[Literal["market", "limit", "stop"]] = Field(min_length=1)
    allowed_actions: list[Operation] = Field(min_length=1)
    risk_increase_permissions: list[Literal["widen_stop", "add_exposure", "hedge"]] = Field(default_factory=list)
    supervision_position_id: str | None = None
    supervision_order_ids: list[str] = Field(default_factory=list, max_length=100)
    breach_behavior: FinishBehavior
    target_behavior: FinishBehavior
    expiry_behavior: FinishBehavior
    emergency_behavior: FinishBehavior

    @model_validator(mode="after")
    def boundaries(self) -> MandateEnvelope:
        if self.expires_at <= self.start_at or self.max_mission_loss > self.allocated_capital:
            raise ValueError("Invalid duration or loss exceeds allocated accounting capital")
        if self.max_risk_per_trade > self.max_open_risk:
            raise ValueError("Per-trade risk exceeds aggregate open-risk limit")
        if self.supervision_position_id and "open" in self.allowed_actions:
            raise ValueError("Position supervision cannot authorize unrelated entries")
        for behavior in (self.breach_behavior, self.target_behavior, self.expiry_behavior, self.emergency_behavior):
            if behavior.close_positions and "close_position" not in self.allowed_actions:
                raise ValueError("Finish closure requires explicit close permission")
            if behavior.cancel_pending and "cancel_order" not in self.allowed_actions:
                raise ValueError("Finish cancellation requires explicit cancel permission")
        return self

    @property
    def fingerprint(self) -> str:
        return hashlib.sha256(json.dumps(self.model_dump(mode="json"), sort_keys=True,
            separators=(",", ":"), allow_nan=False).encode()).hexdigest()


class AccountObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    fetched_at: int
    account: AccountState
    positions: list[BrokerItem]
    orders: list[BrokerItem]


class TradingMandate(RuntimeRecord):
    goal_id: str
    plan_id: str
    principal: str
    responsibility_id: str
    envelope: MandateEnvelope
    approved_envelope: MandateEnvelope | None = None
    scope_fingerprint: str
    policy_version: Literal["delegated-v1"] = "delegated-v1"
    status: MissionStatus = "AWAITING_MANDATE_APPROVAL"
    approval_id: str | None = None
    approved_at: int | None = None
    approved_by: str | None = None
    baseline: AccountObservation
    observed: AccountObservation | None = None
    next_check_at: int
    failure_count: int = 0
    last_event_hash: str | None = None
    realized_pnl: Decimal = Decimal(0)
    unrealized_pnl: Decimal = Decimal(0)
    peak_pnl: Decimal = Decimal(0)
    daily_pnl: dict[str, Decimal] = Field(default_factory=dict)
    attention_reason: str = ""
    finish_pending: bool = False
    finish_kind: Literal["breach", "target", "expiry", "emergency"] | None = None
    pending_pnl_positions: list[str] = Field(default_factory=list,max_length=10000)
    pnl_complete: bool = True
    event_generation: int = 0
    pending_event_id: str | None = None
    pending_event_text: str = ""
    pending_event_queued: bool = True
    last_operational_hash: str | None = None
    last_notified_pnl: Decimal | None = None


class AccountGuardrails(RuntimeRecord):
    enabled: bool = False
    emergency_stop: bool = False
    max_active_mandates: int = Field(default=1, ge=1, le=100)
    max_open_risk: Money
    max_account_loss: Money
    baseline_equity: Money
    max_notional: Money | None = None
    max_margin_usage: Money | None = None


class RiskReservation(RuntimeRecord):
    account_id: str
    mandate_id: str
    effect_id: str
    action_fingerprint: str
    risk: Decimal = Field(ge=0, allow_inf_nan=False)
    notional: Decimal = Field(ge=0, allow_inf_nan=False)
    margin: Decimal = Field(ge=0, allow_inf_nan=False)
    risk_increasing: bool
    entry_kind: Literal["market", "pending"] | None = None
    state: Literal["RESERVED", "ACTIVE", "UNCERTAIN", "RELEASED"] = "RESERVED"
    provider_reference: str | None = None
    assessment: dict[str, JsonValue] = Field(default_factory=dict)
    review_decision: Literal["ALLOW", "ASK_USER", "DENY"] | None = None
    review_source: Literal["deterministic", "independent", "user"] | None = None
    review_reason: str = Field(default="",max_length=1000)
    mission_budget_before: Decimal | None = None
    mission_budget_after: Decimal | None = None
    account_budget_before: Decimal | None = None
    account_budget_after: Decimal | None = None


class RiskAssessment(BaseModel):
    model_config = ConfigDict(extra="forbid")
    semantics_version: Literal[1] = 1
    account_id: str
    mandate_id: str
    mandate_revision: int
    fetched_at: int
    fingerprint: str
    risk_increasing: bool
    proposed_risk: Decimal
    incremental_risk: Decimal
    open_risk: Decimal | None
    account_open_risk: Decimal | None
    mission_pnl: Decimal
    remaining_loss: Decimal
    position_count: int
    order_count: int
    proposed_notional: Decimal
    proposed_margin: Decimal
    margin_usage: Decimal
    account_equity: Decimal
    account_notional: Decimal = Decimal(0)
    mission_notional: Decimal = Decimal(0)
