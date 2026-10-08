"""Bounded read-only reconciliation admitted by Nanobot's existing cron timer."""
from __future__ import annotations

from loguru import logger
from pydantic import Field

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.security.actions import now_ms
from nanobot.session.records import RecordStore, RuntimeRecord
from nanobot.session.responsibilities import ResponsibilityStore
from nanobot.trading.execution import TradeExecutor


class ReconciliationRetry(RuntimeRecord):
    attempts: int = Field(default=0, ge=0)
    next_at: int = Field(default_factory=now_ms)


class TradeRecovery:
    def __init__(self, executor: TradeExecutor, responsibilities: ResponsibilityStore):
        self.executor, self.responsibilities = executor, responsibilities
        self.retries = RecordStore("trade_reconciliation", ReconciliationRetry, executor.effects)

    def due(self) -> list[tuple[str, ReconciliationRetry | None]]:
        retries = {record.id: record for record in self.retries.list()}
        return [(effect.id, retries.get(effect.id)) for effect in self.executor.effects.list_effects()
                if effect.state == "UNCERTAIN" and effect.action.tool == "trade_execute"
                and effect.action.parameters.get("account_id") == self.executor.proposals.client.connection.account_id
                and (effect.id not in retries or retries[effect.id].attempts < 3)]

    def nearest(self) -> int | None:
        return min((retry.next_at if retry else now_ms() for _, retry in self.due()), default=None)

    async def run_due(self) -> None:
        for effect_id, retry in self.due()[:10]:
            if retry and retry.next_at > now_ms():
                continue
            retry = retry or self.retries.create(ReconciliationRetry(id=effect_id))
            # Persist admission before provider reads; process death consumes an attempt.
            retry.attempts += 1
            retry.next_at = now_ms() + 30_000 * 2 ** (retry.attempts - 1)
            self.retries.save(retry)
            effect = self.executor.effects.get_effect(effect_id)
            channel, _, chat_id = effect.action.principal.partition(":")
            try:
                with request_context(RequestContext(channel=channel, chat_id=chat_id,
                                                   session_key=effect.action.principal)):
                    result = await self.executor.reconcile(effect_id, effect.action.principal)
                responsibility_id = effect.action.responsibility_id
                if responsibility_id:
                    # Stable outcome wake; interrupted parents remain paused until
                    # the user authorizes continuation, never replaying the mutation.
                    self.responsibilities.enqueue(responsibility_id,
                        f"effect:{effect_id}:{result['state']}",
                        f"External effect {effect_id}: {result['state']}. Inspect saved evidence before continuing.")
            except (ValueError, PermissionError):
                logger.warning("Reconciliation needs user attention effect={}", effect_id)
