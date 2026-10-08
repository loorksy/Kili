"""Trusted Decimal risk arithmetic, independent of the acting model and OANDA."""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from nanobot.security.actions import now_ms
from nanobot.trading.metaapi import BrokerItem, BrokerPrice, SymbolSpec
from nanobot.trading.mission_models import AccountObservation, RiskAssessment, TradingMandate
from nanobot.trading.proposals import TradeIntent, TradeProposals


def fresh_price(price: BrokerPrice) -> None:
    observed = datetime.fromisoformat(price.time.replace("Z", "+00:00"))
    if (observed.tzinfo is None or not -5 <= (datetime.now(timezone.utc)-observed).total_seconds() <= 30
            or price.bid <= 0 or price.ask < price.bid):
        raise ValueError("Fresh executable broker pricing is required")


def side_of(item: BrokerItem) -> str:
    parts = item.type.split("_")
    if "BUY" in parts:
        return "buy"
    if "SELL" in parts:
        return "sell"
    raise ValueError("Broker direction is ambiguous")


def stop_risk(side: str, entry: Decimal, stop: Decimal | None, volume: Decimal,
              spec: SymbolSpec, price: BrokerPrice, currency: str) -> Decimal:
    if stop is None or stop <= 0 or volume <= 0:
        raise ValueError("Autonomous exposure requires a valid protective stop and volume")
    distance = max(Decimal(0), entry-stop if side == "buy" else stop-entry)
    if spec.tick_size and price.loss_tick_value:
        return distance / spec.tick_size * price.loss_tick_value * volume
    if spec.contract_size and spec.contract_size > 0 and spec.currency_profit == currency:
        return distance * spec.contract_size * volume
    raise ValueError("Cannot independently calculate account-currency loss")


def item_risk(item: BrokerItem, spec: SymbolSpec, price: BrokerPrice, currency: str,
              *, pending: bool = False) -> Decimal:
    fresh_price(price)
    side = side_of(item)
    entry = item.open_price if pending else (price.bid if side == "buy" else price.ask)
    if entry is None or item.volume is None:
        raise ValueError("Incomplete broker exposure data")
    return stop_risk(side, entry, item.stop_loss, item.volume, spec, price, currency)


def notional(entry: Decimal, volume: Decimal, spec: SymbolSpec, currency: str) -> Decimal:
    if not spec.contract_size or spec.currency_profit != currency:
        raise ValueError("Cannot determine account-currency notional without broker conversion")
    return abs(entry * volume * spec.contract_size)


