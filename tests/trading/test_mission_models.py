from decimal import Decimal

import pytest

from nanobot.security.actions import ActionStore
from nanobot.session.records import RecordStore
from nanobot.trading.mission_models import TradingGoal, TradingPlan


def test_durable_goal_and_immutable_plan_remain_separate_after_restart(tmp_path):
    journal = ActionStore(tmp_path/"state.db")
    goals = RecordStore("trading_goals",TradingGoal,journal)
    plans = RecordStore("trading_plans",TradingPlan,journal)
    goals.create(TradingGoal(id="goal",principal="websocket:main",responsibility_id="resp",account_id="demo",
        objective="Try to earn $300; target is not guaranteed",target_profit=Decimal(300),currency="USD",start_at=1,end_at=100))
    plans.create(TradingPlan(id="plan1",goal_id="goal",plan_version=1,market_scope=["gold"],
        monitoring_summary="Wait for evidence",execution_summary="No trade is required",
        risk_proposal_summary="Propose a bounded envelope",reevaluation_summary="After material event"))
    assert RecordStore("trading_goals",TradingGoal,ActionStore(journal.path)).get("goal").status == "DRAFT"
    assert RecordStore("trading_plans",TradingPlan,ActionStore(journal.path)).get("plan1").execution_summary == "No trade is required"
    with pytest.raises(ValueError):
        TradingGoal(id="bad",principal="websocket:main",responsibility_id="resp",account_id="demo",objective="300 at any cost",
            currency="USD",start_at=1,end_at=100,approved_by_user=True)
