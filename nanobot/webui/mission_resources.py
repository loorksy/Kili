"""Authenticated conversation adapters; durable financial authority stays in Python."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from nanobot.config.schema import Config
from nanobot.trading.metaapi import MetaApiClient
from nanobot.trading.mission_models import AccountGuardrails
from nanobot.trading.missions import TradingMissions


class MissionControl(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_key: str
    mandate_id: str
    operation: Literal["activate", "pause", "cancel", "resume", "emergency_stop", "guardrails"]
    guardrails: AccountGuardrails | None = None


def service_for(config: Config) -> TradingMissions:
    connection = config.tools.integrations.metaapi
    if connection is None:
        raise ValueError("MetaApi connection is unavailable")
    return TradingMissions(MetaApiClient(connection),live_enabled=config.tools.integrations.autonomous_trading_enabled)


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
        "expires_at":mandate.envelope.expires_at}


async def control_mission(service: TradingMissions, request: MissionControl) -> dict[str, object]:
    mandate = service.mandates.get(request.mandate_id)
    service.owner(request.session_key,mandate)
    if request.operation == "activate":
        await service.activate(request.session_key,mandate.id)
    elif request.operation == "guardrails":
        # This adapter is callable only by the authenticated mutation handler,
        # never a model tool. CAS prevents stale account-wide changes.
        guard = request.guardrails
        if guard is None or guard.id != mandate.envelope.account_id:
            raise PermissionError("Guardrail account differs from this mandate")
        previous = service.guardrails.get(guard.id)
        if guard.enabled and mandate.envelope.mode == "LIVE" and not service.live_enabled:
            raise PermissionError("Live delegated trading is disabled in Settings")
        if guard.baseline_equity != previous.baseline_equity:
            raise PermissionError("Loss accounting baseline cannot be reset through controls")
        service.guardrails.save(guard)
    else:
        service.control(request.session_key,mandate.id,request.operation,user=True)
    return mission_snapshot(service,request.session_key,mandate.id)