def assess(mandate: TradingMandate, intent: TradeIntent, fingerprint: str,
           observation: AccountObservation, specs: dict[str, SymbolSpec],
           prices: dict[str, BrokerPrice], symbol: str, owned_positions: list[BrokerItem],
           owned_orders: list[BrokerItem], proposed_margin: Decimal) -> RiskAssessment:
    envelope = mandate.envelope
    now = now_ms()
    if not 0 <= now-observation.fetched_at <= 30_000:
        raise ValueError("Account observation is stale")
    if observation.account.currency != envelope.currency or not observation.account.trade_allowed:
        raise ValueError("Account currency/permission changed")
    if intent.operation not in envelope.allowed_actions or intent.canonical_instrument not in envelope.allowed_instruments:
        raise PermissionError("Action is outside the approved mandate scope")
    spec, price = specs[symbol], prices[symbol]
    fresh_price(price)
    TradeProposals.validate_spec(intent, spec)
    positions, orders = owned_positions, owned_orders
    target = next((p for p in (orders if "order" in intent.operation else positions)
                   if p.id == intent.target_id), None)
    if intent.operation != "open" and (target is None or target.symbol != symbol):
        raise PermissionError("Exact broker target is not owned/supervised by this mission")
    if envelope.supervision_position_id and intent.operation == "open":
        raise PermissionError("Supervision never grants unrelated entry authority")
    if envelope.supervision_position_id and target is not None:
        original = next((p for p in mandate.baseline.positions if p.id == target.id),None)
        if original and (target.type != original.type or target.open_price != original.open_price
                or target.volume is None or original.volume is None or target.volume > original.volume):
            raise PermissionError("Supervised position ownership changed; new exact user mandate required")
    risk = Decimal(0)
    previous = Decimal(0)
    amount = Decimal(0)
    if intent.operation == "open":
        if intent.order_type not in envelope.allowed_order_types:
            raise PermissionError("Order type is outside mandate scope")
        if intent.order_type != "market":
            capability = "SYMBOL_ORDER_"+intent.order_type.upper()
            if spec.order_mode is None or capability not in spec.order_mode:
                raise PermissionError("Broker has not advertised this pending order capability")
            if intent.expiration_time is None or datetime.fromisoformat(intent.expiration_time.replace("Z","+00:00")).timestamp()*1000 > envelope.expires_at:
                raise PermissionError("Pending entry must expire within mandate duration")
        if observation.account.margin_mode != "ACCOUNT_MARGIN_MODE_RETAIL_HEDGING":
            raise PermissionError("New autonomous exposure requires verified hedging attribution")
        if any(p.symbol == symbol for p in positions) and "add_exposure" not in envelope.risk_increase_permissions:
            raise PermissionError("Adding to existing exposure was not authorized")
        if any(p.symbol == symbol and side_of(p) != intent.side for p in observation.positions):
            if "hedge" not in envelope.risk_increase_permissions:
                raise PermissionError("Offsetting exposure is new risk; hedge permission required")
        assert intent.volume is not None
        entry = (price.ask if intent.side == "buy" else price.bid) if intent.order_type == "market" else intent.price
        assert entry is not None
        if intent.stop_loss is None or (intent.side == "buy" and intent.stop_loss >= entry) or (intent.side == "sell" and intent.stop_loss <= entry):
            raise ValueError("New exposure requires directionally valid protection")
        risk = stop_risk(intent.side,entry,intent.stop_loss,intent.volume,spec,price,envelope.currency)
        amount = notional(entry,intent.volume,spec,envelope.currency)
    elif target is not None:
        pending = intent.operation in {"modify_order", "cancel_order"}
        try:
            previous = item_risk(target,spec,price,envelope.currency,pending=pending)
        except ValueError:
            if intent.operation not in {"close_position","cancel_order"}:
                raise
            previous = Decimal(0)  # Closure reduces even unquantifiable exposure.
        if intent.operation in {"modify_position", "modify_order"}:
            changed = target.model_copy(update={"stop_loss":intent.stop_loss if intent.stop_loss is not None else target.stop_loss,
                "open_price":intent.price if intent.price is not None else target.open_price,
                "volume":intent.volume if intent.volume is not None else target.volume})
            if intent.operation == "modify_position" and intent.volume is not None:
                raise ValueError("Position size cannot be changed through stop modification")
            entry = changed.open_price if pending else (price.bid if side_of(changed) == "buy" else price.ask)
            if changed.stop_loss is not None and entry is not None and (
                    (side_of(changed) == "buy" and changed.stop_loss >= entry)
                    or (side_of(changed) == "sell" and changed.stop_loss <= entry)):
                raise ValueError("Modified protective stop is beyond the executable broker price")
            risk = item_risk(changed,spec,price,envelope.currency,pending=pending)
            if pending:
                if changed.open_price is None or changed.volume is None or target.open_price is None or target.volume is None:
                    raise ValueError("Pending exposure is incomplete")
                amount = max(Decimal(0), notional(changed.open_price,changed.volume,spec,envelope.currency)
                    - notional(target.open_price,target.volume,spec,envelope.currency))
            if risk > previous and "widen_stop" not in envelope.risk_increase_permissions:
                raise PermissionError("Increasing protective loss was not authorized")
            if changed.volume and target.volume and changed.volume > target.volume and "add_exposure" not in envelope.risk_increase_permissions:
                raise PermissionError("Increasing pending volume was not authorized")
        elif intent.operation == "close_position" and intent.volume is not None:
            if target.volume is None or intent.volume > target.volume:
                raise ValueError("Partial close exceeds current position")
            remaining = target.volume-intent.volume
            if remaining and (remaining < spec.min_volume or remaining % spec.volume_step):
                raise ValueError("Partial close leaves an invalid broker volume")
            risk = previous * remaining / target.volume
    increasing = intent.operation == "open" or risk > previous or amount > 0
    if mandate.status == "NEEDS_ATTENTION" and not mandate.finish_pending:
        raise PermissionError("Manual drift or incomplete evidence requires user intervention before mutation")
    if increasing and (mandate.status != "ACTIVE" or not envelope.start_at <= now < envelope.expires_at):
        raise PermissionError("Mandate is not active within its authorized time")
    if increasing and not mandate.pnl_complete:
        raise PermissionError("Authoritative mission P&L is incomplete")
    if not increasing and mandate.status not in {"ACTIVE", "PAUSED", "RISK_STOPPED", "NEEDS_ATTENTION"} and not mandate.finish_pending:
        raise PermissionError("Mandate management authority ended")
    if mandate.finish_pending:
        behavior = {"target":envelope.target_behavior,"expiry":envelope.expiry_behavior,
            "breach":envelope.breach_behavior,"emergency":envelope.emergency_behavior}.get(mandate.finish_kind or "breach",envelope.breach_behavior)
        if intent.operation not in {"cancel_order", "close_position"}:
            raise PermissionError("Only pre-authorized finish reduction remains")
        if (intent.operation == "cancel_order" and not behavior.cancel_pending) or (intent.operation == "close_position" and not behavior.close_positions):
            raise PermissionError("Finish behavior does not authorize this action")
    pnl = mandate.realized_pnl + mandate.unrealized_pnl
    remaining_loss = envelope.max_mission_loss + pnl
    today = datetime.now(timezone.utc).date().isoformat()
    if increasing and (remaining_loss <= 0 or (envelope.max_daily_loss is not None and mandate.daily_pnl.get(today,Decimal(0))+mandate.unrealized_pnl <= -envelope.max_daily_loss)
            or (envelope.max_drawdown is not None and mandate.peak_pnl-pnl >= envelope.max_drawdown)):
        raise PermissionError("Hard mission loss/daily loss/drawdown limit reached")
    open_risk: Decimal | None
    try:
        open_risk = sum((item_risk(p,specs[p.symbol],prices[p.symbol],envelope.currency) for p in positions),Decimal(0))
        open_risk += sum((item_risk(p,specs[p.symbol],prices[p.symbol],envelope.currency,pending=True) for p in orders),Decimal(0))
    except ValueError:
        if increasing:
            raise
        open_risk = None
    account_risk: Decimal | None = None
    account_notional = Decimal(0)
    mission_notional = Decimal(0)
    if increasing:
        account_risk = sum((item_risk(p,specs[p.symbol],prices[p.symbol],envelope.currency) for p in observation.positions),Decimal(0))
        account_risk += sum((item_risk(p,specs[p.symbol],prices[p.symbol],envelope.currency,pending=True) for p in observation.orders),Decimal(0))
        account_notional = sum((notional(prices[p.symbol].bid,p.volume or Decimal(0),specs[p.symbol],envelope.currency)
            for p in [*observation.positions,*observation.orders]),Decimal(0))
        mission_notional = sum((notional(prices[p.symbol].bid,p.volume or Decimal(0),specs[p.symbol],envelope.currency)
            for p in [*positions,*orders]),Decimal(0))
    return RiskAssessment(account_id=envelope.account_id, mandate_id=mandate.id, mandate_revision=mandate.revision,
        fetched_at=observation.fetched_at, fingerprint=fingerprint, risk_increasing=increasing,
        proposed_risk=risk, incremental_risk=max(Decimal(0),risk-previous),open_risk=open_risk,
        account_open_risk=account_risk, mission_pnl=pnl,remaining_loss=remaining_loss,
        position_count=len(positions),order_count=len(orders),proposed_notional=amount,
        proposed_margin=proposed_margin,margin_usage=observation.account.margin,account_equity=observation.account.equity,
        account_notional=account_notional,mission_notional=mission_notional)
