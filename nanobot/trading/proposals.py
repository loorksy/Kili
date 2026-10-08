"""Durable intent and broker-verified final previews, separate from execution."""
from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from nanobot.security.actions import now_ms
from nanobot.session.records import RecordStore, RuntimeRecord
from nanobot.trading.instruments import InstrumentMappings
from nanobot.trading.metaapi import AccountState, BrokerPrice, MetaApiClient, SymbolSpec


class TradeIntent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    canonical_instrument: str
    operation: Literal["open", "modify_position", "modify_order", "cancel_order", "close_position"] = "open"
    side: Literal["buy", "sell"] = "buy"
    order_type: Literal["market", "limit", "stop"] = "market"
    volume: Decimal | None = Field(default=None, gt=0)
    price: Decimal | None = Field(default=None, gt=0)
    stop_loss: Decimal | None = Field(default=None, gt=0)
    take_profit: Decimal | None = Field(default=None, gt=0)
    target_id: str | None = Field(default=None, pattern=r"^[a-zA-Z0-9_-]{1,100}$")
    expiration_time: str | None = None

    @model_validator(mode="after")
    def check_intent(self) -> TradeIntent:
        if self.operation == "open" and self.volume is None:
            raise ValueError("Open requires volume")
        if self.operation == "open" and self.order_type != "market" and self.price is None:
            raise ValueError("Pending order requires price")
        if self.operation != "open" and self.target_id is None:
            raise ValueError("Modification/closure requires exact target_id")
        if self.operation == "modify_order" and self.price is None:
            raise ValueError("Pending order modification requires price")
        if self.operation == "modify_position" and self.stop_loss is None and self.take_profit is None:
            raise ValueError("Position modification requires stop loss or take profit")
        return self


class TradeProposal(RuntimeRecord):
    principal: str
    responsibility_id: str | None = None
    account_id: str
    intent: TradeIntent
    rationale_summary: str = Field(default="", max_length=2000)
    evidence_refs: list[str] = Field(default_factory=list, max_length=30)
    chart_refs: list[str] = Field(default_factory=list, max_length=10)
    status: Literal["PROPOSED", "PREVIEWED", "EXECUTED", "FAILED", "UNCERTAIN"] = "PROPOSED"
    preview_id: str | None = None
    effect_id: str | None = None
    mandate_id: str | None = None
    plan_id: str | None = None


class TradePreview(RuntimeRecord):
    proposal_id: str
    principal: str
    responsibility_id: str | None = None
    account_id: str
    canonical_instrument: str
    broker_symbol: str
    mapping_revision: int
    intent: TradeIntent
    account: AccountState
    specification: SymbolSpec
    broker_price: BrokerPrice
    expires_at: int
    broker_request: dict[str, JsonValue]
    effect_key: str
    mandate_id: str | None = None
    mandate_fingerprint: str | None = None
    plan_id: str | None = None

    def material_action(self) -> dict[str, JsonValue]:
        result: dict[str, JsonValue] = {"preview_id": self.id, "proposal_id": self.proposal_id,
                "responsibility_id": self.responsibility_id,
                "account_id": self.account_id, "canonical_instrument": self.canonical_instrument,
                "broker_symbol": self.broker_symbol, "mapping_revision": self.mapping_revision,
                "intent": self.intent.model_dump(mode="json"),
                "broker_request": self.broker_request, "effect_key": self.effect_key}
        if self.mandate_id is not None:
            result.update(mandate_id=self.mandate_id,mandate_fingerprint=self.mandate_fingerprint,plan_id=self.plan_id)
        return result


