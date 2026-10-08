"""Fixed MetaApi operations through the official dependency-isolated SDK.

An explicitly injected HTTP transport remains a deterministic fixture seam;
the gateway never falls back to manual REST when SDK connection fails.
"""
from __future__ import annotations

import asyncio
import json
import re
from decimal import Decimal
from typing import Literal
from urllib.parse import quote, unquote

import httpx
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError

from nanobot.market.models import Connection
from nanobot.market.provider import ProviderUnavailableError, parse_provider
from nanobot.security.actions import ActionStore, Effect, current_authorized_action
from nanobot.security.network import PinnedDNSAsyncTransport, httpx_env_proxy_mounts
from nanobot.security.secrets import SecretStore


class AccountState(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, allow_inf_nan=False)
    broker: str
    currency: str
    balance: Decimal
    equity: Decimal
    margin: Decimal = Decimal(0)
    free_margin: Decimal = Field(default=Decimal(0), alias="freeMargin")
    trade_allowed: bool = Field(default=False, alias="tradeAllowed")
    margin_mode: str | None = Field(default=None, alias="marginMode")
    platform: str | None = None


class BrokerItem(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, allow_inf_nan=False)
    id: str
    symbol: str
    type: str
    volume: Decimal | None = None
    client_id: str | None = Field(default=None, alias="clientId")
    comment: str | None = None
    state: str | None = None
    open_price: Decimal | None = Field(default=None, alias="openPrice")
    stop_loss: Decimal | None = Field(default=None, alias="stopLoss")
    take_profit: Decimal | None = Field(default=None, alias="takeProfit")
    profit: Decimal | None = None
    swap: Decimal = Decimal(0)
    commission: Decimal = Decimal(0)
    current_price: Decimal | None = Field(default=None, alias="currentPrice")
    time: str | None = None
    expiration_time: str | None = Field(default=None,alias="expirationTime")


class SymbolSpec(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, allow_inf_nan=False)
    symbol: str
    digits: int = Field(ge=0, le=12)
    min_volume: Decimal = Field(alias="minVolume", gt=0)
    max_volume: Decimal = Field(alias="maxVolume", gt=0)
    volume_step: Decimal = Field(alias="volumeStep", gt=0)
    trade_mode: str = Field(alias="tradeMode")
    currency_base: str | None = Field(default=None, alias="currencyBase")
    currency_profit: str | None = Field(default=None, alias="currencyProfit")
    contract_size: Decimal | None = Field(default=None, alias="contractSize")
    tick_size: Decimal | None = Field(default=None, alias="tickSize", gt=0)
    order_mode: list[str] | None = Field(default=None,alias="orderMode")


class BrokerPrice(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, allow_inf_nan=False)
    symbol: str
    bid: Decimal
    ask: Decimal
    time: str
    loss_tick_value: Decimal | None = Field(default=None, alias="lossTickValue", gt=0)


class BrokerDeal(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True, allow_inf_nan=False)
    id: str
    position_id: str | None = Field(default=None, alias="positionId")
    order_id: str | None = Field(default=None, alias="orderId")
    client_id: str | None = Field(default=None, alias="clientId")
    type: str
    profit: Decimal
    commission: Decimal = Decimal(0)
    swap: Decimal = Decimal(0)
    time: str
    entry_type: str | None = Field(default=None,alias="entryType")


class MarginEstimate(BaseModel):
    model_config = ConfigDict(extra="ignore", allow_inf_nan=False)
    margin: Decimal = Field(ge=0)


