"""Authenticated conversation adapters; durable financial authority stays in Python."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from nanobot.config.schema import Config
from nanobot.session.records import RecordStore
from nanobot.trading.accounts import TradingAccounts
from nanobot.trading.metaapi import MetaApiClient
from nanobot.trading.mission_models import AccountGuardrails, TradingMandate
from nanobot.trading.missions import TradingMissions


class MissionControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_key: str
    mandate_id: str
    operation: Literal["activate", "pause", "cancel", "resume", "emergency_stop", "guardrails", "approve", "deny"]
    guardrails: AccountGuardrails | None = None
    fingerprint: str | None = None


def service_for(config: Config, mandate_id: str | None = None, principal: str | None = None) -> TradingMissions:
    account_id = None
    if mandate_id:
        mandate = RecordStore("trading_mandates", TradingMandate).get(mandate_id)
        if mandate.principal != principal:
            raise PermissionError("Trading mission belongs to another conversation")
        account_id = mandate.envelope.account_id
    connection = TradingAccounts(config.tools.integrations).connection(account_id, principal=principal)
    return TradingMissions(MetaApiClient(connection),live_enabled=not config.tools.integrations.delegated_trading_blocked)


def mission_snapshot(service: TradingMissions, principal: str, mandate_id: str) -> dict[str, object]:
    mandate = service.mandates.get(mandate_id)
    service.owner(principal,mandate)
    goal,plan = service.goals.get(mandate.goal_id),service.plans.get(mandate.plan_id)
    reservations = [r for r in service.reservations.list() if r.mandate_id == mandate.id and r.state != "RELEASED"]
    return {"id":mandate.id,"status":mandate.status,"mode":mandate.envelope.mode,
        "goal":goal.objective,"target_profit":str(goal.target_profit) if goal.target_profit is not None else None,
        "currency":goal.currency,"envelope":mandate.envelope.model_dump(mode="json"),
        "realized_pnl":str(mandate.realized_pnl),"unrealized_pnl":str(mandate.unrealized_pnl),
        "pnl_complete":mandate.pnl_complete,"remaining_loss":str(mandate.envelope.max_mission_loss+mandate.realized_pnl+mandate.unrealized_pnl),
        "reserved_risk":str(sum(r.risk for r in reservations)),"attention_reason":mandate.attention_reason,
        "plan_version":plan.plan_version,"monitoring_summary":plan.monitoring_summary,
        "approval_id":mandate.approval_id,"approved":mandate.approved_at is not None,
        "expires_at":mandate.envelope.expires_at,
        "fingerprint":service.approval_action(mandate).fingerprint,
        "account_id":mandate.envelope.account_id,
        "mode_label":mandate.envelope.mode,
        "max_mission_loss":str(mandate.envelope.max_mission_loss),
        "max_risk_per_trade":str(mandate.envelope.max_risk_per_trade),
        "instruments":list(mandate.envelope.allowed_instruments)}


async def authorize_mandate(service: TradingMissions, principal: str, mandate: TradingMandate,
                           fingerprint: str | None, *, approve: bool) -> None:
    """Owner button path. A peer message cannot call this."""
    if not fingerprint:
        raise PermissionError("Mandate approval requires the exact action fingerprint")
    action = service.approval_action(mandate)
    if fingerprint != action.fingerprint:
        raise PermissionError("Fingerprint does not match this mandate")
    pending = service.journal.pending_for_fingerprint(fingerprint, principal)
    service.journal.resolve(pending.id, principal=principal, approve=approve, fingerprint=fingerprint)
    if approve:
        await service.activate(principal, mandate.id)


async def control_mission(service: TradingMissions, request: MissionControl) -> dict[str, object]:
    mandate = service.mandates.get(request.mandate_id)
    service.owner(request.session_key,mandate)
    if request.operation == "approve":
        await authorize_mandate(service, request.session_key, mandate, request.fingerprint, approve=True)
    elif request.operation == "deny":
        await authorize_mandate(service, request.session_key, mandate, request.fingerprint, approve=False)
    elif request.operation == "activate":
        await service.activate(request.session_key,mandate.id)
    elif request.operation == "guardrails":
        # This adapter is callable only by the authenticated mutation handler,
        # never a model tool. CAS prevents stale account-wide changes.
        guard = request.guardrails
        if guard is None or guard.id != mandate.envelope.account_id:
            raise PermissionError("Guardrail account differs from this mandate")
        previous = service.guardrails.get(guard.id)
        if guard.enabled and guard.id != service.client.connection.account_id:
            raise PermissionError("Cannot enable guardrails for a replaced account connection")
        if guard.enabled and mandate.envelope.mode == "LIVE" and not service.live_enabled:
            raise PermissionError("Live delegated trading is disabled in Settings")
        if guard.baseline_equity != previous.baseline_equity:
            raise PermissionError("Loss accounting baseline cannot be reset through controls")
        service.guardrails.save(guard)
    else:
        service.control(request.session_key,mandate.id,request.operation,user=True)
    return mission_snapshot(service,request.session_key,mandate.id)
