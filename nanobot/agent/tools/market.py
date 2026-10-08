"""Structured OANDA evidence tools, registered only with an explicit connection."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext
from nanobot.market.oanda import GRANULARITIES, OandaClient


class MarketRecommendation(BaseModel):
    """Display-only analysis. Never grants financial execution authority."""
    model_config = ConfigDict(extra="forbid")
    instrument: str = Field(min_length=1, max_length=80)
    intent: Literal["BUY", "SELL", "WAIT", "AVOID", "WATCH"]
    timeframe: str = Field(default="H1", max_length=20)
    summary: str = Field(min_length=1, max_length=2000)
    entry: list[Decimal] = Field(default_factory=list, max_length=2)
    stop_loss: Decimal | None = None
    targets: list[Decimal] = Field(default_factory=list, max_length=5)
    evidence_time: str | None = Field(default=None, max_length=80)
    chart_id: str | None = Field(default=None, pattern=r"^chart_[a-f0-9]{32}$")

    @field_serializer("entry", "targets", "stop_loss", when_used="json")
    def price_strings(self, value: list[Decimal] | Decimal | None) -> list[str] | str | None:
        if isinstance(value, list):
            return [format(price, "f") for price in value]
        return format(value, "f") if value is not None else None

    @field_validator("entry", "targets", "stop_loss")
    @classmethod
    def prices(cls, value: list[Decimal] | Decimal | None) -> list[Decimal] | Decimal | None:
        values = value if isinstance(value, list) else [value] if value is not None else []
        if any(not price.is_finite() or price <= 0 or price > Decimal("1e30") for price in values):
            raise ValueError("Prices must be positive, finite and bounded")
        return value


class _MarketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["capabilities", "instruments", "quote", "candles", "timeframes", "recommendation"]
    provider_instrument: str | None = None
    canonical_instrument: str | None = None
    instrument: str | None = Field(default=None, max_length=80)
    recommendation: MarketRecommendation | None = None
    timeframe: str = "H1"
    count: int = Field(default=500, ge=1, le=5000)
    before: str | None = None


class MarketTool(Tool):
    action_class = "read"
    _scopes = {"core", "subagent"}

    def __init__(self, client: OandaClient):
        self.client = client

    @property
    def name(self) -> str:
        return "market"

    @property
    def description(self) -> str:
        return ("OANDA analysis evidence. Start with capabilities or instruments if unsure. For quote/candles "
                "pass instrument (e.g. XAUUSD or XAU_USD); it is resolved against this account's actual instrument catalog. "
                "Alternatively pass provider_instrument and canonical_instrument. Timeframes: H1/H4/D (D1 also accepted). "
                "Use recommendation with a structured recommendation object for an actionable analysis or explicit user request "
                "for a recommendation; BUY/SELL/WAIT/WATCH/AVOID renders a card. Return its market_recommendation fence "
                "unchanged. Include a chart_id only from a chart you can access. Do not send a recommendation card for "
                "greetings, a simple quote, or every monitoring tick. Prices need recent evidence; never imply guaranteed "
                "profit or executed orders. Analysis is separate from broker execution and approval.")

    @property
    def read_only(self) -> bool:
        return True

    @property
    def parameters(self) -> dict[str, Any]:
        return _MarketRequest.model_json_schema()

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.config.integrations.oanda is not None

    @classmethod
    def create(cls, ctx: ToolContext) -> MarketTool:
        connection = ctx.config.integrations.oanda
        assert connection is not None
        return cls(OandaClient(connection))

    async def execute(self, **kwargs: Any) -> str:
        request = _MarketRequest.model_validate(kwargs)
        if request.operation == "capabilities":
            return json.dumps({"operations": ["instruments", "quote", "candles", "timeframes", "recommendation"],
                "examples": [{"operation": "quote", "instrument": "XAUUSD"},
                             {"operation": "candles", "instrument": "XAU_USD", "timeframe": "H4", "count": 200}],
                "timeframes": GRANULARITIES, "source": "oanda", "execution_authority": False})
        if request.operation == "recommendation":
            if request.recommendation is None:
                raise ValueError("A structured recommendation object is required")
            data = request.recommendation.model_dump(mode="json")
            if request.recommendation.chart_id:
                from nanobot.agent.tools.chart import current_chart_actor
                from nanobot.charts.state import ChartService
                chart = ChartService().get(request.recommendation.chart_id, current_chart_actor())
                data["session_key"] = chart.session_key
            return "```market_recommendation\n" + json.dumps(data) + "\n```"
        if request.operation == "instruments":
            return json.dumps([item.model_dump(mode="json") for item in await self.client.instruments()])
        if request.operation == "timeframes":
            return json.dumps(GRANULARITIES)
        symbol = request.provider_instrument
        canonical = request.canonical_instrument
        if request.instrument or not symbol or not canonical:
            query = request.instrument or symbol or canonical
            if not query:
                raise ValueError("Supply instrument (e.g. XAUUSD), or query instruments first")
            instruments = await self.client.instruments()
            # Match advertised aliases only, never infer broker symbols or execution mappings.
            matches = [item for item in instruments if query.upper() in {
                item.name.upper(), item.name.replace("_", "").upper(), item.display_name.upper()}]
            if len(matches) != 1:
                raise ValueError("Instrument unavailable or ambiguous; use instruments to select its exact name")
            symbol = matches[0].name
            canonical = symbol
        assert symbol is not None and canonical is not None
        timeframe = {"D1": "D", "W1": "W", "MN1": "M"}.get(request.timeframe.upper(), request.timeframe.upper())
        if request.operation == "candles" and timeframe not in GRANULARITIES:
            raise ValueError("Unsupported timeframe; use timeframes to discover available values")
        if request.operation == "quote":
            return (await self.client.quote(symbol, canonical)).model_dump_json()
        if request.operation == "candles":
            data = await self.client.candles(symbol, canonical,
                                             timeframe, count=request.count, before=request.before)
            return json.dumps([item.model_dump(mode="json") for item in data])
        raise ValueError("Unknown market operation")
