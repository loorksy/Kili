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
