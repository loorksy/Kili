"""Private MetaApi SDK process. Fixed provider operations; no agent/tool runtime.

Dynamic SDK types are confined to this pinned compatibility boundary. The
gateway authenticates effects before invoking `trade`; this process has no
policy, approval, scheduling, workspace or authoritative-state API.
"""
from __future__ import annotations

import asyncio
import importlib
import json
import logging
import os
import socket
import sys
from datetime import datetime
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit
from urllib.request import getproxies


def provider_url(url: str) -> str:
    parsed = urlsplit(url)
    if (parsed.scheme not in {"https", "wss"} or parsed.username or parsed.password
            or parsed.port not in {None, 443} or not parsed.hostname
            or not parsed.hostname.endswith(".agiliumtrade.ai")):
        raise ValueError("Unsupported MetaApi endpoint")
    return url


def number(value: Any) -> float | None:
    if value is None:
        return None
    exact = Decimal(str(value))
    result = float(exact)
    if not exact.is_finite() or Decimal(str(result)) != exact:
        raise ValueError("Financial precision cannot be represented by the SDK")
    return result


def timestamp(value: str) -> datetime:
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("Timestamp requires timezone")
    return result


def json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return format(value, "f")
    raise TypeError("Unsupported SDK result")


def install_network_boundary() -> None:
    """Adapt the pinned SDK transports without editing installed SDK files."""
    httpx = importlib.import_module("httpx")
    aiohttp = importlib.import_module("aiohttp")
    network = importlib.import_module("nanobot.security.network")
    http_module = importlib.import_module("metaapi_cloud_sdk.clients.http_client")
    socketio = importlib.import_module("socketio")
    websocket = importlib.import_module("metaapi_cloud_sdk.clients.metaapi.metaapi_websocket_client")

    async def make_request(client: Any, options: dict[str, Any]) -> Any:
        url = provider_url(options["url"])
        ok, _, _ = network.resolve_url_target(url, trust_remote_dns=network.env_proxy_applies_to_url(url))
        if not ok:
            raise ValueError("Unsafe provider endpoint")
        async with httpx.AsyncClient(timeout=client._timeout, follow_redirects=False,
                                     transport=network.PinnedDNSAsyncTransport(),
                                     mounts=network.httpx_env_proxy_mounts()) as transport:
            return await transport.request(options.get("method", "GET"), url,
                                           params=options.get("params"), files=options.get("files"),
                                           headers=options.get("headers"), json=options.get("body"))

    class PublicResolver(aiohttp.abc.AbstractResolver):
        async def resolve(self, host: str, port: int = 0, family: int = socket.AF_INET) -> list[dict[str, Any]]:
            # Only configured operator proxies may resolve to internal IPs.
            proxy_hosts = {urlsplit(value).hostname for key, value in getproxies().items()
                           if key in {"https", "http", "all"}}
            if host in proxy_hosts:
                return await aiohttp.resolver.DefaultResolver().resolve(host, port, family)
            url = provider_url(f"https://{host}")
            ok, _, ips = await asyncio.to_thread(network.resolve_url_target, url)
            if not ok or not ips:
                raise OSError("Unsafe provider DNS")
            return [{"hostname": host, "host": ip, "port": port,
                     "family": socket.AF_INET6 if ":" in ip else socket.AF_INET,
                     "proto": 0, "flags": socket.AI_NUMERICHOST} for ip in ips]

        async def close(self) -> None:
            pass

    async def validate_request(_session: Any, _context: Any, params: Any) -> None:
        provider_url(str(params.url))

    class SafeSocketClient(socketio.AsyncClient):
        def __init__(self, *args: Any, **kwargs: Any):
            trace = aiohttp.TraceConfig()
            trace.on_request_start.append(validate_request)
            session = aiohttp.ClientSession(connector=aiohttp.TCPConnector(resolver=PublicResolver()),
                                             trust_env=True, trace_configs=[trace])
            # Engine.IO 3 doesn't forward environment proxies to ws_connect.
            original_ws = session.ws_connect

            def safe_ws(url: str, **options: Any) -> Any:
                provider_url(str(url))
                if network.env_proxy_applies_to_url(str(url).replace("wss:", "https:")):
                    options["proxy"] = getproxies().get("https") or getproxies().get("all")
                return original_ws(url, **options)

            session.ws_connect = safe_ws
            socketio.AsyncClient.__init__(self, *args, http_session=session, **kwargs)

        async def connect(self, url: str, *args: Any, **kwargs: Any) -> Any:
            provider_url(url)
            return await socketio.AsyncClient.connect(self, url, *args, **kwargs)

    http_module.HttpClient._make_request = make_request
    # Replace only this SDK module's Socket.IO reference, not any Nanobot channel.
    class SocketModule:
        AsyncClient = SafeSocketClient

    setattr(websocket, "socketio", SocketModule)


