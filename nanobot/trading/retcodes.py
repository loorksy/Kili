"""Bounded provider diagnostics and conservative trade-outcome classification."""
from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter


class ValidationDetail(BaseModel):
    model_config = ConfigDict(extra="forbid")
    parameter: str | None = Field(default=None, max_length=300)
    message: str | None = Field(default=None, max_length=300)


class ProviderDiagnostic(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: str = Field(max_length=80)
    string_code: str | None = Field(default=None, max_length=80)
    numeric_code: int | None = None
    message: str | None = Field(default=None, max_length=300)
    details: list[ValidationDetail] = Field(default_factory=list, max_length=10)


_REASONS = {
    "INVALID_EXPIRATION": ("Broker rejected the order expiration time/mode.", "الوسيط رفض وقت أو نوع انتهاء صلاحية الأمر."),
    "INVALID_FILL": ("Order filling mode is unsupported for this symbol.", "نوع تنفيذ الأمر غير مدعوم لهذا الرمز."),
    "INVALID_STOPS": ("Invalid stop loss or take profit.", "وقف الخسارة أو جني الربح غير صالح."),
    "INVALID_PRICE": ("Invalid order price for the current market.", "سعر الأمر غير صالح بالنسبة للسوق الحالي."),
    "INVALID_VOLUME": ("Lot size violates broker minimum, maximum or step.", "حجم اللوت يخالف حدود الوسيط أو خطوة الحجم."),
    "MARKET_CLOSED": ("Market is closed for this symbol.", "السوق مغلق لهذا الرمز حالياً."),
    "TRADE_DISABLED": ("Trading is disabled for this account or symbol.", "التداول معطّل لهذا الحساب أو الرمز."),
    "NO_MONEY": ("Insufficient free margin.", "الهامش المتاح غير كافٍ."),
    "INVALID_ORDER": ("Order type is not allowed by the broker.", "نوع الأمر غير مسموح من الوسيط."),
    "LIMIT_ORDERS": ("Pending order limit reached.", "تم بلوغ الحد الأقصى للأوامر المعلّقة."),
    "LIMIT_VOLUME": ("Symbol volume limit reached.", "تم بلوغ الحد الأقصى للحجم على الرمز."),
    "REJECT": ("Broker rejected the request.", "الوسيط رفض الطلب."),
    "SERVER_DISABLES_AT": ("Server has disabled automated trading.", "التداول الآلي معطّل على الخادم."),
    "CLIENT_DISABLES_AT": ("Terminal has disabled automated trading.", "التداول الآلي معطّل على المنصّة."),
}
_NUMERIC = {10006: "REJECT", 10014: "INVALID_VOLUME", 10015: "INVALID_PRICE", 10016: "INVALID_STOPS",
            10017: "TRADE_DISABLED", 10018: "MARKET_CLOSED", 10019: "NO_MONEY", 10022: "INVALID_EXPIRATION",
            10026: "SERVER_DISABLES_AT", 10027: "CLIENT_DISABLES_AT", 10030: "INVALID_FILL",
            10033: "LIMIT_ORDERS", 10034: "LIMIT_VOLUME"}
_SUCCESS = {"ERR_NO_ERROR", "TRADE_RETCODE_DONE", "TRADE_RETCODE_PLACED", "TRADE_RETCODE_DONE_PARTIAL", "TRADE_RETCODE_NO_CHANGES"}
_UNCERTAIN = {"TRADE_RETCODE_TIMEOUT", "TRADE_RETCODE_CONNECTION", "TRADE_RETCODE_PRICE_OFF", "TRADE_RETCODE_REQUOTE",
              "ERR_TRADE_TIMEOUT", "ERR_NO_CONNECTION", "ERR_OFF_QUOTES", "ERR_REQUOTE"}
_URL = re.compile(r"(?:https?|wss?)://\S+", re.I)
_JWT = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+")
_AUTH = re.compile(r"(?i)(?:(?:auth[-_]?token|authorization|api[-_]?key|password)\s*[:=]\s*(?:bearer\s+)?|bearer\s+)\S+")


def safe_text(value: object, token: str) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.replace(token, "[redacted]") if token else value
    value = _AUTH.sub("[redacted]", _JWT.sub("[redacted]", _URL.sub("[url]", value)))
    return " ".join(value.split())[:300]


def provider_diagnostic(exc: Exception, token: str) -> ProviderDiagnostic:
    """Only allowlisted scalar exception fields cross the private SDK boundary."""
    code = safe_text(getattr(exc, "stringCode", None), token)
    if code is not None and not re.fullmatch(r"[A-Z0-9_]{1,80}", code):
        code = None
    numeric = getattr(exc, "numericCode", None)
    details: list[ValidationDetail] = []
    raw = getattr(exc, "details", None)
    if isinstance(raw, list):
        for item in TypeAdapter(list[object]).validate_python(raw)[:10]:
            if isinstance(item, dict):
                detail = TypeAdapter(dict[str, object]).validate_python(item)
                details.append(ValidationDetail(parameter=safe_text(detail.get("parameter"), token),
                                                message=safe_text(detail.get("message"), token)))
    return ProviderDiagnostic(kind=type(exc).__name__[:80], string_code=code,
        numeric_code=numeric if isinstance(numeric, int) and not isinstance(numeric, bool) else None,
        message=safe_text(exc.args[0] if exc.args else None, token), details=details)


def trade_outcome(code: str | None, numeric: int | None = None, *, kind: str | None = None) -> Literal["SUCCEEDED", "FAILED", "UNCERTAIN"]:
    if code in _SUCCESS:
        return "SUCCEEDED"
    if code in _UNCERTAIN or numeric in {10004, 10012, 10021, 10031, 128, 6, 136, 138}:
        return "UNCERTAIN"
    if code and code.removeprefix("TRADE_RETCODE_") in {*_REASONS, "ERROR", "CANCEL", "INVALID", "PRICE_CHANGED",
            "TOO_MANY_REQUESTS", "LOCKED", "FROZEN", "ONLY_REAL", "INVALID_CLOSE_VOLUME", "POSITION_CLOSED",
            "CLOSE_ORDER_EXIST", "LIMIT_POSITIONS", "LONG_ONLY", "SHORT_ONLY", "CLOSE_ONLY", "FIFO_CLOSE", "HEDGE_PROHIBITED"}:
        return "FAILED"
    if numeric in _NUMERIC or kind in {"ValidationException", "ForbiddenException", "UnauthorizedException", "NotFoundException"}:
        return "FAILED"
    return "UNCERTAIN"


def rejection_reason(error: ProviderDiagnostic) -> tuple[str, str]:
    key = (error.string_code or "").removeprefix("TRADE_RETCODE_")
    if key not in _REASONS:
        key = _NUMERIC.get(error.numeric_code or 0, key)
    if key in _REASONS:
        return _REASONS[key]
    if error.kind == "ValidationException":
        return "MetaApi rejected the request format; inspect validation details.", "MetaApi رفض صيغة الطلب؛ راجع تفاصيل التحقق."
    if error.kind in {"ForbiddenException", "UnauthorizedException"}:
        return "MetaApi access is denied or credentials are invalid.", "صلاحية MetaApi مرفوضة أو بيانات الاتصال غير صالحة."
    if error.kind == "NotFoundException":
        return "MetaApi account or resource was not found.", "حساب أو مورد MetaApi غير موجود."
    code = error.string_code or error.kind
    return f"Provider response: {code}; reconcile if the outcome is uncertain.", f"رد مزوّد التنفيذ: {code}؛ يلزم التحقق إذا كانت النتيجة غير مؤكدة."


def diagnostic_result(error: ProviderDiagnostic) -> dict[str, JsonValue]:
    en, ar = rejection_reason(error)
    return {"error_kind": error.kind, "string_code": error.string_code,
            "numeric_code": error.numeric_code, "provider_message": error.message,
            "details": [detail.model_dump(mode="json") for detail in error.details],
            "reason_en": en, "reason_ar": ar}
