"""Opt-in, read-only private provider verification. Never broker mutations."""
import os

import pytest

from nanobot.market.models import Connection
from nanobot.market.oanda import OandaClient
from nanobot.security.secrets import SecretStore
from nanobot.trading.metaapi import MetaApiClient


@pytest.mark.parametrize("provider", ["oanda", "metaapi"])
async def test_optional_live_provider_read(provider, tmp_path):
    prefix = "NANOBOT_TEST_" + provider.upper()
    if os.environ.get(prefix + "_ENABLE") != "1":
        pytest.skip("Private provider read verification is explicitly opt-in")
    token, account = os.environ.get(prefix + "_TOKEN"), os.environ.get(prefix + "_ACCOUNT")
    if not token or not account:
        pytest.skip("Private read-only verification credentials not configured")
    secrets = SecretStore(tmp_path / "secrets")
    secrets.put("connection", token)
    connection = Connection(secret_ref="connection", account_id=account,
                            region=os.environ.get(prefix + "_REGION", "london"))
    if provider == "oanda":
        assert await OandaClient(connection, secrets).instruments()
    else:
        assert (await MetaApiClient(connection, secrets).connection_state()).id == account
