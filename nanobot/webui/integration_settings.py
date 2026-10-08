"""Existing Settings owns connection entry; only protected references are persisted in config."""
from __future__ import annotations

import uuid
from typing import Literal

from pydantic import BaseModel, ConfigDict, SecretStr

from nanobot.config.schema import Config
from nanobot.market.models import Connection, Instrument
from nanobot.security.secrets import SecretStore
from nanobot.trading.instruments import InstrumentMappings
from nanobot.trading.metaapi import MetaApiClient
from nanobot.webui.settings_services import WebUISettingsConfig


class ConnectionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    provider: Literal["oanda", "metaapi"]
    account_id: str
    token: SecretStr | None = None
    environment: Literal["practice", "live"] = "practice"
    region: str = "london"
    charts_enabled: bool = True


class MappingUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    instrument: Instrument
    broker_symbol: str


class AutonomyUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool


def integration_status(config: Config) -> dict[str, object]:
    result: dict[str, object] = {"charts_enabled": config.tools.integrations.charts_enabled,
        "autonomous_trading_enabled":config.tools.integrations.autonomous_trading_enabled}
    for provider in ("oanda", "metaapi"):
        connection = getattr(config.tools.integrations, provider)
        if isinstance(connection, Connection):
            result[provider] = {"configured": True, "account_id": connection.account_id,
                                "environment": connection.environment, "region": connection.region,
                                "credential": "stored"}
        else:
            result[provider] = {"configured": False}
    result["mappings"] = [m.model_dump(mode="json") for m in InstrumentMappings().records.list()]
    return result


def configure_connection(settings: WebUISettingsConfig, request: ConnectionUpdate) -> dict[str, object]:
    def change(config: Config) -> None:
        previous = getattr(config.tools.integrations, request.provider)
        reference = previous.secret_ref if isinstance(previous, Connection) else "connection_" + uuid.uuid4().hex
        connection = Connection(secret_ref=reference, account_id=request.account_id,
                                environment=request.environment, region=request.region)
        if request.token:
            SecretStore().put(reference, request.token.get_secret_value())
        elif not isinstance(previous, Connection):
            raise ValueError("A credential is required for a new connection")
        setattr(config.tools.integrations, request.provider, connection)
        config.tools.integrations.charts_enabled = request.charts_enabled
        from nanobot.security.financial_auth import require_financial_gateway_auth
        require_financial_gateway_auth(config)
    settings.update(change)
    return {**integration_status(settings.load()), "restart_required": True}


async def configure_mapping(config: Config, request: MappingUpdate) -> dict[str, object]:
    connection = config.tools.integrations.metaapi
    if connection is None:
        raise ValueError("MetaApi connection is not configured")
    record = await InstrumentMappings().verify_user_mapping(MetaApiClient(connection), request.instrument, request.broker_symbol)
    return record.model_dump(mode="json")


def configure_autonomy(settings: WebUISettingsConfig, request: AutonomyUpdate) -> dict[str, object]:
    def change(config: Config) -> None:
        if request.enabled and config.tools.integrations.metaapi is None:
            raise ValueError("Connect MetaApi before enabling delegated live trading")
        config.tools.integrations.autonomous_trading_enabled = request.enabled
        from nanobot.security.financial_auth import require_financial_gateway_auth
        require_financial_gateway_auth(config)
    settings.update(change)
    if not request.enabled:
        from nanobot.session.records import RecordStore
        from nanobot.trading.mission_models import AccountGuardrails
        guards = RecordStore("account_guardrails",AccountGuardrails)
        for guard in guards.list():
            guard.enabled = False
            guards.save(guard)
    return {**integration_status(settings.load()),"restart_required":True}
