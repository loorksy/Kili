import json
from decimal import Decimal

import pytest
from mission_helpers import broker_fixture
from test_missions import proposed
from trade_helpers import service_for

from nanobot.agent.tools.context import RequestContext, ResponsibilityExecution, request_context
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.trade_execute import TradeExecuteTool
from nanobot.security.actions import ActionPolicy, Review
from nanobot.session.responsibilities import ResponsibilityStore, StaleExecutionError
from nanobot.trading.execution import TradeExecutor
from nanobot.trading.proposals import TradeIntent


async def delegated_setup(tmp_path, *, mode="LIVE",supervision=False,**changes):
    client,state = broker_fixture(tmp_path)
    if supervision:
        state["positions"].append({"id":"manual-1","symbol":"GOLDm","type":"POSITION_TYPE_BUY","volume":".1",
            "openPrice":"2701","stopLoss":"2699","profit":"0"})
        changes.update(supervision_position_id="manual-1",allowed_actions=["modify_position","close_position","cancel_order"])
    service,goal,plan,mandate,approval = await proposed(tmp_path,client,mode=mode,**changes)
    service.live_enabled = True  # Trusted operator switch, never a tool parameter.
    store = ResponsibilityStore(tmp_path/"workspace")
    responsibility = store.create(objective=goal.objective,session_key=goal.principal,channel="websocket",chat_id="main")
    goal = service.goals.get(goal.id)
    goal.responsibility_id = responsibility.id
    service.goals.save(goal)
    mandate.responsibility_id = responsibility.id
    # Bind the new exact responsibility before obtaining any user approval.
    mandate = service.mandates.save(mandate)
    approval = service.journal.request(service.approval_action(mandate))
    service.journal.resolve(approval.id,principal=goal.principal,approve=True)
    mandate = await service.activate(goal.principal,mandate.id)
    proposals = await service_for(tmp_path/"proposals",client)
    # Use the same protected transaction domain as the mission ledger.
    from nanobot.session.records import RecordStore
    from nanobot.trading.proposals import TradePreview, TradeProposal
    proposals.proposals = RecordStore("trade_proposals",TradeProposal,service.journal)
    proposals.previews = RecordStore("trade_previews",TradePreview,service.journal)
    executor = TradeExecutor(proposals,service.journal,live_enabled=True)
    registry = ToolRegistry(ActionPolicy(service.journal))
    registry.register(TradeExecuteTool(executor))
    claim = store.claim_foreground(responsibility.id)
    context = RequestContext(channel="websocket",chat_id="main",session_key=goal.principal)
    context.responsibility_scope.executions[responsibility.id] = ResponsibilityExecution(store=store,claim=claim)
    return service,mandate,executor,registry,context,state


async def preview_for(executor,mandate,**kwargs):
    intent = TradeIntent(canonical_instrument="XAU-USD",volume=Decimal(".1"),stop_loss=Decimal(2699),**kwargs)
    record = executor.proposals.create(mandate.principal,intent,responsibility_id=mandate.responsibility_id,mandate_id=mandate.id)
    return await executor.proposals.preview(record.id,mandate.principal)


async def test_prior_mandate_executes_once_without_per_trade_approval(tmp_path):
    service,mandate,executor,registry,context,state = await delegated_setup(tmp_path)
    with request_context(context):
        preview = await preview_for(executor,mandate)
        result = json.loads(await registry.execute("trade_execute",{"preview_id":preview.id}))
        assert result["state"] == "SUCCEEDED" and len(state["calls"]) == 1
        assert json.loads(await registry.execute("trade_execute",{"preview_id":preview.id}))["state"] == "SUCCEEDED"
        assert len(state["calls"]) == 1
    effect = service.journal.find_effect(preview.effect_key)
    assert effect.mandate_id == mandate.id and effect.approval_id is None
    assert len(service.reservations.list()) == 1
    reservation = service.reservations.list()[0]
    assert reservation.review_decision == "ALLOW" and reservation.review_source == "deterministic"
    assert reservation.mission_budget_after == reservation.mission_budget_before-reservation.risk
    entry = next(item for item in executor.journal.list() if item.kind == "SUCCEEDED")
    assert entry.mandate_id == mandate.id and entry.goal_id == mandate.goal_id
    assert entry.plan_version == 1 and entry.risk_assessment["semantics_version"] == 1
    assert entry.review_source == "deterministic" and entry.mission_budget_after is not None
    assert "MISSION_SECRET_SENTINEL" not in json.dumps(result)


@pytest.mark.parametrize("change",["no_stop","too_much_risk","netting","disconnect","no_ownership","emergency"])
async def test_hard_boundaries_cannot_be_overridden_by_a_mandate(tmp_path,change):
    service,mandate,executor,registry,context,state = await delegated_setup(tmp_path)
    with request_context(context):
        preview = await preview_for(executor,mandate)
        if change in {"no_stop","too_much_risk"}:
            proposal = executor.proposals.proposals.get(preview.proposal_id)
            proposal.intent.stop_loss = None if change == "no_stop" else Decimal(2600)
            executor.proposals.proposals.save(proposal)
            preview = await executor.proposals.preview(proposal.id,mandate.principal)
        if change == "netting":
            state["margin_mode"] = "ACCOUNT_MARGIN_MODE_RETAIL_NETTING"
        if change == "disconnect":
            state["connected"] = False
        if change == "no_ownership":
            context.responsibility_scope.executions.clear()
        if change == "emergency":
            service.control(mandate.principal,mandate.id,"emergency_stop",user=True)
        result = await registry.execute("trade_execute",{"preview_id":preview.id})
        assert result.is_error and not state["calls"]


async def test_reviewer_escalation_requires_exact_action_approval_and_keeps_risk_checks(tmp_path):
    service,mandate,executor,registry,context,state = await delegated_setup(tmp_path)
    class Reviewer:
        async def review(self,action):
            assert action.parameters["delegation_review"]["mandate"]["max_mission_loss"] == "100"
            return Review(decision="ASK_USER",reason="Escalate")
    registry.policy.reviewer = Reviewer()
    with request_context(context):
        preview = await preview_for(executor,mandate)
        result = await registry.execute("trade_execute",{"preview_id":preview.id})
        assert result.is_error and not state["calls"]
        approval = service.journal.approvals_for_proposal(preview.proposal_id)[0]
        service.journal.resolve(approval.id,principal=mandate.principal,approve=True)
        assert json.loads(await registry.execute("trade_execute",{"preview_id":preview.id}))["state"] == "SUCCEEDED"


async def test_stale_worker_does_not_consume_authority(tmp_path):
    service,mandate,executor,registry,context,state = await delegated_setup(tmp_path)
    with pytest.raises(StaleExecutionError), request_context(context):
        preview = await preview_for(executor,mandate)
        execution = next(iter(context.responsibility_scope.executions.values()))
        execution.store.takeover(mandate.responsibility_id)
        assert (await registry.execute("trade_execute",{"preview_id":preview.id})).is_error
        assert not state["calls"]


async def test_changed_envelope_invalidates_old_preview(tmp_path):
    service,mandate,executor,registry,context,state = await delegated_setup(tmp_path)
    with request_context(context):
        preview = await preview_for(executor,mandate)
        service.reduce(mandate.principal,mandate.id,mandate.envelope.model_copy(update={"max_risk_per_trade":Decimal(10)}))
        assert (await registry.execute("trade_execute",{"preview_id":preview.id})).is_error
        assert not state["calls"]
