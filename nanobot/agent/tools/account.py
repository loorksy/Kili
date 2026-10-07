"""Read-only connected broker account evidence."""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext
from nanobot.trading.metaapi import MetaApiClient


class AccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["connection", "state", "positions", "orders", "symbols", "specification", "price"]
    symbol: str | None = None


class AccountTool(Tool):
    action_class = "read"

    def __init__(self, client: MetaApiClient):
        self.client = client

    @property
    def name(self) -> str:
        return "account"

    @property
    def description(self) -> str:
        return "Read MetaApi connection/account state, positions, orders, exact broker symbols/specifications and broker-side prices. Distinct from OANDA analysis data."

    @property
    def parameters(self) -> dict[str, Any]:
        return AccountRequest.model_json_schema()

    @property
    def read_only(self) -> bool:
        return True

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.config.integrations.metaapi is not None

    @classmethod
    def create(cls, ctx: ToolContext) -> AccountTool:
        connection = ctx.config.integrations.metaapi
        assert connection is not None
        return cls(MetaApiClient(connection))

    async def execute(self, **kwargs: Any) -> str:
        request = AccountRequest.model_validate(kwargs)
        if request.operation == "connection":
            return (await self.client.connection_state()).model_dump_json()
        if request.operation == "state":
            return (await self.client.account()).model_dump_json()
        if request.operation == "positions" or request.operation == "orders":
            return json.dumps([item.model_dump(mode="json") for item in await self.client.items(request.operation)])
        if request.operation == "symbols":
            return json.dumps(await self.client.symbols())
        if not request.symbol:
            raise ValueError("Exact broker symbol is required")
        if request.operation == "specification":
            return (await self.client.specification(request.symbol)).model_dump_json()
        return (await self.client.price(request.symbol)).model_dump_json()