class AccountConnection(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    id: str = Field(alias="_id")
    state: str
    connection_status: str = Field(alias="connectionStatus")
    region: str
    platform_version: int | None = Field(default=None, alias="platformVersion", ge=4, le=5)


class TradeResponse(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)
    string_code: str = Field(alias="stringCode")
    order_id: str | None = Field(default=None, alias="orderId")
    position_id: str | None = Field(default=None, alias="positionId")


class ProviderRejectedError(RuntimeError):
    """An authenticated provider explicitly rejected an operation."""


class MetaApiClient:
    def __init__(self, connection: Connection, secrets: SecretStore | None = None,
                 *, transport: httpx.AsyncBaseTransport | None = None):
        self.connection, self.secrets, self.transport = connection, secrets or SecretStore(), transport
        self.base = f"https://mt-client-api-v1.{connection.region}.agiliumtrade.ai"

    @staticmethod
    def validate_symbol(symbol: str) -> str:
        # SDK symbol arguments are opaque market identifiers, not URLs/paths.
        # Brokers legitimately advertise '+', spaces and slash suffixes.
        if not 1 <= len(symbol) <= 80 or not symbol.isprintable() or symbol.isspace():
            raise ValueError("Invalid broker symbol")
        return quote(symbol, safe="")

    async def _request(self, method: Literal["GET", "POST"], path: str, *, body: str | None = None,
                       provisioning: bool = False) -> object:
        if self.transport is None:
            return await self._sdk_request(method, path, body=body)
        token = self.secrets.resolve(self.connection.secret_ref)
        base = "https://mt-provisioning-api-v1.agiliumtrade.agiliumtrade.ai" if provisioning else self.base
        async with httpx.AsyncClient(transport=self.transport or PinnedDNSAsyncTransport(),
                                     mounts=None if self.transport else httpx_env_proxy_mounts(),
                                     timeout=20, follow_redirects=False) as client:
            attempts = 3 if method == "GET" else 1
            for attempt in range(attempts):
                try:
                    response = await client.request(method, base + path, content=body,
                                                    headers={"auth-token": token.reveal(), "Content-Type": "application/json"})
                    if (response.status_code == 429 or response.status_code >= 500) and attempt + 1 < attempts:
                        await asyncio.sleep(.1 * 2 ** attempt)
                        continue
                    if 400 <= response.status_code < 500 and response.status_code not in {408, 429}:
                        raise ProviderRejectedError(f"MetaApi rejected operation (HTTP {response.status_code})")
                    if response.status_code >= 300:
                        raise ProviderUnavailableError("MetaApi operation unavailable; mutation outcome may be uncertain")
                    return token.redact(response.json())
                except (httpx.HTTPError, ValueError):
                    if attempt + 1 < attempts:
                        await asyncio.sleep(.1 * 2 ** attempt)
                        continue
                    raise ProviderUnavailableError("MetaApi operation unavailable; mutation outcome may be uncertain") from None
        raise ProviderUnavailableError("MetaApi operation unavailable")

    async def _sdk_request(self, method: str, path: str, *, body: str | None) -> object:
        from nanobot.trading.sdk_bridge import SDKRejectedError, account_bridge
        suffix = path.removeprefix(self.account_path)
        parameters: dict[str, JsonValue] = {}
        reads = {"": "connection", "/account-information": "account", "/positions": "positions",
                 "/orders": "orders", "/symbols": "symbols"}
        if method == "GET" and suffix in reads:
            operation = reads[suffix]
        elif method == "GET" and (match := re.fullmatch(r"/symbols/([^/]+)/(specification|current-price)", suffix)):
            operation = "specification" if match[2] == "specification" else "price"
            parameters = {"symbol": unquote(match[1])}
        elif method == "GET" and (match := re.fullmatch(r"/(history-orders|history-deals)/time/([^/]+)/([^/]+)", suffix)):
            operation = "history_orders" if match[1] == "history-orders" else "history_deals"
            parameters = {"start": unquote(match[2]), "end": unquote(match[3])}
        elif method == "POST" and suffix == "/calculate-margin" and body:
            operation = "margin"
            parameters = TypeAdapter(dict[str, JsonValue]).validate_python(json.loads(body, parse_float=str))
        else:
            raise ValueError("Unsupported MetaApi SDK operation")
        try:
            return await account_bridge(self.connection, self.secrets).request(operation, parameters)
        except SDKRejectedError:
            raise ProviderRejectedError("MetaApi rejected the requested account operation") from None

    @property
    def account_path(self) -> str:
        return f"/users/current/accounts/{self.connection.account_id}"

    async def connection_state(self) -> AccountConnection:
        return parse_provider(AccountConnection, await self._request("GET", self.account_path, provisioning=True))

    async def account(self) -> AccountState:
        return parse_provider(AccountState, await self._request("GET", self.account_path + "/account-information"))

    async def items(self, kind: Literal["positions", "orders"]) -> list[BrokerItem]:
        data = await self._request("GET", self.account_path + "/" + kind)
        try:
            return TypeAdapter(list[BrokerItem]).validate_python(data)
        except ValidationError:
            raise ProviderUnavailableError("MetaApi returned invalid account data") from None

    async def symbols(self) -> list[str]:
        try:
            return TypeAdapter(list[str]).validate_python(await self._request("GET", self.account_path + "/symbols"))
        except ValidationError:
            raise ProviderUnavailableError("MetaApi returned invalid symbol data") from None

    async def specification(self, symbol: str) -> SymbolSpec:
        encoded = self.validate_symbol(symbol)
        spec = parse_provider(SymbolSpec, await self._request("GET", self.account_path + f"/symbols/{encoded}/specification"))
        if spec.symbol != symbol:
            raise ValueError("Provider specification belongs to another symbol")
        return spec

    async def price(self, symbol: str) -> BrokerPrice:
        encoded = self.validate_symbol(symbol)
        price = parse_provider(BrokerPrice, await self._request("GET", self.account_path + f"/symbols/{encoded}/current-price"))
        if price.symbol != symbol:
            raise ValueError("Broker price belongs to another symbol")
        return price

    async def history_orders(self, start: str, end: str) -> list[BrokerItem]:
        data = await self._request("GET", self.account_path + f"/history-orders/time/{quote(start, safe='')}/{quote(end, safe='')}")
        try:
            return TypeAdapter(list[BrokerItem]).validate_python(data)
        except ValidationError:
            raise ProviderUnavailableError("MetaApi returned invalid history data") from None

    async def history_deals(self, start: str, end: str) -> list[BrokerDeal]:
        data = await self._request("GET", self.account_path + f"/history-deals/time/{quote(start, safe='')}/{quote(end, safe='')}")
        try:
            return TypeAdapter(list[BrokerDeal]).validate_python(data)
        except ValidationError:
            raise ProviderUnavailableError("MetaApi returned invalid deal data") from None

    async def calculate_margin(self, symbol: str, side: str, volume: Decimal, price: Decimal) -> Decimal:
        self.validate_symbol(symbol)
        if side not in {"buy", "sell"} or not volume.is_finite() or volume <= 0:
            raise ValueError("Invalid margin request")
        # A fixed read-only broker calculation, not a trading mutation.
        body = '{"symbol":' + json.dumps(symbol) + ',"type":' + json.dumps("ORDER_TYPE_" + side.upper()) + ',"volume":' + format(volume,"f") + ',"openPrice":' + format(price,"f") + '}'
        return parse_provider(MarginEstimate, await self._request("POST", self.account_path + "/calculate-margin", body=body)).margin

    async def mutate(self, payload: dict[str, JsonValue], *, effect: Effect, journal: ActionStore) -> TradeResponse:
        grant = current_authorized_action()
        owned = journal.get_effect(effect.id)
        if (grant is None or grant.action.fingerprint != effect.fingerprint
                or owned.token != effect.token or owned.generation != effect.generation
                or owned.state != "STARTED" or not (owned.approval_id or owned.mandate_id)
                or grant.action.parameters.get("broker_request") != payload
                or grant.action.parameters.get("account_id") != self.connection.account_id):
            raise PermissionError("MetaApi mutation lacks exact gateway effect authorization")
        journal.validate_effect_owner(owned)
        if owned.mandate_id:
            from nanobot.trading.missions import validate_delegated_outbound
            validate_delegated_outbound(journal,owned)
        if self.transport is None:
            from nanobot.trading.sdk_bridge import SDKRejectedError, account_bridge
            bridge = account_bridge(self.connection, self.secrets)
            try:
                # Account synchronization may wait. Fence again after it,
                # immediately before handing the mutation to the SDK.
                await bridge.request("prepare_trade")
                def fence() -> None:
                    latest = journal.get_effect(effect.id)
                    if (latest.token != effect.token or latest.generation != effect.generation
                            or latest.state != "STARTED"):
                        raise PermissionError("SDK effect ownership changed during synchronization")
                    journal.validate_effect_owner(latest)
                    if latest.mandate_id:
                        from nanobot.trading.missions import validate_delegated_outbound
                        validate_delegated_outbound(journal, latest)
                # Recheck inside the connector lock, immediately before stdin
                # delivery, including time spent waiting behind other reads.
                return parse_provider(TradeResponse, await bridge.request("trade", payload, before_write=fence))
            except SDKRejectedError:
                raise ProviderRejectedError("MetaApi rejected the exact authorized trade") from None
        # Numeric JSON is encoded from validated decimal strings without float conversion.
        numeric = {"volume", "openPrice", "stopLoss", "takeProfit"}
        fields: list[str] = []
        for key, value in payload.items():
            if key in numeric:
                number = Decimal(str(value))
                if not number.is_finite():
                    raise ValueError("Non-finite financial value")
                encoded = format(number, "f")
            else:
                encoded = json.dumps(value, allow_nan=False)
            fields.append(json.dumps(key) + ":" + encoded)
        body = "{" + ",".join(fields) + "}"
        return parse_provider(TradeResponse, await self._request("POST", self.account_path + "/trade", body=body))
