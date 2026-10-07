import asyncio
import subprocess
import sys

import pytest

from nanobot.agent.tools.base import Tool
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.security.actions import Action, ActionPolicy, ActionStore, Review
from nanobot.security.secrets import SecretStore


def action(**updates):
    return Action(tool="trade_execute", action_class="consequential", principal="webui:user",
                  parameters={"account": "demo", "symbol": "GOLD", "volume": "0.1", **updates})


class Reviewer:
    def __init__(self, decision="ALLOW", error=False):
        self.calls = 0
        self.decision, self.error = decision, error

    async def review(self, action):
        self.calls += 1
        if self.error:
            raise OSError("Reviewer unavailable")
        return Review(decision=self.decision)


async def test_deterministic_policy_and_independent_review(tmp_path):
    reviewer = Reviewer()
    policy = ActionPolicy(ActionStore(tmp_path / "actions.db"), reviewer)
    assert (await policy.decide(action().model_copy(update={"action_class": "read"}))).decision == "ALLOW"
    assert reviewer.calls == 0
    assert (await policy.decide(action().model_copy(update={"action_class": "forbidden"}))).decision == "DENY"
    assert reviewer.calls == 0
    assert (await policy.decide(action())).decision == "ASK_USER"
    assert reviewer.calls == 1
    reviewer.decision = "DENY"
    assert (await policy.decide(action())).decision == "DENY"
    reviewer.error = True
    assert (await policy.decide(action())).decision == "ASK_USER"


async def test_reviewer_timeout(tmp_path):
    class Slow:
        async def review(self, action):
            await asyncio.sleep(10)
    policy = ActionPolicy(ActionStore(tmp_path / "actions.db"), Slow(), review_timeout=.001)
    assert (await policy.decide(action())).decision == "ASK_USER"


def test_exact_binding_expiry_scope_and_single_use(tmp_path):
    store = ActionStore(tmp_path / "actions.db")
    record = store.request(action())
    assert store.request(action()).id == record.id
    with pytest.raises(PermissionError):
        store.resolve(record.id, principal="other", approve=True)
    assert not store.consume(action())
    store.resolve(record.id, principal=action().principal, approve=True)
    assert not store.consume(action(volume="0.2"))
    assert store.consume(action())
    assert not store.consume(action())
    expired = store.request(action(volume="1"), lifetime_ms=-1)
    with pytest.raises(ValueError):
        store.resolve(expired.id, principal=action().principal, approve=True)


def test_effect_process_death_recovery_fencing_and_reconciliation(tmp_path):
    path = tmp_path / "actions.db"
    script = '''
import os, sys
from pathlib import Path
from nanobot.security.actions import Action, ActionStore
store=ActionStore(Path(sys.argv[1]))
a=Action(tool="trade_execute", action_class="consequential", principal="webui:user", parameters={"account":"demo", "symbol":"GOLD", "volume":"0.1"})
e=store.propose_effect(a,"request-1")
store.start_effect(e.id)
os._exit(17)
'''
    assert subprocess.run([sys.executable, "-c", script, str(path)]).returncode == 17
    store = ActionStore(path)
    effect = store.propose_effect(action(), "request-1")
    assert effect.state == "STARTED"
    assert store.recover() == 1
    with pytest.raises(ValueError):
        store.start_effect(effect.id)
    with pytest.raises(PermissionError):
        store.finish_effect(effect, state="SUCCEEDED")
    reconcile = store.claim_reconciliation(effect.id)
    assert store.finish_effect(reconcile, state="SUCCEEDED", provider_reference="order-1").state == "SUCCEEDED"
    assert store.recover() == 0
    with pytest.raises(ValueError):
        store.propose_effect(action(volume="1"), "request-1")


async def test_registry_cannot_bypass_approval(tmp_path):
    class Trade(Tool):
        action_class = "consequential"
        name, description = "trade_execute", "trade"
        parameters = {"type": "object", "properties": {"volume": {"type": "string"}}}
        calls = 0
        async def execute(self, **kwargs):
            self.calls += 1
            return "executed"
    store = ActionStore(tmp_path / "actions.db")
    registry = ToolRegistry(ActionPolicy(store))
    trade = Trade()
    registry.register(trade)
    result = await registry.execute("trade_execute", {"volume": "1"})
    assert result.is_error and trade.calls == 0
    requested = Action(tool="trade_execute", action_class="consequential", principal="gateway", parameters={"volume":"1"})
    record = store.request(requested)
    store.resolve(record.id, principal="gateway", approve=True)
    assert await registry.execute("trade_execute", {"volume": "1"}) == "executed"
    assert (await registry.execute("trade_execute", {"volume": "1"})).is_error
    assert trade.calls == 1


def test_secret_reference_not_value(tmp_path):
    store = SecretStore(tmp_path / "secrets")
    sentinel = "SENTINEL_PRIVATE_TOKEN_DO_NOT_LEAK"
    store.put("oanda", sentinel)
    assert store.resolve("oanda").reveal() == sentinel
    assert sentinel not in repr(store.resolve("oanda"))
    with pytest.raises(ValueError, match="reference"):
        store.resolve("../escape")
    with pytest.raises(ValueError, match="not configured"):
        store.resolve("missing")