class TradeProposals:
    def __init__(self, client: MetaApiClient, mappings: InstrumentMappings | None = None,
                 proposals: RecordStore[TradeProposal] | None = None,
                 previews: RecordStore[TradePreview] | None = None):
        self.client, self.mappings = client, mappings or InstrumentMappings()
        self.proposals = proposals or RecordStore("trade_proposals", TradeProposal)
        self.previews = previews or RecordStore("trade_previews", TradePreview)

    @staticmethod
    def require_owner(principal: str, owner: str) -> None:
        if principal != owner:
            raise PermissionError("Trade record belongs to another conversation")

    def create(self, principal: str, intent: TradeIntent, *, responsibility_id: str | None = None,
               rationale: str = "", evidence: list[str] | None = None, charts: list[str] | None = None,
               mandate_id: str | None = None, proposal_id: str | None = None) -> TradeProposal:
        # Missing/ambiguous mappings stop before a proposal can target execution.
        self.mappings.require(self.client.connection.account_id, intent.canonical_instrument)
        plan_id: str | None = None
        if mandate_id is not None:
            from nanobot.trading.mission_models import TradingMandate
            mandate = RecordStore("trading_mandates",TradingMandate,self.proposals.journal).get(mandate_id)
            self.require_owner(principal,mandate.principal)
            if responsibility_id != mandate.responsibility_id:
                raise PermissionError("Delegated proposal requires its owning responsibility")
            plan_id = mandate.plan_id
            if intent.operation == "open" and intent.order_type != "market" and intent.expiration_time is None:
                intent = intent.model_copy(update={"expiration_time":datetime.fromtimestamp(mandate.envelope.expires_at/1000,timezone.utc).isoformat()})
        record = self.proposals.create(TradeProposal(id=proposal_id or "proposal_" + uuid.uuid4().hex,
            principal=principal, responsibility_id=responsibility_id,
            account_id=self.client.connection.account_id, intent=intent,
            rationale_summary=rationale, evidence_refs=evidence or [], chart_refs=charts or [],mandate_id=mandate_id,plan_id=plan_id))
        self.record_lifecycle(record, "PROPOSED")
        return record

    def record_lifecycle(self, proposal: TradeProposal, kind: str, preview_id: str | None = None) -> None:
        from nanobot.trading.execution import TradeJournalEntry
        journal = RecordStore("trade_journal", TradeJournalEntry, self.proposals.journal)
        identity = hashlib.sha256(f"{proposal.id}:{kind}:{preview_id}".encode()).hexdigest()
        journal.create(TradeJournalEntry(id="journal_" + identity, proposal_id=proposal.id,
            responsibility_id=proposal.responsibility_id, preview_id=preview_id, kind=kind,
            evidence_refs=proposal.evidence_refs))

    @staticmethod
    def validate_spec(intent: TradeIntent, spec: SymbolSpec) -> None:
        if spec.trade_mode == "SYMBOL_TRADE_MODE_DISABLED":
            raise ValueError("Broker trading is disabled for this symbol")
        if intent.operation == "open":
            if spec.trade_mode == "SYMBOL_TRADE_MODE_CLOSEONLY":
                raise ValueError("Broker symbol is close-only")
            if ((spec.trade_mode == "SYMBOL_TRADE_MODE_LONGONLY" and intent.side == "sell")
                    or (spec.trade_mode == "SYMBOL_TRADE_MODE_SHORTONLY" and intent.side == "buy")):
                raise ValueError("Broker does not permit this direction")
        if intent.volume is not None:
            if not spec.min_volume <= intent.volume <= spec.max_volume or intent.volume % spec.volume_step:
                raise ValueError("Volume violates broker minimum/maximum/step")
        for price in (intent.price, intent.stop_loss, intent.take_profit):
            if price is not None and price != price.quantize(Decimal(1).scaleb(-spec.digits)):
                raise ValueError("Price precision violates broker specification")

    async def validate_current(self, intent: TradeIntent, symbol: str, *, mandate_id: str | None = None) -> tuple[AccountState, SymbolSpec, BrokerPrice]:
        connection = await self.client.connection_state()
        if connection.id != self.client.connection.account_id or connection.connection_status != "CONNECTED":
            raise ValueError("Trading account is not connected")
        if connection.region != self.client.connection.region:
            raise ValueError("Configured MetaApi region does not match this account")
        account = await self.client.account()
        if not account.trade_allowed:
            raise ValueError("Account trading permission is unavailable")
        if symbol not in await self.client.symbols():
            raise ValueError("Verified broker symbol is no longer available")
        spec = await self.client.specification(symbol)
        if spec.symbol != symbol:
            raise ValueError("Broker specification returned a different symbol")
        self.validate_spec(intent, spec)
        price = await self.client.price(symbol)
        if price.symbol != symbol or price.bid <= 0 or price.ask < price.bid:
            raise ValueError("Broker price does not match the requested symbol")
        observed = datetime.fromisoformat(price.time.replace("Z", "+00:00"))
        if observed.tzinfo is None or not -30 <= (datetime.now(timezone.utc) - observed).total_seconds() <= 300:
            raise ValueError("Broker price is stale or has no trusted timestamp")
        if intent.operation != "open":
            kind = "orders" if intent.operation in {"modify_order", "cancel_order"} else "positions"
            targets = await self.client.items(kind)
            if mandate_id:
                from nanobot.trading.missions import TradingMissions
                from nanobot.trading.simulation import MissionSimulation
                service = TradingMissions(self.client,self.proposals.journal)
                mandate = service.mandates.get(mandate_id)
                if mandate.envelope.mode == "SIMULATION":
                    book = MissionSimulation(service,mandate).get()
                    targets.extend(book.orders if kind == "orders" else book.positions)
            target = next((p for p in targets if p.id == intent.target_id), None)
            if target is None or target.symbol != symbol:
                raise ValueError("Exact broker target does not match this instrument")
        return account, spec, price

    @staticmethod
    def broker_request(intent: TradeIntent, symbol: str, effect_key: str) -> dict[str, JsonValue]:
        suffix = {"market": "", "limit": "_LIMIT", "stop": "_STOP"}[intent.order_type]
        action_type = "ORDER_TYPE_" + intent.side.upper() + suffix if intent.operation == "open" else {
            "modify_position": "POSITION_MODIFY", "modify_order": "ORDER_MODIFY",
            "cancel_order": "ORDER_CANCEL", "close_position": "POSITION_CLOSE_ID",
        }[intent.operation]
        if intent.operation == "close_position" and intent.volume is not None:
            action_type = "POSITION_PARTIAL"
        payload: dict[str, JsonValue] = {"actionType": action_type, "symbol": symbol,
                                       "clientId": "nb" + hashlib.sha256(effect_key.encode()).hexdigest()[:20]}
        if intent.target_id:
            payload["orderId" if intent.operation in {"modify_order", "cancel_order"} else "positionId"] = intent.target_id
        for key, value in (("volume", intent.volume), ("openPrice", intent.price),
                           ("stopLoss", intent.stop_loss), ("takeProfit", intent.take_profit)):
            if value is not None:
                payload[key] = format(value, "f")
        if intent.expiration_time:
            from datetime import datetime
            expiry = datetime.fromisoformat(intent.expiration_time.replace("Z", "+00:00"))
            if expiry.tzinfo is None or int(expiry.timestamp()*1000) <= now_ms():
                raise ValueError("Expiration must be a future timezone-aware timestamp")
            payload["expiration"] = {"type": "ORDER_TIME_SPECIFIED", "time": expiry.isoformat()}
        return payload

    async def preview(self, proposal_id: str, principal: str) -> TradePreview:
        proposal = self.proposals.get(proposal_id)
        self.require_owner(principal, proposal.principal)
        if proposal.preview_id:
            previous = self.previews.get(proposal.preview_id)
            effect = self.previews.journal.find_effect(previous.effect_key)
            if effect and effect.state in {"STARTED", "UNCERTAIN", "RECONCILING", "SUCCEEDED"}:
                raise ValueError("Existing external effect must be resolved before another preview")
        if proposal.status in {"UNCERTAIN", "EXECUTED"}:
            raise ValueError("Reconcile or inspect the existing effect before another preview")
        if proposal.account_id != self.client.connection.account_id:
            raise ValueError("Connected account changed; create a new proposal")
        mapping = self.mappings.require(proposal.account_id, proposal.intent.canonical_instrument)
        account, spec, price = await self.validate_current(proposal.intent, mapping.provider_symbol,mandate_id=proposal.mandate_id)
        preview_id = "preview_" + uuid.uuid4().hex
        key = f"trade:{proposal.id}:{preview_id}"
        mandate_fingerprint: str | None = None
        if proposal.mandate_id:
            from nanobot.trading.mission_models import TradingMandate
            mandate = RecordStore("trading_mandates",TradingMandate,self.proposals.journal).get(proposal.mandate_id)
            if mandate.plan_id != proposal.plan_id:
                raise ValueError("Plan was revised; create a new proposal")
            mandate_fingerprint = mandate.scope_fingerprint
        record = self.previews.create(TradePreview(id=preview_id, proposal_id=proposal.id,
            principal=principal, responsibility_id=proposal.responsibility_id,
            account_id=proposal.account_id, canonical_instrument=proposal.intent.canonical_instrument,
            broker_symbol=mapping.provider_symbol, mapping_revision=mapping.revision,
            intent=proposal.intent, account=account, specification=spec, broker_price=price,
            expires_at=now_ms() + 600_000, broker_request=self.broker_request(proposal.intent,mapping.provider_symbol,key),
            effect_key=key,mandate_id=proposal.mandate_id,mandate_fingerprint=mandate_fingerprint,plan_id=proposal.plan_id))
        proposal.preview_id, proposal.status = record.id, "PREVIEWED"
        self.proposals.save(proposal)
        self.record_lifecycle(proposal, "PREVIEWED", record.id)
        return record

    def require_preview(self, preview_id: str, principal: str) -> TradePreview:
        preview = self.previews.get(preview_id)
        self.require_owner(principal, preview.principal)
        proposal = self.proposals.get(preview.proposal_id)
        if proposal.preview_id != preview.id or preview.account_id != self.client.connection.account_id:
            raise ValueError("Preview was replaced or the account changed")
        mapping = self.mappings.require(preview.account_id, preview.canonical_instrument)
        if mapping.provider_symbol != preview.broker_symbol or mapping.revision != preview.mapping_revision:
            raise ValueError("Broker mapping changed; create a new preview and approval")
        return preview
