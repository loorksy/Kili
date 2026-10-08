import json
from decimal import Decimal

import pytest
from test_delegation import delegated_setup, preview_for

from nanobot.agent.tools.context import request_context
from nanobot.trading.mission_observation import refresh
from nanobot.trading.mission_watchers import MissionWatchers
from nanobot.trading.proposals import TradeIntent


async def management(executor,mandate,registry,operation,**parameters):
    record = executor.proposals.create(mandate.principal,TradeIntent(canonical_instrument="XAU-USD",
        operation=operation,target_id="manual-1",**parameters),responsibility_id=mandate.responsibility_id,mandate_id=mandate.id)
    preview = await executor.proposals.preview(record.id,mandate.principal)
    return await registry.execute("trade_execute",{"preview_id":preview.id})


async def test_supervision_tightens_profit_stop_and_validates_partial_close(tmp_path):
    service,mandate,executor,registry,context,state = await delegated_setup(tmp_path,supervision=True)
    state["bid"],state["ask"] = "2705","2706"
    with request_context(context):
        denied = await management(executor,mandate,registry,"modify_position",stop_loss=Decimal(2698))
        assert denied.is_error and not state["calls"]
        result = await management(executor,mandate,registry,"modify_position",stop_loss=Decimal(2704))
        assert json.loads(result)["state"] == "SUCCEEDED"
        assert state["positions"][0]["stopLoss"] == "2704"
        assert json.loads(await management(executor,mandate,registry,"close_position",volume=Decimal(".03")))["state"] == "SUCCEEDED"
        assert state["positions"][0]["volume"] == "0.07"
        with pytest.raises(ValueError,match="Volume"):
            await management(executor,mandate,registry,"close_position",volume=Decimal(".035"))
        assert json.loads(await management(executor,mandate,registry,"close_position"))["state"] == "SUCCEEDED"
        assert not state["positions"]


async def test_manual_supervised_terms_change_freezes_management(tmp_path):
    service,mandate,executor,registry,context,state = await delegated_setup(tmp_path,supervision=True)
    state["positions"][0]["stopLoss"] = "2698"
    with request_context(context):
        result = await management(executor,mandate,registry,"modify_position",stop_loss=Decimal(2699))
        assert result.is_error and not state["calls"]
        current = service.mandates.get(mandate.id)
        assert current.status == "NEEDS_ATTENTION"
        assert service.control(mandate.principal,mandate.id,"pause",user=True).status == "NEEDS_ATTENTION"


async def test_simulation_cannot_reach_broker_and_reopens_persistent_book(tmp_path):
    service,mandate,executor,registry,context,state = await delegated_setup(tmp_path,mode="SIMULATION")
    with request_context(context):
        preview = await preview_for(executor,mandate)
        result = json.loads(await registry.execute("trade_execute",{"preview_id":preview.id}))
        assert result["state"] == "SUCCEEDED" and not state["calls"]
    from nanobot.trading.simulation import MissionSimulation
    assert len(MissionSimulation(service,mandate).get().positions) == 1
    current,observation,positions,_ = await refresh(service,service.mandates.get(mandate.id))
    assert current.unrealized_pnl == Decimal(-10)
    assert positions[0].id.startswith("sim-")
    assert observation.account.equity == Decimal(9990)
    watcher = MissionWatchers(executor,next(iter(context.responsibility_scope.executions.values())).store)
    current.next_check_at = 0
    service.mandates.save(current)
    await watcher.run_due()
    current = service.mandates.get(mandate.id)
    count = len(watcher.responsibilities.get(mandate.responsibility_id).wakes)
    current.next_check_at = 0
    service.mandates.save(current)
    await watcher.run_due()
    assert len(watcher.responsibilities.get(mandate.responsibility_id).wakes) == count
    assert not state["calls"]


@pytest.mark.parametrize("event",["target","loss","expiry","emergency"])
async def test_lifecycle_performs_only_the_user_approved_finish_behavior(tmp_path,event):
    service,mandate,executor,registry,context,state = await delegated_setup(tmp_path,mode="SIMULATION",max_open_risk="500")
    with request_context(context):
        preview = await preview_for(executor,mandate)
        assert json.loads(await registry.execute("trade_execute",{"preview_id":preview.id}))["state"] == "SUCCEEDED"
    watcher = MissionWatchers(executor,next(iter(context.responsibility_scope.executions.values())).store)
    if event == "target":
        state["bid"],state["ask"] = "2735","2736"
    elif event == "loss":
        state["bid"],state["ask"] = "2680","2681"
    elif event == "expiry":
        from nanobot.security.actions import now_ms
        current = service.mandates.get(mandate.id)
        service.reduce(mandate.principal,mandate.id,current.envelope.model_copy(update={"expires_at":now_ms()-1}))
    else:
        service.control(mandate.principal,mandate.id,"emergency_stop",user=True)
    current = service.mandates.get(mandate.id)
    current.next_check_at = 0
    service.mandates.save(current)
    await watcher.run_due()
    current = service.mandates.get(mandate.id)
    from nanobot.trading.simulation import MissionSimulation
    book = MissionSimulation(service,current).get()
    if event == "target":
        assert current.status == "TARGET_REACHED" and not book.positions
    elif event in {"loss","emergency"}:
        assert current.status == "RISK_STOPPED" and not book.positions
    else:
        assert current.status == "EXPIRED" and len(book.positions) == 1
    assert not state["calls"]


async def test_pending_orders_reserve_risk_and_can_be_cancelled(tmp_path):
    service,mandate,executor,registry,context,state = await delegated_setup(tmp_path)
    with request_context(context):
        preview = await preview_for(executor,mandate,order_type="limit",price=Decimal(2700))
        assert preview.intent.expiration_time is not None
        assert json.loads(await registry.execute("trade_execute",{"preview_id":preview.id}))["state"] == "SUCCEEDED"
        reservation = service.reservations.list()[0]
        assert reservation.risk == Decimal(10) and reservation.entry_kind == "pending"
        target = state["orders"][0]["id"]
        proposal = executor.proposals.create(mandate.principal,TradeIntent(canonical_instrument="XAU-USD",
            operation="cancel_order",target_id=target),responsibility_id=mandate.responsibility_id,mandate_id=mandate.id)
        preview = await executor.proposals.preview(proposal.id,mandate.principal)
        assert json.loads(await registry.execute("trade_execute",{"preview_id":preview.id}))["state"] == "SUCCEEDED"
        assert not state["orders"]
