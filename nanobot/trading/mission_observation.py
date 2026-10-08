"""Broker evidence attribution and material account events; no LLM polling."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from nanobot.security.actions import Effect, now_ms
from nanobot.trading.metaapi import BrokerDeal, BrokerItem
from nanobot.trading.mission_models import AccountObservation, TradingMandate
from nanobot.trading.missions import TradingMissions


def owned_items(mandate: TradingMandate, effects: list[Effect], observation: AccountObservation) -> tuple[list[BrokerItem],list[BrokerItem]]:
    relevant = [e for e in effects if e.mandate_id == mandate.id and e.state in {"SUCCEEDED","UNCERTAIN","RECONCILING","STARTED"}]
    clients = client_ids(relevant)
    references = broker_references(relevant)
    positions = [p for p in observation.positions if p.client_id in clients or p.id in references or p.id == mandate.envelope.supervision_position_id]
    orders = [p for p in observation.orders if p.client_id in clients or p.id in references or p.id in mandate.envelope.supervision_order_ids]
    return positions,orders


def terms(item: BrokerItem) -> tuple[object,...]:
    return (item.symbol,item.type,item.volume,item.open_price,item.stop_loss,item.take_profit)


def client_ids(effects: list[Effect]) -> set[str]:
    return {identity for e in effects if isinstance(payload := e.action.parameters.get("broker_request"),dict)
        and isinstance(identity := payload.get("clientId"),str)}


def broker_references(effects: list[Effect]) -> set[str]:
    identities = {e.provider_reference for e in effects if e.provider_reference}
    for effect in effects:
        if isinstance(effect.result,dict):
            for key in ("order_id","position_id"):
                value = effect.result.get(key)
                if isinstance(value,str):
                    identities.add(value)
    return identities


def explained_change(old: BrokerItem | None, new: BrokerItem | None, effects: list[Effect], since: int,
                     deals: list[BrokerDeal]) -> bool:
    if old is not None and new is None and any(d.position_id == old.id or d.order_id == old.id for d in deals):
        return True
    for effect in effects:
        if effect.updated_at < since or effect.state not in {"SUCCEEDED","UNCERTAIN","STARTED","RECONCILING"}:
            continue
        payload = effect.action.parameters.get("broker_request")
        if not isinstance(payload,dict):
            continue
        if old is None and new is not None and new.client_id and payload.get("clientId") == new.client_id:
            return True
        target = payload.get("positionId",payload.get("orderId"))
        if old is None or target != old.id:
            continue
        if new is None and payload.get("actionType") in {"POSITION_CLOSE_ID","ORDER_CANCEL"}:
            return True
        if new is not None:
            expected = old.model_copy(deep=True)
            if payload.get("actionType") == "POSITION_PARTIAL":
                if old.volume is not None:
                    expected.volume = old.volume-Decimal(str(payload.get("volume")))
            else:
                for attribute,key in (("stop_loss","stopLoss"),("take_profit","takeProfit"),("open_price","openPrice"),("volume","volume")):
                    if key in payload:
                        setattr(expected,attribute,Decimal(str(payload[key])))
            if terms(expected) == terms(new):
                return True
    return False


async def refresh(service: TradingMissions, mandate: TradingMandate) -> tuple[TradingMandate,AccountObservation,list[BrokerItem],list[BrokerItem]]:
    observation = await service.observe()
    effects = service.journal.list_effects()
    own_effects = [e for e in effects if e.mandate_id == mandate.id]
    start = datetime.fromtimestamp(mandate.approved_at / 1000,timezone.utc).isoformat() if mandate.approved_at else datetime.now(timezone.utc).isoformat()
    deals = await service.client.history_deals(start,datetime.now(timezone.utc).isoformat())
    if mandate.envelope.mode == "SIMULATION":
        from nanobot.trading.simulation import MissionSimulation
        observation,simulated_deals = await MissionSimulation(service,mandate).observe(observation)
        deals = [*deals,*simulated_deals]
    positions,orders = owned_items(mandate,effects,observation)
    if mandate.observed:
        previous_owned,_ = owned_items(mandate,effects,mandate.observed)
        disappeared = {p.id for p in previous_owned}-{p.id for p in positions}
        pending = set(mandate.pending_pnl_positions) | disappeared
        resolved = {d.position_id for d in deals if d.entry_type in {"DEAL_ENTRY_OUT","DEAL_ENTRY_INOUT"}}
        mandate.pending_pnl_positions = sorted(pending-resolved)
    mandate.pnl_complete = not mandate.pending_pnl_positions
    if not mandate.pnl_complete:
        mandate.status,mandate.attention_reason = "NEEDS_ATTENTION","Closed position P&L awaits authoritative deal history"
    if mandate.observed:
        for kind, previous,current in (("positions",mandate.observed.positions,observation.positions),("orders",mandate.observed.orders,observation.orders)):
            old_by_id,new_by_id = {p.id:p for p in previous},{p.id:p for p in current}
            for identity in old_by_id.keys() | new_by_id.keys():
                old,new = old_by_id.get(identity),new_by_id.get(identity)
                if old is not None and new is not None and terms(old) == terms(new):
                    continue
                # A broker fill moves an attributed order into an attributed position.
                filled = old is not None and new is None and kind == "orders" and any(p.client_id == old.client_id and p.client_id for p in positions)
                if not filled and not explained_change(old,new,effects,mandate.observed.fetched_at,deals):
                    mandate.status,mandate.attention_reason = "NEEDS_ATTENTION","Manual/unattributed account change; review ownership and risk"
    clients = client_ids(own_effects)
    ids = {p.id for p in [*positions,*orders]} | broker_references(own_effects)
    if mandate.envelope.supervision_position_id:
        ids.add(mandate.envelope.supervision_position_id)
    relevant = {d.id:d for d in deals if d.position_id in ids or d.order_id in ids or d.client_id is not None and d.client_id in clients}
    realized = sum((d.profit+d.commission+d.swap for d in relevant.values()),Decimal(0))
    unrealized = Decimal(0)
    for position in positions:
        if position.profit is None:
            mandate.status,mandate.attention_reason = "NEEDS_ATTENTION","Authoritative position P&L is unavailable"
        else:
            unrealized += position.profit+position.swap
    if mandate.envelope.supervision_position_id:
        baseline = next(p for p in mandate.baseline.positions if p.id == mandate.envelope.supervision_position_id)
        baseline_pnl = (baseline.profit or Decimal(0))+baseline.swap
        if any(p.id == baseline.id for p in positions):
            unrealized -= baseline_pnl
        elif any(d.position_id == baseline.id for d in relevant.values()):
            realized -= baseline_pnl
    mandate.realized_pnl,mandate.unrealized_pnl = realized,unrealized
    mandate.peak_pnl = max(mandate.peak_pnl,realized+unrealized)
    mandate.daily_pnl = {}
    for deal in relevant.values():
        timestamp = datetime.fromisoformat(deal.time.replace("Z","+00:00"))
        if timestamp.tzinfo is None:
            raise ValueError("Deal accounting requires an explicit broker timezone")
        day = timestamp.astimezone(timezone.utc).date().isoformat()
        mandate.daily_pnl[day] = mandate.daily_pnl.get(day,Decimal(0))+deal.profit+deal.commission+deal.swap
    mandate.observed = observation
    for reservation in service.reservations.list():
        if reservation.mandate_id != mandate.id or reservation.state == "RELEASED":
            continue
        effect = service.journal.get_effect(reservation.effect_id)
        if effect.state in {"STARTED","UNCERTAIN","RECONCILING"}:
            reservation.state = "UNCERTAIN"
            mandate.status,mandate.attention_reason = "NEEDS_ATTENTION","Reconcile unresolved financial effect before new risk"
        elif effect.state == "FAILED":
            reservation.state = "RELEASED"
        elif effect.state == "SUCCEEDED":
            reservation.provider_reference = effect.provider_reference
            payload = effect.action.parameters.get("broker_request")
            if isinstance(payload,dict):
                present = any(p.id == effect.provider_reference or p.client_id == payload.get("clientId") and p.client_id for p in [*positions,*orders])
                if present:
                    reservation.state = "ACTIVE"
                elif payload.get("actionType") in {"ORDER_CANCEL","POSITION_CLOSE_ID","POSITION_PARTIAL","POSITION_MODIFY","ORDER_MODIFY"} or any(d.position_id == effect.provider_reference or d.order_id == effect.provider_reference or d.client_id == payload.get("clientId") and d.client_id for d in relevant.values()):
                    reservation.state = "RELEASED"
                # No evidence of an acknowledged entry retains its reservation.
        service.reservations.save(reservation)
    mandate.next_check_at = now_ms()+30_000
    return service.mandates.save(mandate),observation,positions,orders
