import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from threading import Barrier

import pytest
from test_delegation import delegated_setup, preview_for

from nanobot.agent.tools.context import request_context
from nanobot.security.actions import now_ms
from nanobot.trading.mission_models import RiskAssessment
from nanobot.trading.missions import TradingMissions
from nanobot.webui.mission_resources import MissionControl, control_mission, mission_snapshot


async def test_cancelled_authority_cannot_be_resurrected_via_pause(tmp_path):
    service,mandate,executor,registry,context,state = await delegated_setup(tmp_path)
    service.control(mandate.principal,mandate.id,"cancel",user=True)
    with pytest.raises(PermissionError):
        service.control(mandate.principal,mandate.id,"pause",user=True)
    with pytest.raises(PermissionError):
        service.control(mandate.principal,mandate.id,"resume",user=True)
    with request_context(context):
        preview = await preview_for(executor,mandate)
        assert (await registry.execute("trade_execute",{"preview_id":preview.id})).is_error
    assert not state["calls"]


async def test_account_risk_ledger_serializes_two_concurrent_missions(tmp_path):
    service,mandate,_,_,_,state = await delegated_setup(tmp_path)
    second = mandate.model_copy(deep=True,update={"id":"second","goal_id":"goal2"})
    service.mandates.create(second)
    guard = service.guardrails.get("demo")
    guard.max_open_risk,guard.max_active_mandates = Decimal(15),2
    service.guardrails.save(guard)
    barrier = Barrier(2)
    def reserve(record):
        risk = RiskAssessment(account_id="demo",mandate_id=record.id,mandate_revision=record.revision,
            fetched_at=now_ms(),fingerprint=record.id,risk_increasing=True,proposed_risk=Decimal(10),
            incremental_risk=Decimal(10),open_risk=Decimal(0),account_open_risk=Decimal(0),
            mission_pnl=Decimal(0),remaining_loss=Decimal(100),position_count=0,order_count=0,
            proposed_notional=Decimal(100),proposed_margin=Decimal(10),margin_usage=Decimal(0),account_equity=Decimal(10000))
        barrier.wait()
        try:
            with service.journal.transaction() as db:
                TradingMissions.reserve_in_transaction(db,risk,"effect_"+record.id,operation="open",pending=True)
            return True
        except PermissionError:
            return False
    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(reserve,[mandate,second]))
    assert sorted(results) == [False,True]
    assert sum(r.risk for r in service.reservations.list()) == 10
    assert not state["calls"]


async def test_mission_resources_require_exact_conversation_and_user_controls(tmp_path):
    service,mandate,_,_,_,_ = await delegated_setup(tmp_path)
    with pytest.raises(PermissionError):
        mission_snapshot(service,"websocket:other",mandate.id)
    with pytest.raises(PermissionError):
        await control_mission(service,MissionControl(session_key="websocket:other",mandate_id=mandate.id,operation="cancel"))
    with pytest.raises(PermissionError):
        service.control(mandate.principal,mandate.id,"emergency_stop",user=False)
    public = await control_mission(service,MissionControl(session_key=mandate.principal,mandate_id=mandate.id,operation="emergency_stop"))
    assert public["status"] == "RISK_STOPPED" and service.guardrails.get("demo").emergency_stop
    assert "MISSION_SECRET_SENTINEL" not in json.dumps(public)


async def test_connection_replacement_cannot_transfer_mandate_authority(tmp_path):
    from nanobot.trading.mission_observation import refresh
    service,mandate,_,_,_,state = await delegated_setup(tmp_path)
    service.client.connection = service.client.connection.model_copy(update={"account_id":"another-account"})
    with pytest.raises(PermissionError,match="account"):
        await refresh(service,service.mandates.get(mandate.id))
    with pytest.raises(PermissionError,match="account"):
        await service.activate(mandate.principal,mandate.id)
    assert not state["calls"]


