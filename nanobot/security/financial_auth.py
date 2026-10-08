"""Financial integrations cannot trust an agent-reachable local login route."""
from __future__ import annotations

from nanobot.channels.websocket.runtime import WebSocketConfig
from nanobot.config.schema import Config


def require_financial_gateway_auth(config: Config) -> None:
    if config.tools.integrations.metaapi is None:
        return
    raw = (config.channels.model_extra or {}).get("websocket", {})
    websocket = WebSocketConfig.model_validate(raw)
    if not websocket.enabled:
        return
    if (not websocket.websocket_requires_token
            or not (websocket.token.strip() or websocket.token_issue_secret.strip())
            or websocket.trusted_proxy_auth is not None):
        raise ValueError(
            "MetaApi with WebUI requires an application token/tokenIssueSecret and "
            "trustedProxyAuth disabled. Local or proxy-only login cannot authorize financial actions."
        )
