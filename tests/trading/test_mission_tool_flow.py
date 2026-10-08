import json

import pytest
from mission_helpers import broker_fixture
from test_missions import envelope

from nanobot.agent.tools.context import (
    RequestContext,
    ResponsibilityExecution,
    ToolContext,
    request_context,
)
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.trading_mission import MissionRequest, TradingMissionTool
from nanobot.config.schema import Config
from nanobot.security.actions import ActionPolicy, ActionStore, now_ms
from nanobot.session.manager import SessionManager
from nanobot.trading.missions import TradingMissions


async def test_scripted_natural_objective_becomes_plan_and_user_bound_authority(tmp_path):
    client,state = broker_fixture(tmp_path)
    config = Config().tools
    config.integrations.metaapi = client.connection
    sessions = SessionManager(tmp_path/"workspace")
    responsibility = sessions.responsibilities.create(objective="Try to make $300 in two days",
        session_key="websocket:main",channel="websocket",chat_id="main")
    tool = TradingMissionTool(ToolContext(config=config,workspace=str(sessions.workspace),sessions=sessions))
    tool.service = TradingMissions(client,ActionStore(tmp_path/"missions.db"))
    registry = ToolRegistry(ActionPolicy(tool.service.journal))
    registry.register(tool)
    context = RequestContext(channel="websocket",chat_id="main",session_key="websocket:main")
    context.responsibility_scope.executions[responsibility.id] = ResponsibilityExecution(store=sessions.responsibilities,
        claim=sessions.responsibilities.claim_foreground(responsibility.id))
    with request_context(context):
        # A scripted acting model selects structured arguments from the user's
        # objective; real-provider inference is deliberately unnecessary here.
        goal = json.loads(await registry.execute("trading_mission",{"operation":"create_goal", "goal":{
            "objective":"Try to make $300 in two days; use gold, propose bounded risk first",
            "target_profit":"300","currency":"USD","start_at":now_ms()-10000,"end_at":now_ms()+172800000},
            "responsibility_id":responsibility.id}))
        plan = json.loads(await registry.execute("trading_mission",{"operation":"create_plan","goal_id":goal["id"],"plan":{
            "market_scope":["XAU-USD"],"monitoring_summary":"Use event/time wakeups",
            "execution_summary":"WAIT if there is no suitable opportunity",
            "risk_proposal_summary":"Suggest $100 maximum mission loss, $20 per trade",
            "reevaluation_summary":"After material account/market changes",
            "evidence_refs":["account:demo","quote:oanda:XAU_USD"]}}))
        proposed = await registry.execute("trading_mission",{"operation":"propose","goal_id":goal["id"],
            "plan_id":plan["id"],"envelope":envelope().model_dump(mode="json")})
        assert "not guaranteed" in proposed and "action_approval" in proposed
        mandate = tool.service.mandates.list()[0]
        assert (await registry.execute("trading_mission",{"operation":"activate","mandate_id":mandate.id})).is_error
        approval = tool.service.journal.pending_resolutions()
        assert not approval  # The actor did not resolve its proposed approval.
        with tool.service.journal.transaction() as db:
            approval_id = db.execute("SELECT id FROM approvals").fetchone()[0]
        tool.service.journal.resolve(approval_id,principal="websocket:main",approve=True)
        active = json.loads(await registry.execute("trading_mission",{"operation":"activate","mandate_id":mandate.id}))
        assert active["status"] == "ACTIVE" and active["envelope"]["max_mission_loss"] == "100"
        assert not state["calls"]
    for field in ("approved_by","approved_at","policy_version","review_decision"):
        with pytest.raises(ValueError):
            MissionRequest.model_validate({"operation":"activate","mandate_id":mandate.id,field:"forged"})
