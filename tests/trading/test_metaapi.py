from decimal import Decimal

import httpx
import pytest

from nanobot.market.models import Connection, Instrument
from nanobot.security.actions import ActionStore
from nanobot.security.secrets import SecretStore
from nanobot.session.records import RecordStore
from nanobot.trading.instruments import InstrumentMappings, SymbolMapping
from nanobot.trading.metaapi import MetaApiClient, ProviderRejectedError


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
            return httpx.Response(200,json=[{"id":"1","symbol":"GOLDm","type":"POSITION_TYPE_BUY","volume":"0.1"}])
        if path.endswith("symbols"):
            return httpx.Response(200,json=["GOLDm","EURUSD.a"])
        if path.endswith("specification"):
            return httpx.Response(200,json={"symbol":"GOLDm","digits":2,"minVolume":"0.01","maxVolume":"100","volumeStep":"0.01","tradeMode":"SYMBOL_TRADE_MODE_FULL"})
        if path.endswith("current-price"):
            return httpx.Response(200,json={"symbol":"GOLDm","bid":"2701.10","ask":"2701.25","time":"2026-10-07T20:00:00Z"})
        return httpx.Response(200,json={"_id":"demo","state":"DEPLOYED","connectionStatus":"CONNECTED","region":"london"})
    return MetaApiClient(Connection(secret_ref="meta",account_id="demo"),secrets,transport=httpx.MockTransport(handler))


async def test_account_reads_symbol_spec_and_connection(client):
    assert (await client.connection_state()).connection_status == "CONNECTED"
    account = await client.account()
    assert account.balance == Decimal("10000.01")
    assert "PRIVATE_META_SENTINEL" not in account.model_dump_json()
    assert (await client.items("positions"))[0].symbol == "GOLDm"
    assert (await client.items("orders"))[0].volume == Decimal("0.1")
    assert "GOLDm" in await client.symbols()
    assert (await client.specification("GOLDm")).volume_step == Decimal(".01")
    assert (await client.price("GOLDm")).ask == Decimal("2701.25")


async def test_explicit_mapping_is_account_scoped_and_never_guesses(client,tmp_path):
    records = RecordStore("mappings",SymbolMapping,ActionStore(tmp_path / "state.db"))
    mappings = InstrumentMappings(records)
    instrument = Instrument(id="XAU-USD",display_symbol="XAUUSD",asset_class="metal",base="XAU",quote="USD")
    with pytest.raises(ValueError):
        mappings.require("demo",instrument.id)
    mapping = await mappings.verify_user_mapping(client,instrument,"GOLDm")
    assert mapping.provider_symbol == "GOLDm" and mapping.status == "VERIFIED"
    assert mappings.require("demo",instrument.id).id == mapping.id
    with pytest.raises(ValueError):
        mappings.require("other-account",instrument.id)
    with pytest.raises(ValueError,match="does not exist"):
        await mappings.verify_user_mapping(client,instrument,"XAUUSD")


async def test_provider_rejection_is_redacted(tmp_path):
    secrets = SecretStore(tmp_path / "secrets")
    secrets.put("meta", "PRIVATE_META_SENTINEL")
    client = MetaApiClient(Connection(secret_ref="meta",account_id="demo"),secrets,
                          transport=httpx.MockTransport(lambda r:httpx.Response(403,text="PRIVATE_META_SENTINEL")))
    with pytest.raises(ProviderRejectedError) as exc:
        await client.account()
    assert "PRIVATE_META_SENTINEL" not in str(exc.value)
