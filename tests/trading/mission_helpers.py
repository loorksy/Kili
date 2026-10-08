import json
from datetime import datetime, timezone
from decimal import Decimal

import httpx

from nanobot.market.models import Connection
from nanobot.security.secrets import SecretStore
from nanobot.trading.metaapi import MetaApiClient


def broker_fixture(tmp_path):
    secrets = SecretStore(tmp_path/"mission-secrets")
    secrets.put("testmeta","MISSION_SECRET_SENTINEL")
    state = {"positions":[],"orders":[],"history_orders":[],"deals":[],"calls":[],"equity":"10000",
             "bid":"2700","ask":"2701","connected":True,"margin_mode":"ACCOUNT_MARGIN_MODE_RETAIL_HEDGING"}
    def handler(request):
        path = request.url.path
        if path.endswith("/calculate-margin"):
            return httpx.Response(200,json={"margin":"100"})
        if path.endswith("/trade"):
            payload = json.loads(request.content)
            state["calls"].append(payload)
            identity = "broker-"+str(len(state["calls"]))
            if payload["actionType"].startswith("ORDER_TYPE_"):
                pending = payload["actionType"] not in {"ORDER_TYPE_BUY","ORDER_TYPE_SELL"}
                item = {"id":identity,"symbol":payload["symbol"],"type":payload["actionType"] if pending else payload["actionType"].replace("ORDER","POSITION"),
                    "clientId":payload["clientId"],"volume":str(payload["volume"]),"openPrice":str(payload.get("openPrice",state["ask"])),
                    "stopLoss":str(payload["stopLoss"]),"profit":"0"}
                state["orders" if pending else "positions"].append(item)
                return httpx.Response(200,json={"stringCode":"TRADE_RETCODE_PLACED" if pending else "TRADE_RETCODE_DONE","orderId":identity,"positionId":None if pending else identity})
            target = payload.get("positionId",payload.get("orderId"))
            collection = state["orders" if "orderId" in payload else "positions"]
            item = next(p for p in collection if p["id"] == target)
            if payload["actionType"] in {"POSITION_CLOSE_ID","ORDER_CANCEL"}:
                if payload["actionType"] == "ORDER_CANCEL":
                    state["history_orders"].append({**item,"state":"ORDER_STATE_CANCELED"})
                if payload["actionType"] == "POSITION_CLOSE_ID":
                    state["deals"].append({"id":"deal-"+identity,"positionId":item["id"],"clientId":item.get("clientId"),
                        "type":"DEAL_TYPE_SELL","entryType":"DEAL_ENTRY_OUT","profit":item["profit"],"time":datetime.now(timezone.utc).isoformat()})
                collection.remove(item)
            elif payload["actionType"] == "POSITION_PARTIAL":
                item["volume"] = str(Decimal(item["volume"])-Decimal(str(payload["volume"])))
            else:
                for key in ("stopLoss","takeProfit","openPrice","volume"):
                    if key in payload:
                        item[key] = str(payload[key])
            return httpx.Response(200,json={"stringCode":"TRADE_RETCODE_DONE","positionId":target})
        if path.endswith("account-information"):
            return httpx.Response(200,json={"broker":"fixture","platform":"mt5","currency":"USD","balance":"10000","equity":state["equity"],
                "margin":"0","freeMargin":"10000","tradeAllowed":True,"marginMode":state["margin_mode"]})
        if "/history-orders/" in path:
            return httpx.Response(200,json=state["history_orders"])
        for kind in ("positions","orders","deals"):
            if path.endswith("/"+kind) or "/history-"+kind+"/" in path:
                return httpx.Response(200,json=state[kind])
        if path.endswith("symbols"):
            return httpx.Response(200,json=["GOLDm"])
        if path.endswith("specification"):
            return httpx.Response(200,json={"symbol":"GOLDm","digits":2,"minVolume":".01","maxVolume":"100","volumeStep":".01",
                "tradeMode":"SYMBOL_TRADE_MODE_FULL","contractSize":"100","currencyProfit":"USD","orderMode":["SYMBOL_ORDER_MARKET","SYMBOL_ORDER_LIMIT","SYMBOL_ORDER_STOP"]})
        if path.endswith("current-price"):
            return httpx.Response(200,json={"symbol":"GOLDm","bid":state["bid"],"ask":state["ask"],"time":datetime.now(timezone.utc).isoformat()})
        return httpx.Response(200,json={"_id":"demo","state":"DEPLOYED","connectionStatus":"CONNECTED" if state["connected"] else "DISCONNECTED","region":"london"})
    return MetaApiClient(Connection(account_id="demo",secret_ref="testmeta"),secrets,transport=httpx.MockTransport(handler)),state
