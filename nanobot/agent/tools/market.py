"""Structured evidence from the selected authenticated broker account."""
from __future__ import annotations

import json
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_serializer, field_validator

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.market.broker import BrokerMarket
from nanobot.trading.accounts import TradingAccounts


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
        if any(not price.is_finite() or price < Decimal("1e-18") or price > Decimal("1e30") or len(price.as_tuple().digits) > 60 for price in values):
            raise ValueError("Prices must be finite, between 1e-18 and 1e30, with at most 60 significant digits")
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
    account_id: str | None = None


class MarketTool(Tool):
    action_class = "read"
    _scopes = {"core", "subagent"}

    def __init__(self, client: BrokerMarket, accounts: TradingAccounts | None = None):
        self.client = client
        self.accounts = accounts

    @property
    def name(self) -> str:
        return "market"

    @property
    def description(self) -> str:
        return ("Selected broker account market evidence through MetaApi SDK. Start with capabilities or instruments if unsure. "
                "For quote/candles pass the exact instrument from this account's advertised symbol catalog; "
                "all its symbols are available, including broker suffixes. Never guess or strip suffixes. "
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
        return bool(ctx.config.integrations.broker_accounts())

    @classmethod
    def create(cls, ctx: ToolContext) -> MarketTool:
        accounts = TradingAccounts(ctx.config.integrations)
        return cls(BrokerMarket(accounts.client()), accounts)

    async def execute(self, **kwargs: Any) -> str:
        request = _MarketRequest.model_validate(kwargs)
        context = current_request_context()
        client = BrokerMarket(self.accounts.client(request.account_id,
            principal=context.session_key if context else None)) if self.accounts else self.client
        source = "metaapi"
        if request.operation == "recommendation":
            if request.recommendation is None:
                raise ValueError("A structured recommendation object is required")
            data = request.recommendation.model_dump(mode="json")
            data["source"] = source
            data["account_id"] = client.connection.account_id
            if request.recommendation.chart_id:
                from nanobot.agent.tools.chart import current_chart_actor
                from nanobot.charts.state import ChartService
                chart = ChartService().get(request.recommendation.chart_id, current_chart_actor())
                if source == "metaapi" and (chart.provider != source or chart.account_id != client.connection.account_id):
                    raise ValueError("Recommendation chart belongs to another market source/account")
                data["session_key"] = chart.session_key
            return "```market_recommendation\n" + json.dumps(data) + "\n```"
        timeframes = await client.timeframes()
        if request.operation == "capabilities":
            return json.dumps({"operations": ["instruments", "quote", "candles", "timeframes", "recommendation"],
                "examples": [{"operation": "instruments"}],
                "timeframes": timeframes, "source": source, "execution_authority": False})
        if request.operation == "instruments":
            return json.dumps([item.model_dump(mode="json") for item in await client.instruments()])
        if request.operation == "timeframes":
            return json.dumps(timeframes)
        symbol = request.provider_instrument
        canonical = request.canonical_instrument
        if request.instrument or not symbol or not canonical:
            query = request.instrument or symbol or canonical
            if not query:
                raise ValueError("Supply an exact broker instrument, or query instruments first")
            instruments = await client.instruments()
            # Match advertised aliases only, never infer broker symbols or execution mappings.
            matches = [item for item in instruments if query.upper() in {
                item.name.upper(), item.display_name.upper(),
                item.canonical_instrument.upper()}]
            if len(matches) != 1:
                raise ValueError("Instrument unavailable or ambiguous; use instruments to select its exact name")
            symbol = matches[0].name
            canonical = matches[0].canonical_instrument
        assert symbol is not None and canonical is not None
        timeframe = {"D1": "D", "W1": "W", "MN1": "M"}.get(request.timeframe.upper(), request.timeframe.upper())
        if request.operation == "candles" and timeframe not in timeframes:
            raise ValueError("Unsupported timeframe; use timeframes to discover available values")
        if request.operation == "quote":
            return (await client.quote(symbol, canonical)).model_dump_json()
        if request.operation == "candles":
            data = await client.candles(symbol, canonical,
                                             timeframe, count=request.count, before=request.before)
            return json.dumps([item.model_dump(mode="json") for item in data])
        raise ValueError("Unknown market operation")
