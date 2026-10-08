"""Explicit, account-scoped instrument identity. Broker names are never guessed."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Literal

from nanobot.market.models import Instrument
from nanobot.session.records import RecordStore, RuntimeRecord
from nanobot.trading.metaapi import MetaApiClient


class SymbolMapping(RuntimeRecord):
    instrument: Instrument
    provider: Literal["metaapi", "oanda"]
    account_id: str
    provider_symbol: str
    status: Literal["UNVERIFIED", "VERIFIED", "AMBIGUOUS"] = "UNVERIFIED"
    verified_at: datetime | None = None
    verification_source: Literal["provider_metadata", "user"] | None = None


class InstrumentMappings:
    def __init__(self, records: RecordStore[SymbolMapping] | None = None):
        self.records = records or RecordStore("instrument_mappings", SymbolMapping)

    @staticmethod
    def key(provider: str, account: str, instrument: str) -> str:
        return "mapping_" + hashlib.sha256(f"{provider}\0{account}\0{instrument}".encode()).hexdigest()

    @staticmethod
    def native_identity(account: str, symbol: str) -> str:
        MetaApiClient.validate_symbol(symbol)
        return "broker_" + hashlib.sha256(json.dumps([account, symbol]).encode()).hexdigest()[:32]

    def register_catalog(self, account: str, advertised_symbols: list[str]) -> None:
        """Trusted provider catalog, never an agent-supplied canonical mapping.

        Native identity asserts only this exact account/symbol pair. It does
        not equate GOLD, XAUUSD or suffix variants or grant trading authority.
        """
        with self.records.execution_write(), self.records.journal.transaction() as db:
            for symbol in advertised_symbols:
                canonical = self.native_identity(account, symbol)
                identity = self.key("metaapi", account, canonical)
                row = db.execute("SELECT record FROM records WHERE namespace=? AND id=?", (self.records.namespace, identity)).fetchone()
                if row is not None:
                    record = SymbolMapping.model_validate_json(row[0])
                    if record.provider_symbol != symbol or record.status != "VERIFIED":
                        raise ValueError("Native broker identity conflicts with an existing mapping")
                    continue
                record = SymbolMapping(id=identity,
                    instrument=Instrument(id=canonical, display_symbol=symbol, asset_class="broker"),
                    provider="metaapi", account_id=account, provider_symbol=symbol, status="VERIFIED",
                    verified_at=datetime.now(timezone.utc), verification_source="provider_metadata")
                db.execute("INSERT INTO records VALUES (?,?,?,?)", (self.records.namespace, record.id,
                    record.revision, record.model_dump_json()))

    def require(self, account: str, instrument: str) -> SymbolMapping:
        try:
            mapping = self.records.get(self.key("metaapi", account, instrument))
        except ValueError:
            raise ValueError("Instrument mapping is missing for this account; verify the exact broker symbol") from None
        if mapping.status != "VERIFIED":
            raise ValueError("Instrument mapping is ambiguous or unverified; user resolution required")
        return mapping

    async def verify_user_mapping(self, client: MetaApiClient, instrument: Instrument, symbol: str) -> SymbolMapping:
        """Authenticated Settings interaction only; not an agent tool."""
        if symbol not in await client.symbols():
            raise ValueError("Symbol does not exist on the connected broker account")
        await client.specification(symbol)
        record = SymbolMapping(id=self.key("metaapi",client.connection.account_id,instrument.id),
                               instrument=instrument, provider="metaapi", account_id=client.connection.account_id,
                               provider_symbol=symbol, status="VERIFIED", verified_at=datetime.now(timezone.utc),
                               verification_source="user")
        try:
            existing = self.records.get(record.id)
        except ValueError:
            return self.records.create(record)
        record.revision, record.created_at = existing.revision, existing.created_at
        return self.records.save(record)