async def trade(rpc: Any, payload: dict[str, Any]) -> Any:
    allowed = {"actionType", "symbol", "clientId", "volume", "openPrice", "stopLoss",
               "takeProfit", "positionId", "orderId", "expiration"}
    if payload.keys() - allowed:
        raise ValueError("Unsupported trading parameter")
    kind = payload["actionType"]
    options = {"clientId": payload["clientId"]} if "clientId" in payload else {}
    if "expiration" in payload:
        expiry = payload["expiration"]
        if expiry["type"] != "ORDER_TIME_SPECIFIED":
            raise ValueError("Unsupported expiration")
        options["expiration"] = {"type": "ORDER_TIME_SPECIFIED", "time": timestamp(expiry["time"])}
    sl, tp = number(payload.get("stopLoss")), number(payload.get("takeProfit"))
    creators = {
        "ORDER_TYPE_BUY": "create_market_buy_order", "ORDER_TYPE_SELL": "create_market_sell_order",
        "ORDER_TYPE_BUY_LIMIT": "create_limit_buy_order", "ORDER_TYPE_SELL_LIMIT": "create_limit_sell_order",
        "ORDER_TYPE_BUY_STOP": "create_stop_buy_order", "ORDER_TYPE_SELL_STOP": "create_stop_sell_order",
    }
    if kind in creators:
        args = [payload["symbol"], number(payload["volume"])]
        if kind.endswith(("_LIMIT", "_STOP")):
            args.append(number(payload["openPrice"]))
        return await getattr(rpc, creators[kind])(*args, stop_loss=sl, take_profit=tp, options=options)
    if kind == "POSITION_MODIFY":
        return await rpc.modify_position(payload["positionId"], stop_loss=sl, take_profit=tp)
    if kind == "POSITION_PARTIAL":
        return await rpc.close_position_partially(payload["positionId"], number(payload["volume"]), options=options)
    if kind == "POSITION_CLOSE_ID":
        return await rpc.close_position(payload["positionId"], options=options)
    if kind == "ORDER_MODIFY":
        return await rpc.modify_order(payload["orderId"], number(payload["openPrice"]), stop_loss=sl, take_profit=tp, options=options)
    if kind == "ORDER_CANCEL":
        return await rpc.cancel_order(payload["orderId"])
    raise ValueError("Unsupported trading operation")


class AccountEnvironment:
    def __init__(self, bootstrap: dict[str, str]):
        sdk = importlib.import_module("metaapi_cloud_sdk")
        self.api = sdk.MetaApi(bootstrap["token"], {
            "region": bootstrap["region"], "requestTimeout": 20, "connectTimeout": 20,
            "historicalMarketDataRequestTimeout": 30, "retryOpts": {"retries": 0},
            "enableSocketioDebugger": False, "packetLogger": {"enabled": False},
        })
        self.account_id = bootstrap["account_id"]
        self.account: Any = None
        self.rpc: Any = None

    async def execute(self, operation: str, params: dict[str, Any]) -> Any:
        if self.account is None:
            self.account = await self.api.metatrader_account_api.get_account(self.account_id)
        if operation == "connection":
            await self.account.reload()
            return {"_id": self.account.id, "state": self.account.state,
                    "connectionStatus": self.account.connection_status, "region": self.account.region}
        if operation == "candles":
            return await self.account.get_historical_candles(params["symbol"], params["timeframe"],
                                                           timestamp(params["start"]) if params.get("start") else None,
                                                           params.get("limit", 500))
        if operation == "trade":
            if self.rpc is None:
                raise ValueError("Prepare the synchronized account before trading")
            return await trade(self.rpc, params)
        if self.rpc is None:
            self.rpc = self.account.get_rpc_connection()
            await self.rpc.connect()
        await self.rpc.wait_synchronized(timeout_in_seconds=20)
        if operation == "prepare_trade":
            return {"ready": True}
        reads = {"account": "get_account_information", "positions": "get_positions",
                 "orders": "get_orders", "symbols": "get_symbols"}
        if operation in reads:
            return await getattr(self.rpc, reads[operation])()
        if operation == "specification":
            return await self.rpc.get_symbol_specification(params["symbol"])
        if operation == "price":
            return await self.rpc.get_symbol_price(params["symbol"])
        if operation == "history_orders":
            result = await self.rpc.get_history_orders_by_time_range(timestamp(params["start"]), timestamp(params["end"]))
            if result.get("synchronizing"):
                raise RuntimeError("History not synchronized")
            return result["historyOrders"]
        if operation == "history_deals":
            result = await self.rpc.get_deals_by_time_range(timestamp(params["start"]), timestamp(params["end"]))
            if result.get("synchronizing"):
                raise RuntimeError("History not synchronized")
            return result["deals"]
        if operation == "margin":
            return await self.rpc.calculate_margin({"symbol": params["symbol"], "type": params["type"],
                                                    "volume": number(params["volume"]), "openPrice": number(params["openPrice"])})
        raise ValueError("Unsupported SDK operation")

    async def close(self) -> None:
        if self.rpc is not None:
            await self.rpc.close()
        self.api.close()


async def run() -> None:
    wire = sys.stdout
    sys.stdout = open(os.devnull, "w")
    logging.disable(logging.CRITICAL)
    importlib.import_module("metaapi_cloud_sdk.logger").LoggerManager.use_logging()
    install_network_boundary()
    bootstrap = json.loads(await asyncio.to_thread(sys.stdin.readline))
    environment = AccountEnvironment(bootstrap)
    try:
        while line := await asyncio.to_thread(sys.stdin.readline):
            try:
                request = json.loads(line)
                data = await asyncio.wait_for(environment.execute(request["operation"], request["parameters"]), timeout=55)
                reply = {"ok": True, "data": data}
            except Exception as exc:
                # Provider diagnostics may contain tokens and URLs. Only a
                # classified code crosses IPC; never raw exception strings.
                rejected = type(exc).__name__ in {"TradeException", "ValidationException", "UnauthorizedException", "ForbiddenException", "NotFoundException"}
                reply = {"ok": False, "error": "rejected" if rejected else "unavailable"}
            wire.write(json.dumps(reply, default=json_default, allow_nan=False) + "\n")
            wire.flush()
    finally:
        await environment.close()


if __name__ == "__main__":
    # Isolated interpreter loads SDK first, then trusted Nanobot network guards.
    sys.path.extend(sys.argv[1:])
    asyncio.run(run())
