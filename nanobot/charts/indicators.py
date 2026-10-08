"""Bounded, deterministic indicator data language. No eval, code or I/O primitives."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal, localcontext
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from nanobot.market.models import Candle
from nanobot.session.records import RecordStore, RuntimeRecord

Scalar = Decimal | None


class Parameter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default: Decimal
    minimum: Decimal
    maximum: Decimal

    @model_validator(mode="after")
    def bounds(self) -> Parameter:
        if not all(x.is_finite() for x in (self.default, self.minimum, self.maximum)):
            raise ValueError("Parameters must be finite")
        if not self.minimum <= self.default <= self.maximum:
            raise ValueError("Invalid parameter bounds")
        return self


class Node(BaseModel):
    model_config = ConfigDict(extra="forbid")
    op: Literal["input", "constant", "parameter", "add", "subtract", "multiply", "divide", "gt", "lt", "equal", "and", "or", "choose", "mean", "min", "max", "std", "ema", "shift", "cross_above", "cross_below", "swing_high", "swing_low"]
    inputs: list[int] = Field(default_factory=list, max_length=3)
    field: Literal["open", "high", "low", "close", "volume"] = "close"
    value: Decimal = Decimal(0)
    parameter: str | None = Field(default=None, max_length=80)
    window_parameter: str | None = Field(default=None, max_length=80)
    offset_parameter: str | None = Field(default=None, max_length=80)
    window: int = Field(default=14, ge=1, le=512)
    offset: int = Field(default=0, ge=0, le=512)

    @model_validator(mode="after")
    def finite(self) -> Node:
        if not self.value.is_finite():
            raise ValueError("Indicator constants must be finite")
        return self


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    node: int = Field(ge=0)
    kind: Literal["line", "histogram", "marker", "state", "band"] = "line"
    color: str = Field(default="#38bdf8", pattern=r"^#[0-9a-fA-F]{6}$")


class IndicatorDefinition(BaseModel):
    model_config = ConfigDict(extra="forbid")
    definition_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=80)
    description: str = Field(default="", max_length=2000)
    parameters: dict[str, Parameter] = Field(default_factory=dict, max_length=16)
    nodes: list[Node] = Field(min_length=1, max_length=64)
    outputs: list[Output] = Field(min_length=1, max_length=8)
    pane: Literal["main", "separate"] = "main"

    @model_validator(mode="after")
    def graph(self) -> IndicatorDefinition:
        unary = {"mean", "min", "max", "std", "ema", "shift", "swing_high", "swing_low"}
        binary = {"add", "subtract", "multiply", "divide", "gt", "lt", "equal", "and", "or", "cross_above", "cross_below"}
        for index, node in enumerate(self.nodes):
            arity = 1 if node.op in unary else 2 if node.op in binary else 3 if node.op == "choose" else 0
            if len(node.inputs) != arity or any(ref < 0 or ref >= index for ref in node.inputs):
                raise ValueError("Nodes must be an acyclic, ordered graph with correct arity")
            for reference in (node.window_parameter, node.offset_parameter):
                if reference is not None and reference not in self.parameters:
                    raise ValueError("Unknown window parameter")
            if node.op == "parameter" and node.parameter not in self.parameters:
                raise ValueError("Unknown indicator parameter")
        if any(output.node >= len(self.nodes) for output in self.outputs):
            raise ValueError("Unknown output node")
        if len({o.name for o in self.outputs}) != len(self.outputs):
            raise ValueError("Output names must be unique")
        return self


def evaluate(definition: IndicatorDefinition, candles: list[Candle],
             parameters: dict[str, Decimal] | None = None) -> dict[str, list[Scalar]]:
    if len(candles) > 5000:
        raise ValueError("Indicator input exceeds 5000 candles")
    supplied = parameters or {}
    if supplied.keys() - definition.parameters.keys():
        raise ValueError("Unknown indicator parameter")
    values = {name: supplied.get(name, p.default) for name, p in definition.parameters.items()}
    for name, value in values.items():
        bounds = definition.parameters[name]
        if not value.is_finite() or not bounds.minimum <= value <= bounds.maximum:
            raise ValueError("Indicator parameter outside validated bounds")
    effective: list[Node] = []
    for node in definition.nodes:
        copy = node.model_copy(deep=True)
        for field, reference in (("window", node.window_parameter), ("offset", node.offset_parameter)):
            if reference is not None:
                value = values[reference]
                if value != int(value) or not (1 if field == "window" else 0) <= value <= 512:
                    raise ValueError("Window parameters must be bounded integers")
                if field == "window":
                    copy.window = int(value)
                else:
                    copy.offset = int(value)
        effective.append(copy)
    work = len(candles) * sum(node.window + node.offset + 1 if node.op in {"mean", "min", "max", "std", "swing_high", "swing_low"} else 1 for node in effective)
    if work > 2_000_000:
        raise ValueError("Indicator calculation exceeds bounded work budget")
    series: list[list[Scalar]] = []
    with localcontext() as context:
        context.prec = 28
        for node in effective:
            result: list[Scalar] = []
            args = [series[ref] for ref in node.inputs]
            for i, candle in enumerate(candles):
                value: Scalar = None
                if node.op == "input":
                    raw = getattr(candle, node.field)
                    value = Decimal(raw) if raw is not None else None
                elif node.op == "constant":
                    value = node.value
                elif node.op == "parameter":
                    value = values[node.parameter or ""]
                elif node.op == "shift":
                    value = args[0][i - node.offset] if i >= node.offset else None
                elif node.op in {"mean", "min", "max", "std"}:
                    window = args[0][max(0, i - node.window + 1):i + 1]
                    valid = [v for v in window if v is not None]
                    if len(valid) == node.window:
                        mean = sum(valid, Decimal(0)) / len(valid)
                        value = mean if node.op == "mean" else min(valid) if node.op == "min" else max(valid) if node.op == "max" else (sum(((v - mean) ** 2 for v in valid), Decimal(0)) / len(valid)).sqrt()
                elif node.op == "ema":
                    current = args[0][i]
                    previous = result[-1] if result else None
                    if current is not None:
                        alpha = Decimal(2) / (node.window + 1)
                        value = current if previous is None else current * alpha + previous * (1 - alpha)
                elif node.op in {"swing_high", "swing_low"}:
                    # Confirmation occurs NOW; marker value belongs to i-offset, never looks ahead.
                    center = i - node.offset
                    if center >= node.window:
                        pivot = args[0][center]
                        neighbors = args[0][center - node.window:center] + args[0][center + 1:i + 1]
                        if pivot is not None and all(v is not None for v in neighbors):
                            valid_neighbors = [v for v in neighbors if v is not None]
                            if all(pivot > v if node.op == "swing_high" else pivot < v for v in valid_neighbors):
                                value = pivot
                else:
                    operands = [arg[i] for arg in args]
                    if all(v is not None for v in operands):
                        valid = [v for v in operands if v is not None]
                        a, b = valid[0], valid[1]
                        if node.op == "add":
                            value = a + b
                        elif node.op == "subtract":
                            value = a - b
                        elif node.op == "multiply":
                            value = a * b
                        elif node.op == "divide":
                            value = a / b if b else None
                        elif node.op == "gt":
                            value = Decimal(a > b)
                        elif node.op == "lt":
                            value = Decimal(a < b)
                        elif node.op == "equal":
                            value = Decimal(a == b)
                        elif node.op == "and":
                            value = Decimal(bool(a) and bool(b))
                        elif node.op == "or":
                            value = Decimal(bool(a) or bool(b))
                        elif node.op == "choose":
                            value = b if a else valid[2]
                        elif node.op in {"cross_above", "cross_below"} and i:
                            previous_a, previous_b = args[0][i - 1], args[1][i - 1]
                            if previous_a is not None and previous_b is not None:
                                value = Decimal(previous_a <= previous_b and a > b if node.op == "cross_above" else previous_a >= previous_b and a < b)
                if value is not None and (not value.is_finite() or abs(value) > Decimal("1e30")):
                    raise ValueError("Indicator produced an invalid or excessive value")
                result.append(value)
            series.append(result)
    return {output.name: series[output.node] for output in definition.outputs}


class CustomIndicator(RuntimeRecord):
    definition: IndicatorDefinition
    definition_hash: str
    indicator_version: int = Field(ge=1)
    family_id: str
    author: str
    source: Literal["CUSTOM", "USER_IMPORTED"] = "CUSTOM"
    scope: Literal["PRIVATE", "SHARED"] = "PRIVATE"
    original_filename: str | None = Field(default=None, max_length=200)
    validation_status: Literal["VALIDATED"] = "VALIDATED"
    test_status: Literal["PASSED"] = "PASSED"
    security_status: Literal["SAFE_IR"] = "SAFE_IR"


class IndicatorRegistry:
    def __init__(self, records: RecordStore[CustomIndicator] | None = None):
        self.records = records or RecordStore("custom_indicators", CustomIndicator)

    def register(self, definition: IndicatorDefinition, author: str, *, family_id: str | None = None,
                 source: Literal["CUSTOM", "USER_IMPORTED"] = "CUSTOM", filename: str | None = None,
                 scope: Literal["PRIVATE", "SHARED"] = "PRIVATE") -> CustomIndicator:
        import uuid
        payload = definition.model_dump(mode="json")
        digest = hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        existing = [r for r in self.records.list() if r.author == author]
        if len(existing) >= 200:
            raise ValueError("Indicator registry quota exceeded")
        family = family_id or "indicator_" + uuid.uuid4().hex
        previous = [r for r in existing if r.family_id == family]
        if family_id and not previous:
            raise PermissionError("Indicator family is outside this scope")
        for record in previous:
            if record.definition_hash == digest and record.scope == scope:
                return record
        fixture = [Candle(canonical_instrument="fixture", provider_instrument="FIXTURE", time=datetime(2026, 1, 1, tzinfo=timezone.utc) + timedelta(hours=i), open=Decimal(i + 1), high=Decimal(i + 2), low=Decimal(i), close=Decimal(i + 1), complete=True, source="fixture", fetched_at=datetime(2026, 1, 1, tzinfo=timezone.utc)) for i in range(600)]
        for data in ([], fixture[:1], fixture[:10], fixture):
            if evaluate(definition, data) != evaluate(definition, data):
                raise ValueError("Indicator must be deterministic")
        version = max((r.indicator_version for r in previous), default=0) + 1
        return self.records.create(CustomIndicator(id=family + "_v" + str(version), family_id=family,
            indicator_version=version, definition=definition, definition_hash=digest, author=author,
            source=source, original_filename=filename, scope=scope))

    def get(self, indicator_id: str, author: str) -> CustomIndicator:
        record = self.records.get(indicator_id)
        if record.author != author and record.scope != "SHARED":
            raise PermissionError("Private indicator belongs to another conversation")
        return record

    def search(self, author: str, query: str = "") -> list[CustomIndicator]:
        return [r for r in self.records.list() if (r.author == author or r.scope == "SHARED") and query.casefold() in (r.definition.name + " " + r.definition.description).casefold()]


class IndicatorInstance(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str = Field(pattern=r"^study_[a-f0-9]{32}$")
    indicator_id: str
    parameters: dict[str, Decimal] = Field(default_factory=dict, max_length=16)
    calc_params: list[float] = Field(default_factory=list, max_length=16)
    pane: Literal["main", "separate"] = "main"
    visible: bool = True
    created_by: str
    revision: int = 0
