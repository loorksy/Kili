from datetime import datetime, timezone
from decimal import Decimal

import pytest

from nanobot.security.actions import ActionStore, now_ms
from nanobot.trading.mission_models import FinishBehavior, MandateEnvelope, TradingGoal, TradingPlan
from nanobot.trading.missions import TradingMissions


def envelope(**updates):
    values = dict(mode="SIMULATION",account_id="demo",currency="USD",start_at=now_ms()-1000,
        expires_at=now_ms()+86_400_000,allocated_capital="2000",max_mission_loss="100",
        max_open_risk="50",max_risk_per_trade="20",max_concurrent_positions=2,max_pending_orders=2,
        allowed_instruments=["XAU-USD"],allowed_order_types=["market","limit","stop"],
        allowed_actions=["open","modify_position","modify_order","cancel_order","close_position"],
        breach_behavior=FinishBehavior(cancel_pending=True,close_positions=True),
        target_behavior=FinishBehavior(cancel_pending=True,close_positions=True),
        expiry_behavior=FinishBehavior(cancel_pending=True,close_positions=False),
        emergency_behavior=FinishBehavior(cancel_pending=True,close_positions=True))
    return MandateEnvelope.model_validate({**values,**updates})


async def proposed(tmp_path,client,**updates):
    service = TradingMissions(client,ActionStore(tmp_path/"missions.db"))
    goal = service.create_goal(TradingGoal(id="goal",principal="websocket:main",responsibility_id="resp",
        account_id="demo",objective="Try to make $300; no guarantee",target_profit=Decimal(300),
        currency="USD",start_at=now_ms()-10_000,end_at=now_ms()+172_800_000))
    plan = service.create_plan(goal.principal,TradingPlan(id="plan1",goal_id=goal.id,plan_version=1,
        market_scope=["XAU-USD"],monitoring_summary="Inspect market conditions",execution_summary="May wait",
        risk_proposal_summary="Suggest $100 mission cap",reevaluation_summary="After meaningful event",
        evidence_refs=["account:demo","quote:oanda"]))
    mandate,approval = await service.propose(goal.principal,goal.id,plan.id,envelope(**updates))
    return service,goal,plan,mandate,approval


async def test_goal_plan_mandate_exact_user_binding_and_versions(tmp_path,client):
    service,goal,plan,mandate,approval = await proposed(tmp_path,client)
    assert approval.action.parameters["profit_target_is_aspirational"] is True
    with pytest.raises(PermissionError):
        await service.activate(goal.principal,mandate.id)
    with pytest.raises(PermissionError):
        service.journal.resolve(approval.id,principal="websocket:other",approve=True)
    service.journal.resolve(approval.id,principal=goal.principal,approve=True)
    active = await service.activate(goal.principal,mandate.id)
    assert active.status == "ACTIVE" and active.approved_envelope == mandate.envelope
    with pytest.raises(ValueError):
        await service.activate(goal.principal,mandate.id)
    next_plan = plan.model_copy(update={"id":"plan2","plan_version":2,"execution_summary":"Take no trade"})
    service.create_plan(goal.principal,next_plan)
    assert service.plans.get("plan1").execution_summary == "May wait"
    assert service.mandates.get(active.id).envelope.max_mission_loss == Decimal(100)
    reduced = service.reduce(goal.principal,active.id,active.envelope.model_copy(update={"max_risk_per_trade":Decimal(10)}))
    assert reduced.envelope.max_risk_per_trade == Decimal(10)
    with pytest.raises(PermissionError):
        service.reduce(goal.principal,active.id,reduced.envelope.model_copy(update={"max_mission_loss":Decimal(200)}))


async def test_live_feature_is_never_silently_enabled(tmp_path,client):
    service,goal,_,mandate,approval = await proposed(tmp_path,client,mode="LIVE")
    service.journal.resolve(approval.id,principal=goal.principal,approve=True)
    with pytest.raises(PermissionError,match="disabled"):
        await service.activate(goal.principal,mandate.id)


async def test_user_denial_cancels_the_exact_draft_authority(tmp_path,client):
    service,goal,_,mandate,approval = await proposed(tmp_path,client)
    service.journal.resolve(approval.id,principal=goal.principal,approve=False)
    assert service.mandates.get(mandate.id).status == "CANCELLED"
    with pytest.raises(ValueError):
        await service.activate(goal.principal,mandate.id)


def test_required_loss_breach_and_time_boundary():
    for changes in ({"max_mission_loss":None},{"breach_behavior":None},{"expires_at":0},
                    {"max_mission_loss":"Infinity"},{"supervision_position_id":"1"}):
        with pytest.raises(ValueError):
            envelope(**changes)


def test_risk_calculates_broker_values_not_model_claims():
    from nanobot.trading.metaapi import BrokerPrice, SymbolSpec
    from nanobot.trading.risk import fresh_price, stop_risk
    spec = SymbolSpec(symbol="GOLD",digits=2,minVolume=".01",maxVolume="100",volumeStep=".01",
        tradeMode="SYMBOL_TRADE_MODE_FULL",contractSize="100",currencyProfit="USD")
    price = BrokerPrice(symbol="GOLD",bid="2700",ask="2701",time=datetime.now(timezone.utc).isoformat())
    assert stop_risk("buy",Decimal(2701),Decimal(2699),Decimal(".1"),spec,price,"USD") == Decimal(20)
    assert stop_risk("buy",Decimal(2701),Decimal(2702),Decimal(".1"),spec,price,"USD") == 0
    with pytest.raises(ValueError):
        stop_risk("buy",Decimal(2701),None,Decimal(".1"),spec,price,"USD")
    with pytest.raises(ValueError):
        stop_risk("buy",Decimal(2701),Decimal(2699),Decimal(".1"),spec,price,"EUR")
    with pytest.raises(ValueError):
        fresh_price(price.model_copy(update={"time":"2020-01-01T00:00:00Z"}))
