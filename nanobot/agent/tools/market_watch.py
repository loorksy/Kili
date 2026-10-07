"""Explicit market conditions attached to the existing durable responsibility."""
from __future__ import annotations

import hashlib
import uuid
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.context import ToolContext, current_request_context
from nanobot.market.watchers import MarketWatcher
from nanobot.security.actions import now_ms
from nanobot.session.records import RecordStore


class _WatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: Literal["create", "list", "cancel"]
    responsibility_id: str
    watcher_id: str | None = None
    provider_instrument: str | None = None
    canonical_instrument: str | None = None
    condition: Literal["above", "below", "cross_above", "cross_below"] = "above"
    threshold: str | None = None
    interval_ms: int = Field(default=60_000, ge=1000)


class MarketWatchTool(Tool):
    def __init__(self, ctx: ToolContext):
        namespace = hashlib.sha256(ctx.workspace.encode()).hexdigest()
        self.records = RecordStore("market_watchers:" + namespace, MarketWatcher)
        self.cron = ctx.cron_service

    @property
    def name(self) -> str:
        return "market_watch"

    @property
    def description(self) -> str:
        return "Create a deterministic price condition for a durable responsibility. Quotes do not invoke the model; the satisfied condition wakes it once."

    @property
    def parameters(self) -> dict[str, Any]:
        return _WatchRequest.model_json_schema()

    @classmethod
    def enabled(cls, ctx: ToolContext) -> bool:
        return ctx.config.integrations.oanda is not None and ctx.sessions is not None

    @classmethod
    def create(cls, ctx: ToolContext) -> MarketWatchTool:
        return cls(ctx)

    async def execute(self, **kwargs: Any) -> str:
        import json
        request = _WatchRequest.model_validate(kwargs)
        context = current_request_context()
        execution = context.responsibility_scope.executions.get(request.responsibility_id) if context else None
        if not execution:
            raise PermissionError("A claimed responsibility must own this condition")
        execution.store.assert_owner(execution.claim)
        if request.operation == "list":
            return json.dumps([w.model_dump(mode="json") for w in self.records.list()
                               if w.responsibility_id == request.responsibility_id])
        if request.operation == "create":
            if not request.provider_instrument or not request.canonical_instrument or request.threshold is None:
                raise ValueError("Condition requires explicit instruments and threshold")
            watcher = MarketWatcher.model_validate({
                "id": "watch_" + uuid.uuid4().hex, "responsibility_id": request.responsibility_id,
                "provider_instrument": request.provider_instrument,
                "canonical_instrument": request.canonical_instrument,
                "condition": request.condition, "threshold": request.threshold,
                "interval_ms": request.interval_ms, "next_check_ms": now_ms(),
            })
            self.records.create(watcher)
        else:
            if not request.watcher_id:
                raise ValueError("Cancel requires watcher_id")
            watcher = self.records.get(request.watcher_id)
            if watcher.responsibility_id != request.responsibility_id:
                raise PermissionError("Condition belongs to another responsibility")
            watcher.active = False
            self.records.save(watcher)
        if self.cron:
            self.cron.reschedule()
        return watcher.model_dump_json()
