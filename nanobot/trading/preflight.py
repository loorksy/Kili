"""Read-only Decimal validation of the exact action against fresh broker terms."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, NoReturn

from nanobot.trading.metaapi import BrokerItem, BrokerPrice, SymbolSpec

if TYPE_CHECKING:
    from nanobot.trading.proposals import TradeIntent


def reject(en: str, ar: str) -> NoReturn:
    raise ValueError(f"{en} / {ar}")


def session_milliseconds(value: str) -> int:
    # The pinned SDK describes hh.mm.ss.SSS; brokers also return hh:mm:ss.SSS.
    parts = value.replace(":", ".").split(".")
    if len(parts) not in {3, 4}:
        raise ValueError("Invalid broker session time")
    hour, minute, second = (int(p) for p in parts[:3])
    millis = int(parts[3].ljust(3, "0")) if len(parts) == 4 else 0
    if not (0 <= hour <= 24 and 0 <= minute < 60 and 0 <= second < 60 and 0 <= millis < 1000):
        raise ValueError("Invalid broker session time")
    if hour == 24 and (minute or second or millis):
        raise ValueError("Invalid broker session boundary")
    return ((hour * 60 + minute) * 60 + second) * 1000 + millis


def validate_market(intent: TradeIntent, spec: SymbolSpec, price: BrokerPrice,
                    now: datetime, target: BrokerItem | None = None) -> None:
    pending = intent.operation == "modify_order" or (intent.operation == "open" and intent.order_type != "market")
    point = spec.point or Decimal(1).scaleb(-spec.digits)
    distance = Decimal(spec.stops_level) * point
    side = intent.side
    if target is not None:
        if "BUY" in target.type.split("_"):
            side = "buy"
        elif "SELL" in target.type.split("_"):
            side = "sell"
        else:
            reject("Broker target direction is unavailable", "اتجاه الأمر أو المركز غير متاح")
    if intent.operation == "open" and spec.order_mode:
        required = "SYMBOL_ORDER_" + intent.order_type.upper()
        if required not in spec.order_mode:
            reject("Broker does not support this order type", "الوسيط لا يدعم نوع الأمر المطلوب")
    if intent.operation in {"open", "modify_order", "modify_position"} and spec.order_mode:
        for configured, required in ((intent.stop_loss, "SYMBOL_ORDER_SL"), (intent.take_profit, "SYMBOL_ORDER_TP")):
            if configured is not None and required not in spec.order_mode:
                reject("Broker does not support this protective order", "الوسيط لا يدعم أمر الحماية المطلوب")
    if intent.operation == "open" and intent.order_type == "market" and spec.filling_modes:
        if not {"SYMBOL_FILLING_FOK", "SYMBOL_FILLING_IOC"}.intersection(spec.filling_modes):
            if spec.execution_mode == "SYMBOL_TRADE_EXECUTION_MARKET":
                reject("No supported market filling mode", "لا يوجد نوع تنفيذ سوقي مدعوم")
    if intent.expiration_time:
        if not pending:
            reject("Expiration is only valid for pending orders", "الانتهاء صالح للأوامر المعلّقة فقط")
        expiry = datetime.fromisoformat(intent.expiration_time.replace("Z", "+00:00"))
        if expiry.tzinfo is None or expiry < now + timedelta(minutes=2):
            reject("Expiration must be timezone-aware and at least two minutes ahead", "الانتهاء يجب أن يتضمن المنطقة الزمنية ويبعد دقيقتين على الأقل")
        if spec.allowed_expiration_modes and "SYMBOL_EXPIRATION_SPECIFIED" not in spec.allowed_expiration_modes:
            reject("Broker does not support specified expiration", "الوسيط لا يدعم وقت الانتهاء المحدد")
    elif pending and intent.operation == "open" and spec.allowed_expiration_modes:
        if "SYMBOL_EXPIRATION_GTC" not in spec.allowed_expiration_modes:
            reject("Broker does not support default GTC expiration; specify an expiry", "الوسيط لا يدعم الانتهاء الافتراضي؛ حدد وقت انتهاء")
    if pending and intent.price is not None:
        kind = target.type if target is not None else "ORDER_TYPE_" + side.upper() + "_" + intent.order_type.upper()
        entry = intent.price
        valid = {"ORDER_TYPE_BUY_LIMIT": entry <= price.ask - distance,
                 "ORDER_TYPE_SELL_LIMIT": entry >= price.bid + distance,
                 "ORDER_TYPE_BUY_STOP": entry >= price.ask + distance,
                 "ORDER_TYPE_SELL_STOP": entry <= price.bid - distance}
        if not valid.get(kind, False):
            reject("Pending price violates broker direction or minimum distance", "سعر الأمر المعلّق يخالف الاتجاه أو المسافة الدنيا")
    else:
        # Protective market stops trigger on the closing side of the spread.
        entry = price.bid if side == "buy" else price.ask
    if intent.operation in {"open", "modify_order", "modify_position"}:
        for level, stop in ((intent.stop_loss, True), (intent.take_profit, False)):
            if level is None:
                continue
            above = (side == "sell") if stop else (side == "buy")
            if (level <= entry if above else level >= entry) or abs(level - entry) < distance:
                reject("Protection violates broker direction or minimum stop distance", "الحماية تخالف الاتجاه أو المسافة الدنيا للوقف")
    if target is not None and intent.operation in {"modify_order", "cancel_order"} and spec.freeze_level:
        market = price.ask if side == "buy" else price.bid
        if target.open_price is None or abs(target.open_price - market) <= Decimal(spec.freeze_level) * point:
            reject("Pending order is within broker freeze distance", "الأمر المعلّق داخل مسافة التجميد لدى الوسيط")
    if spec.trade_sessions is not None and intent.operation != "cancel_order":
        if not price.broker_time:
            reject("Broker session timezone is unavailable", "المنطقة الزمنية لجلسة الوسيط غير متاحة")
        observed = datetime.fromisoformat(price.time.replace("Z", "+00:00")).astimezone(timezone.utc).replace(tzinfo=None)
        broker_time = datetime.fromisoformat(price.broker_time)
        if broker_time.tzinfo is not None:
            broker_time = broker_time.replace(tzinfo=None)
        offset = broker_time - observed
        # Broker clock offsets are minute-aligned; discard transmission jitter.
        offset = timedelta(minutes=round(offset.total_seconds() / 60))
        local = now.astimezone(timezone.utc).replace(tzinfo=None) + offset
        weekdays = ("MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY", "FRIDAY", "SATURDAY", "SUNDAY")
        millis = ((local.hour * 60 + local.minute) * 60 + local.second) * 1000 + local.microsecond // 1000
        sessions = spec.trade_sessions.get(weekdays[local.weekday()]) or []
        previous = spec.trade_sessions.get(weekdays[(local.weekday() - 1) % 7]) or []
        opened = False
        for session in sessions:
            start, end = session_milliseconds(session.from_time), session_milliseconds(session.to_time)
            opened |= start <= millis <= end if start <= end else millis >= start
        for session in previous:
            start, end = session_milliseconds(session.from_time), session_milliseconds(session.to_time)
            opened |= start > end and millis <= end
        if not opened:
            reject("Market is closed for this symbol", "السوق مغلق لهذا الرمز حالياً")
