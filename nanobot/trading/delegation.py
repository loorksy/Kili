"""Mandate evaluation at the existing central policy and executor boundaries."""
from __future__ import annotations

from decimal import Decimal

from nanobot.security.actions import Action, DelegatedAuthorization
from nanobot.trading.metaapi import BrokerPrice, SymbolSpec
from nanobot.trading.mission_models import TradingMandate
from nanobot.trading.mission_observation import refresh
from nanobot.trading.missions import TradingMissions
from nanobot.trading.proposals import TradeProposals
from nanobot.trading.risk import assess


class MandateAuthority:
    def __init__(self, proposals: TradeProposals, *, live_enabled: bool = False):
        self.proposals = proposals
        self.missions = TradingMissions(proposals.client,proposals.proposals.journal,live_enabled=live_enabled)

    async def evaluate(self, action: Action) -> DelegatedAuthorization | None:
        mandate_id = action.parameters.get("mandate_id")
        if mandate_id is None:
            return None
        if not isinstance(mandate_id,str) or action.tool != "trade_execute" or action.action_class != "consequential":
            raise PermissionError("Invalid delegated canonical action")
        mandate: TradingMandate = self.missions.mandates.get(mandate_id)
        self.missions.owner(action.principal,mandate)
        if mandate.approval_id is None or mandate.approved_envelope is None:
            raise PermissionError("Mandate is not user approved")
        if mandate.envelope.mode == "LIVE" and not self.missions.live_enabled:
            raise PermissionError("Live delegated trading is disabled")
        from nanobot.trading.execution import current_effect_owner
        owner = current_effect_owner()
        if owner is None or owner.responsibility_id != mandate.responsibility_id:
            raise PermissionError("Current responsibility execution does not own the mandate")
        preview_id = action.parameters.get("preview_id")
        if not isinstance(preview_id,str):
            raise ValueError("Delegated action needs an immutable preview")
        preview = self.proposals.require_preview(preview_id,action.principal)
        if (preview.material_action() != action.parameters or preview.plan_id != mandate.plan_id
                or preview.mandate_fingerprint != mandate.scope_fingerprint):
            raise PermissionError("Preview plan/mandate binding changed")
        mandate,observation,positions,orders = await refresh(self.missions,mandate)
        symbols = {preview.broker_symbol} | {p.symbol for p in [*observation.positions,*observation.orders]}
        specs: dict[str,SymbolSpec] = {}
        prices: dict[str,BrokerPrice] = {}
        for symbol in sorted(symbols):
            specs[symbol] = await self.proposals.client.specification(symbol)
            prices[symbol] = await self.proposals.client.price(symbol)
        margin = Decimal(0)
        if preview.intent.operation in {"open", "modify_order"}:
            p = prices[preview.broker_symbol]
            target = next((o for o in orders if o.id == preview.intent.target_id),None)
            volume = preview.intent.volume or (target.volume if target else None)
            if volume is None:
                raise ValueError("Broker volume is required for trusted margin calculation")
            margin = await self.proposals.client.calculate_margin(preview.broker_symbol,preview.intent.side,
                volume,preview.intent.price or (target.open_price if target else None) or (p.ask if preview.intent.side == "buy" else p.bid))
        risk = assess(mandate,preview.intent,action.fingerprint,observation,specs,prices,
            preview.broker_symbol,positions,orders,margin)
        # Dry-run the exact atomic ledger rules. Rollback never leaves a reservation.
        class PreviewOnlyError(Exception):
            pass
        try:
            with self.missions.journal.transaction() as db:
                self.missions.reserve_in_transaction(db,risk,"preview:"+preview.id,
                    operation=preview.intent.operation,pending=preview.intent.order_type != "market")
                raise PreviewOnlyError
        except PreviewOnlyError:
            pass
        plan = self.missions.plans.get(mandate.plan_id)
        return DelegatedAuthorization(mandate_id=mandate.id,action_fingerprint=action.fingerprint,
            scope_fingerprint=mandate.scope_fingerprint,risk=risk.model_dump(mode="json"),
            review_context={"mandate":mandate.envelope.model_dump(mode="json"),
                "plan":plan.model_dump(mode="json"),"risk":risk.model_dump(mode="json")})
