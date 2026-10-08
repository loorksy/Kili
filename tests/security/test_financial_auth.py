import pytest

from nanobot.config.schema import Config
from nanobot.market.models import Connection
from nanobot.security.financial_auth import require_financial_gateway_auth


def configured(websocket):
    config = Config.model_validate({"channels": {"websocket": websocket}})
    config.tools.integrations.metaapi = Connection(secret_ref="protected", account_id="demo")
    return config


@pytest.mark.parametrize("websocket", [{}, {"token": "user-only", "websocketRequiresToken": False},
    {"token": "user-only", "trustedProxyAuth": {"trustedPeerCidrs": ["127.0.0.1/32"], "assertionHeader": "X-Authenticated-User"}}])
def test_financial_actions_cannot_use_local_or_proxy_only_login(websocket):
    with pytest.raises(ValueError, match="MetaApi with WebUI"):
        require_financial_gateway_auth(configured(websocket))


def test_application_login_required_only_for_configured_financial_gateway():
    require_financial_gateway_auth(Config())
    require_financial_gateway_auth(configured({"enabled": False}))
    require_financial_gateway_auth(configured({"tokenIssueSecret": "user-only"}))
