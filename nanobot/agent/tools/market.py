"""Structured OANDA evidence tools, registered only with an explicit connection."""
from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext
from nanobot.market.oanda import GRANULARITIES, OandaClient


class _MarketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: str
    provider_instrument: str | None = None
    canonical_instrument: str | None = None
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
        return "OANDA market evidence: instruments, quote, candles or timeframes. Analysis data is distinct from broker execution data."

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
        if request.operation == "instruments":
            return json.dumps([item.model_dump(mode="json") for item in await self.client.instruments()])
        if request.operation == "timeframes":
            return json.dumps(GRANULARITIES)
        if not request.provider_instrument or not request.canonical_instrument:
            raise ValueError("Quote/candles require explicit provider and canonical instruments")
        if request.operation == "quote":
            return (await self.client.quote(request.provider_instrument, request.canonical_instrument)).model_dump_json()
        if request.operation == "candles":
            data = await self.client.candles(request.provider_instrument, request.canonical_instrument,
                                             request.timeframe, count=request.count, before=request.before)
            return json.dumps([item.model_dump(mode="json") for item in data])
        raise ValueError("Unknown market operation")
