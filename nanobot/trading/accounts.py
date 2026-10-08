"""Protected conversation selection; financial records always keep their account."""
from __future__ import annotations

import hashlib

from nanobot.market.models import Connection, IntegrationsConfig
from nanobot.security.actions import ActionStore
from nanobot.session.records import RecordStore, RuntimeRecord
from nanobot.trading.metaapi import MetaApiClient


class AccountSelection(RuntimeRecord):
    principal: str
    account_id: str


class TradingAccounts:
    def __init__(self, config: IntegrationsConfig, journal: ActionStore | None = None):
        self.config = config
        self.selections = RecordStore("broker_account_selection", AccountSelection, journal)

    @staticmethod
    def selection_id(principal: str) -> str:
        return "account_selection_" + hashlib.sha256(principal.encode()).hexdigest()

    def connection(self, account_id: str | None = None, *, principal: str | None = None) -> Connection:
        accounts = self.config.broker_accounts()
        if account_id is None and principal:
            try:
                selection = self.selections.get(self.selection_id(principal))
            except ValueError:
                pass
            else:
                if selection.principal != principal:
                    raise PermissionError("Broker selection belongs to another conversation")
                account_id = selection.account_id
        identity = account_id or self.config.default_metaapi_account
        if identity is None and self.config.metaapi:
            identity = self.config.metaapi.account_id
        if identity is None or identity not in accounts:
            raise ValueError("Broker account is not configured; select a connected account explicitly")
        return accounts[identity].model_copy(deep=True)

    def client(self, account_id: str | None = None, *, principal: str | None = None) -> MetaApiClient:
        return MetaApiClient(self.connection(account_id, principal=principal))

    def select(self, principal: str, account_id: str) -> AccountSelection:
        if not principal:
            raise PermissionError("Account switching requires a conversation")
        self.connection(account_id)
        identity = self.selection_id(principal)
        try:
            record = self.selections.get(identity)
        except ValueError:
            return self.selections.create(AccountSelection(id=identity, principal=principal, account_id=account_id))
        if record.principal != principal:
            raise PermissionError("Broker selection belongs to another conversation")
        record.account_id = account_id
        return self.selections.save(record)

    def public_accounts(self, principal: str) -> list[dict[str, object]]:
        try:
            selected = self.connection(principal=principal).account_id
        except ValueError:
            # Discovery remains available to repair an unavailable selection;
            # no replacement account is silently selected for execution.
            selected = None
        return [{"account_id": connection.account_id, "name": connection.name or connection.account_id,
                 "environment": connection.environment, "region": connection.region,
                 "selected": connection.account_id == selected}
                for connection in self.config.broker_accounts().values()]
