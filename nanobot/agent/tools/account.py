"""Read-only connected broker account evidence."""
from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.trading.accounts import TradingAccounts
from nanobot.trading.metaapi import MetaApiClient


class AccountRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["list_accounts", "select_account", "connection", "state", "positions", "orders", "symbols", "specification", "price"]
    symbol: str | None = None
    account_id: str | None = None


class AccountTool(Tool):
    action_class = "read"

    def __init__(self, client: MetaApiClient, accounts: TradingAccounts | None = None):
        self.client = client
        self.accounts = accounts

    @property
    def name(self) -> str:
        return "account"

    @property
    def description(self) -> str:
        return ("List/select connected broker accounts in this conversation, or read synchronized MetaApi account state, "
                "positions, orders, exact broker symbols/specifications and broker-side prices. "
                "Account switching never moves an existing proposal, mandate or effect to a different account.")

    @property
    def parameters(self) -> dict[str, Any]:
        return AccountRequest.model_json_schema()

    @property
    def read_only(self) -> bool:
        return False  # Selection is reversible conversation state, never a trade.

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return bool(ctx.config.integrations.broker_accounts())

    @classmethod
    def create(cls, ctx: ToolContext) -> AccountTool:
        accounts = TradingAccounts(ctx.config.integrations)
        return cls(accounts.client(), accounts)

    async def execute(self, **kwargs: Any) -> str:
        request = AccountRequest.model_validate(kwargs)
        context = current_request_context()
        principal = context.session_key if context else None
        if request.operation in {"list_accounts", "select_account"}:
            if self.accounts is None or principal is None:
                raise PermissionError("Account selection requires a configured conversation")
            if request.operation == "select_account":
                if request.account_id is None:
                    raise ValueError("Exact account ID is required")
                self.accounts.select(principal, request.account_id)
            return json.dumps(self.accounts.public_accounts(principal))
        client = self.accounts.client(request.account_id, principal=principal) if self.accounts else self.client
        if request.operation == "connection":
            return (await client.connection_state()).model_dump_json()
        if request.operation == "state":
            return (await client.account()).model_dump_json()
        if request.operation == "positions" or request.operation == "orders":
            return json.dumps([item.model_dump(mode="json") for item in await client.items(request.operation)])
        if request.operation == "symbols":
            return json.dumps(await client.symbols())
        if not request.symbol:
            raise ValueError("Exact broker symbol is required")
        if request.operation == "specification":
            return (await client.specification(request.symbol)).model_dump_json()
        return (await client.price(request.symbol)).model_dump_json()