async def test_target_reached_blocks_next_entry_without_waiting_for_account_timer(tmp_path):
    service,mandate,executor,registry,context,state = await delegated_setup(tmp_path,risk_increase_permissions=["add_exposure"])
    with request_context(context):
        first = await preview_for(executor,mandate)
        assert json.loads(await registry.execute("trade_execute",{"preview_id":first.id}))["state"] == "SUCCEEDED"
        state["positions"][0]["profit"] = "340"
        second = await preview_for(executor,mandate)
        assert (await registry.execute("trade_execute",{"preview_id":second.id})).is_error
        assert service.mandates.get(mandate.id).status == "TARGET_REACHED"
        assert len(state["calls"]) == 1


async def test_completed_responsibility_cannot_consume_autonomous_authority(tmp_path):
    _,mandate,executor,registry,context,state = await delegated_setup(tmp_path)
    with request_context(context):
        preview = await preview_for(executor,mandate)
        execution = context.responsibility_scope.executions[mandate.responsibility_id]
        record = execution.store.get(mandate.responsibility_id)
        record.state = "COMPLETED"
        execution.store.save(record,claim=execution.claim)
        assert (await registry.execute("trade_execute",{"preview_id":preview.id})).is_error
        assert not state["calls"]


async def test_direct_executor_context_does_not_mint_its_own_review(tmp_path):
    from nanobot.security.actions import Action, action_authorization
    service,mandate,executor,_,context,state = await delegated_setup(tmp_path)
    with request_context(context):
        preview = await preview_for(executor,mandate)
        action = Action(tool="trade_execute",action_class="consequential",principal=mandate.principal,
            responsibility_id=mandate.responsibility_id,parameters=preview.material_action())
        with action_authorization(action), pytest.raises(PermissionError,match="central policy"):
            await executor.execute(preview.id,mandate.principal)
        assert service.journal.find_effect(preview.effect_key).state == "PROPOSED"
        assert not service.reservations.list() and not state["calls"]


async def test_two_user_approved_simulation_missions_share_observed_account_risk(tmp_path):
    from nanobot.agent.tools.context import RequestContext, ResponsibilityExecution
    from nanobot.trading.mission_observation import refresh
    from nanobot.trading.simulation import MissionSimulation
    service,first,executor,registry,context,state = await delegated_setup(tmp_path,mode="SIMULATION")
    with request_context(context):
        preview = await preview_for(executor,first)
        assert json.loads(await registry.execute("trade_execute",{"preview_id":preview.id}))["state"] == "SUCCEEDED"
    await refresh(service,service.mandates.get(first.id))
    guard = service.guardrails.get("demo")
    guard.max_open_risk,guard.max_active_mandates = Decimal(25),2
    await control_mission(service,MissionControl(session_key=first.principal,mandate_id=first.id,
        operation="guardrails",guardrails=guard))
    store = next(iter(context.responsibility_scope.executions.values())).store
    responsibility = store.create(objective="Another bounded gold mission",session_key=first.principal,channel="websocket",chat_id="main")
    original = service.goals.get(first.goal_id)
    goal = service.create_goal(original.model_copy(update={"id":"second-goal","responsibility_id":responsibility.id,"status":"DRAFT"}))
    plan = service.create_plan(first.principal,service.plans.get(first.plan_id).model_copy(update={"id":"second-plan","goal_id":goal.id}))
    second,approval = await service.propose(first.principal,goal.id,plan.id,first.envelope)
    service.journal.resolve(approval.id,principal=first.principal,approve=True)
    second = await service.activate(first.principal,second.id)
    ctx = RequestContext(channel="websocket",chat_id="main",session_key=first.principal)
    ctx.responsibility_scope.executions[responsibility.id] = ResponsibilityExecution(store=store,claim=store.claim_foreground(responsibility.id))
    with request_context(ctx):
        preview = await preview_for(executor,second)
        result = await registry.execute("trade_execute",{"preview_id":preview.id})
        assert result.is_error and "Account risk budget" in result
    assert len(MissionSimulation(service,first).get().positions) == 1
    assert not MissionSimulation(service,second).get().positions and not state["calls"]


