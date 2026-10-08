"""Account observation and pre-authorized finish work on Nanobot's existing cron."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from nanobot.agent.tools.context import RequestContext, ResponsibilityExecution, request_context
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.trade_execute import TradeExecuteTool
from nanobot.market.oanda import ProviderUnavailableError
from nanobot.security.actions import ActionPolicy, now_ms
from nanobot.session.responsibilities import ResponsibilityStore
from nanobot.trading.execution import TradeExecutor
from nanobot.trading.metaapi import BrokerItem, ProviderRejectedError
from nanobot.trading.mission_models import FinishBehavior, TradingMandate
from nanobot.trading.mission_observation import refresh
from nanobot.trading.proposals import TradeIntent
from nanobot.trading.risk import item_risk


class MissionWatchers:
    def __init__(self, executor: TradeExecutor, responsibilities: ResponsibilityStore, policy: ActionPolicy | None = None):
        self.executor,self.responsibilities = executor,responsibilities
        self.service = executor.authority.missions
        self.policy = policy or ActionPolicy(executor.effects)

    def nearest(self) -> int | None:
        return min((min(m.next_check_at,m.envelope.expires_at) if m.status == "ACTIVE" else m.next_check_at
            for m in self.service.mandates.list() if m.approved_at is not None
            and m.status not in {"CANCELLED","COMPLETED"} and (m.status != "EXPIRED" or m.finish_pending)),default=None)

    async def check_limits(self, mandate: TradingMandate, positions: list[BrokerItem], orders: list[BrokerItem]) -> TradingMandate:
        assert mandate.observed is not None
        goal = self.service.goals.get(mandate.goal_id)
        limits = mandate.envelope
        total = mandate.realized_pnl+mandate.unrealized_pnl
        today = datetime.now(timezone.utc).date().isoformat()
        loss = total <= -limits.max_mission_loss or (limits.max_daily_loss is not None
            and mandate.daily_pnl.get(today,Decimal(0))+mandate.unrealized_pnl <= -limits.max_daily_loss)
        loss = loss or (limits.max_drawdown is not None and mandate.peak_pnl-total >= limits.max_drawdown)
        guard = self.service.guardrails.get(limits.account_id)
        loss = loss or guard.baseline_equity-mandate.observed.account.equity >= guard.max_account_loss
        try:
            exposure = Decimal(0)
            for item in [*positions,*orders]:
                exposure += item_risk(item,await self.service.client.specification(item.symbol),
                    await self.service.client.price(item.symbol),limits.currency,pending=item in orders)
            loss = loss or exposure > min(limits.max_open_risk,limits.max_mission_loss+total)
        except (ValueError,ProviderUnavailableError,ProviderRejectedError):
            mandate.status,mandate.attention_reason = "NEEDS_ATTENTION","Cannot safely calculate current protected exposure"
        if guard.emergency_stop:
            mandate.status,mandate.finish_pending,mandate.finish_kind = "RISK_STOPPED",True,"emergency"
        elif loss:
            mandate.status,mandate.finish_pending,mandate.finish_kind = "RISK_STOPPED",True,"breach"
        elif now_ms() >= limits.expires_at:
            mandate.status,mandate.finish_pending,mandate.finish_kind = "EXPIRED",True,"expiry"
        elif goal.target_profit is not None and mandate.pnl_complete and total >= goal.target_profit:
            mandate.status,mandate.finish_pending,mandate.finish_kind = "TARGET_REACHED",True,"target"
        elif limits.supervision_position_id and not positions and not orders and mandate.pnl_complete:
            mandate.status,mandate.finish_pending = "COMPLETED",False
        return self.service.mandates.save(mandate)

    async def finish(self, mandate: TradingMandate, positions: list[BrokerItem], orders: list[BrokerItem]) -> None:
        behaviors: dict[str,FinishBehavior] = {"breach":mandate.envelope.breach_behavior,
            "target":mandate.envelope.target_behavior,"expiry":mandate.envelope.expiry_behavior,
            "emergency":mandate.envelope.emergency_behavior}
        behavior = behaviors[mandate.finish_kind or "breach"]
        targets: list[tuple[BrokerItem,Literal["cancel_order","close_position"]]] = [(p,"cancel_order") for p in orders if behavior.cancel_pending]
        if behavior.close_positions:
            for position in positions:
                targets.append((position,"close_position"))
        if not targets:
            mandate.finish_pending = False
            self.service.mandates.save(mandate)
            return
        responsibility = self.responsibilities.get(mandate.responsibility_id)
        if responsibility.active_wake_id or responsibility.recovery_required or responsibility.delivery_needed:
            return
        base_key = f"mission-finish:{mandate.id}:{mandate.finish_kind}"
        batch = hashlib.sha256(repr([(p.id,op) for p,op in targets]).encode()).hexdigest()
        key = base_key+":"+batch
        self.responsibilities.enqueue(responsibility.id,key,"Pre-authorized mission finish operations")
        claim = self.responsibilities.claim(responsibility.id,key)
        if claim is None:
            return
        channel,_,chat_id = mandate.principal.partition(":")
        context = RequestContext(channel=channel,chat_id=chat_id,session_key=mandate.principal)
        context.responsibility_scope.executions[responsibility.id] = ResponsibilityExecution(store=self.responsibilities,claim=claim)
        registry = ToolRegistry(self.policy)
        registry.register(TradeExecuteTool(self.executor))
        with request_context(context):
            for target,operation in targets:
                mapping = next((m for m in self.executor.proposals.mappings.records.list()
                    if m.account_id == mandate.envelope.account_id and m.provider_symbol == target.symbol
                    and m.instrument.id in mandate.envelope.allowed_instruments and m.status == "VERIFIED"),None)
                if mapping is None:
                    raise ValueError("Finish target no longer has a verified account mapping")
                identity = "proposal_"+hashlib.sha256(f"{base_key}:{target.id}:{operation}".encode()).hexdigest()
                try:
                    proposal = self.executor.proposals.proposals.get(identity)
                except ValueError:
                    proposal = self.executor.proposals.create(mandate.principal,
                        TradeIntent(canonical_instrument=mapping.instrument.id,operation=operation,target_id=target.id),
                        responsibility_id=mandate.responsibility_id,mandate_id=mandate.id,
                        rationale="Execute the user's explicitly approved mission finish behavior",proposal_id=identity)
                preview = self.executor.proposals.require_preview(proposal.preview_id,mandate.principal) if proposal.preview_id else await self.executor.proposals.preview(proposal.id,mandate.principal)
                result = await registry.execute("trade_execute",{"preview_id":preview.id})
                if getattr(result,"is_error",False):
                    current = self.service.mandates.get(mandate.id)
                    current.attention_reason = "Pre-authorized finish needs user attention; inspect exact approval/effect"
                    self.service.mandates.save(current)
                    break

    async def run_due(self) -> None:
        for mandate in self.service.mandates.list():
            if (mandate.approved_at is None or mandate.status in {"CANCELLED","COMPLETED"}
                    or mandate.status == "EXPIRED" and not mandate.finish_pending
                    or mandate.next_check_at > now_ms() and now_ms() < mandate.envelope.expires_at):
                continue
            channel,_,chat_id = mandate.principal.partition(":")
            with request_context(RequestContext(channel=channel,chat_id=chat_id,session_key=mandate.principal)):
                try:
                    mandate,_,positions,orders = await refresh(self.service,mandate)
                    mandate = await self.check_limits(mandate,positions,orders)
                    if mandate.finish_pending:
                        await self.finish(mandate,positions,orders)
                    mandate = self.service.mandates.get(mandate.id)
                    # Quotes do not wake the model. Terms/state and ten bounded
                    # progress/loss buckets do, using durable idempotency receipts.
                    step = mandate.envelope.max_mission_loss/10
                    bucket = int((mandate.realized_pnl+mandate.unrealized_pnl)//step)
                    terms = [(p.id,p.type,str(p.volume),str(p.stop_loss),str(p.take_profit)) for p in [*positions,*orders]]
                    event = hashlib.sha256(repr((mandate.status,mandate.attention_reason,bucket,terms)).encode()).hexdigest()
                    mandate = self.notify(mandate,event)
                    mandate.failure_count = 0
                    self.service.mandates.save(mandate)
                except (ValueError,PermissionError,ProviderUnavailableError,ProviderRejectedError):
                    current = self.service.mandates.get(mandate.id)
                    current.failure_count += 1
                    current.status,current.attention_reason = "NEEDS_ATTENTION","Account/finish verification unavailable; new risk frozen"
                    current.next_check_at = now_ms()+min(300_000,30_000*2**min(current.failure_count,3))
                    current = self.service.mandates.save(current)
                    self.notify(current,"unavailable:"+current.attention_reason)

    def notify(self, mandate: TradingMandate, event: str) -> TradingMandate:
        pending_id = mandate.pending_event_id
        if pending_id and not mandate.pending_event_queued:
            self.responsibilities.enqueue(mandate.responsibility_id,pending_id,mandate.pending_event_text)
            mandate.pending_event_queued = True
            mandate = self.service.mandates.save(mandate)
        if event != mandate.last_event_hash:
            mandate.event_generation += 1
            identity = f"mission:{mandate.id}:{mandate.event_generation}"
            mandate.pending_event_id = identity
            mandate.pending_event_text = (f"Trading mission {mandate.id}: {mandate.status}. "
                f"P&L {mandate.realized_pnl+mandate.unrealized_pnl} {mandate.envelope.currency}; "
                f"target is aspirational. {mandate.attention_reason}")
            mandate.pending_event_queued,mandate.last_event_hash = False,event
            mandate = self.service.mandates.save(mandate)  # durable outbox before enqueue
            self.responsibilities.enqueue(mandate.responsibility_id,identity,mandate.pending_event_text)
            mandate.pending_event_queued = True
            mandate = self.service.mandates.save(mandate)
        return mandate
