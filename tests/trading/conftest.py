from datetime import datetime, timezone

import httpx
import pytest

from nanobot.market.models import Connection
from nanobot.security.secrets import SecretStore
from nanobot.trading.metaapi import MetaApiClient


@pytest.fixture
def client(tmp_path):
    secrets = SecretStore(tmp_path / "secrets")
    secrets.put("meta", "PRIVATE_META_SENTINEL")
    def handler(request):
        assert request.headers["auth-token"] == "PRIVATE_META_SENTINEL"
        path = request.url.path
        if path.endswith("account-information"):
            return httpx.Response(200,json={"broker":"demo","currency":"USD","balance":"10000.01","equity":"9999.02","tradeAllowed":True})
        if path.endswith("positions") or path.endswith("orders"):
            return httpx.Response(200,json=[{"id":"1","symbol":"GOLDm","type":"ORDER_TYPE_BUY_LIMIT" if path.endswith("orders") else "POSITION_TYPE_BUY","volume":"0.1"}])
        if path.endswith("symbols"):
            return httpx.Response(200,json=["GOLDm","EURUSD.a"])
        if path.endswith("specification"):
            return httpx.Response(200,json={"symbol":"GOLDm","digits":2,"minVolume":"0.01","maxVolume":"100","volumeStep":"0.01","tradeMode":"SYMBOL_TRADE_MODE_FULL"})
        if path.endswith("current-price"):
            return httpx.Response(200,json={"symbol":"GOLDm","bid":"2701.10","ask":"2701.25","time":datetime.now(timezone.utc).isoformat()})
        return httpx.Response(200,json={"_id":"demo","state":"DEPLOYED","connectionStatus":"CONNECTED","region":"london"})
    return MetaApiClient(Connection(secret_ref="meta",account_id="demo"),secrets,transport=httpx.MockTransport(handler))