@pytest.mark.parametrize("mode",["SIMULATION","LIVE"])
async def test_account_ledger_does_not_mix_live_and_virtual_exposure(tmp_path,mode):
    service,first,_,_,_,state = await delegated_setup(tmp_path,mode=mode)
    guard = service.guardrails.get(first.envelope.account_id)
    guard.max_active_mandates = 2
    await control_mission(service,MissionControl(session_key=first.principal,mandate_id=first.id,
        operation="guardrails",guardrails=guard))
    original = service.goals.get(first.goal_id)
    goal = service.create_goal(original.model_copy(update={"id":"other-mode-goal","status":"DRAFT"}))
    plan = service.create_plan(first.principal,service.plans.get(first.plan_id).model_copy(update={"id":"other-mode-plan","goal_id":goal.id}))
    other_mode = "LIVE" if mode == "SIMULATION" else "SIMULATION"
    other,approval = await service.propose(first.principal,goal.id,plan.id,first.envelope.model_copy(update={"mode":other_mode}))
    service.journal.resolve(approval.id,principal=first.principal,approve=True)
    with pytest.raises(PermissionError,match="Live and simulation"):
        await service.activate(first.principal,other.id)
    assert service.mandates.get(other.id).status == "AWAITING_MANDATE_APPROVAL"
    assert not state["calls"]


async def test_pending_expiry_cannot_be_extended_past_signed_duration(tmp_path):
    from datetime import datetime, timedelta, timezone

    from nanobot.trading.proposals import TradeIntent
    _,mandate,executor,registry,context,state = await delegated_setup(tmp_path)
    with request_context(context):
        first = await preview_for(executor,mandate,order_type="limit",price=Decimal(2700))
        assert json.loads(await registry.execute("trade_execute",{"preview_id":first.id}))["state"] == "SUCCEEDED"
        proposal = executor.proposals.create(mandate.principal,TradeIntent(canonical_instrument="XAU-USD",
            operation="modify_order",target_id=state["orders"][0]["id"],
            price=Decimal(2700),
            expiration_time=(datetime.now(timezone.utc)+timedelta(days=3)).isoformat()),
            responsibility_id=mandate.responsibility_id,mandate_id=mandate.id)
        preview = await executor.proposals.preview(proposal.id,mandate.principal)
        assert (await registry.execute("trade_execute",{"preview_id":preview.id})).is_error
        assert len(state["calls"]) == 1


@pytest.mark.parametrize("field,value",[("max_notional","100"),("max_margin_usage","50")])
async def test_deterministic_hard_limits_block_risk_increase(tmp_path,field,value):
    service,mandate,executor,registry,context,state = await delegated_setup(tmp_path,**{field:value})
    current = service.mandates.get(mandate.id)
    service.mandates.save(current)
    with request_context(context):
        preview = await preview_for(executor,mandate)
        result = await registry.execute("trade_execute",{"preview_id":preview.id})
        assert result.is_error and not state["calls"]


@pytest.mark.parametrize("limit",["max_daily_loss","max_drawdown"])
async def test_daily_loss_and_drawdown_use_trusted_pnl_not_profit_target(tmp_path,limit):
    from datetime import datetime, timezone

    from nanobot.trading.proposals import TradeIntent
    from nanobot.trading.risk import assess
    service,mandate,_,_,_,_ = await delegated_setup(tmp_path,**{limit:"5"})
    observation = await service.observe()
    mandate.realized_pnl = Decimal(-6)
    mandate.daily_pnl[datetime.now(timezone.utc).date().isoformat()] = Decimal(-6)
    spec = await service.client.specification("GOLDm")
    price = await service.client.price("GOLDm")
    with pytest.raises(PermissionError,match="daily loss/drawdown"):
        assess(mandate,TradeIntent(canonical_instrument="XAU-USD",volume=Decimal(".1"),stop_loss=Decimal(2699)),
            "exact",observation,{"GOLDm":spec},{"GOLDm":price},"GOLDm",[],[],Decimal(100))
