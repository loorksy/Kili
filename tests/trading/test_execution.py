import json
from decimal import Decimal

import httpx
import pytest
from trade_helpers import service_for

from nanobot.agent.tools.context import RequestContext, ResponsibilityExecution, request_context
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.trade_execute import TradeExecuteTool, TradeReconcileTool
from nanobot.security.actions import Action, ActionPolicy
from nanobot.session.responsibilities import ResponsibilityStore
from nanobot.trading.execution import TradeExecutor
from nanobot.trading.proposals import TradeIntent


async def setup(tmp_path,client):
    proposals=await service_for(tmp_path,client)
    proposal=proposals.create("websocket:main",TradeIntent(canonical_instrument="XAU-USD",volume=Decimal(".1")))
    preview=await proposals.preview(proposal.id,proposal.principal)
    executor=TradeExecutor(proposals,proposals.proposals.journal)
    registry=ToolRegistry(ActionPolicy(executor.effects))
    registry.register(TradeExecuteTool(executor))
    registry.register(TradeReconcileTool(executor))
    return preview,executor,registry


def approve(preview,store,responsibility_id=None):
    action=Action(tool="trade_execute",action_class="consequential",principal="websocket:main",
                  responsibility_id=responsibility_id,parameters=preview.material_action())
    record=store.request(action)
    store.resolve(record.id,principal=action.principal,approve=True)
    return record


async def test_approved_simulated_execution_exact_binding_and_no_replay(tmp_path,client):
    preview,executor,registry=await setup(tmp_path,client)
    calls=[]
    transport=client.transport
    def handler(request):
        if request.method == "POST":
            calls.append(request)
            assert executor.effects.find_effect(preview.effect_key).state == "STARTED"
            assert json.loads(request.content)["volume"] == .1
            return httpx.Response(200,json={"stringCode":"TRADE_RETCODE_DONE","orderId":"order-1"})
        return transport.handler(request)
    client.transport=httpx.MockTransport(handler)
    with request_context(RequestContext(channel="websocket",chat_id="main",session_key="websocket:main")):
        assert (await registry.execute("trade_execute",{"preview_id":preview.id})).is_error
        assert not calls
        approve(preview,executor.effects)
        result=json.loads(await registry.execute("trade_execute",{"preview_id":preview.id}))
        assert result["state"] == "SUCCEEDED" and len(calls) == 1
        assert json.loads(await registry.execute("trade_execute",{"preview_id":preview.id}))["state"] == "SUCCEEDED"
        assert len(calls) == 1
        assert "PRIVATE_META_SENTINEL" not in json.dumps(result)
        with pytest.raises(PermissionError):
            await executor.execute(preview.id,"websocket:main")
    assert executor.proposals.proposals.get(preview.proposal_id).status == "EXECUTED"
    assert {entry.kind for entry in executor.journal.list()} == {"STARTED","SUCCEEDED"}


async def test_changed_preview_needs_new_approval(tmp_path,client):
    preview,executor,registry=await setup(tmp_path,client)
    approve(preview,executor.effects)
    newer=await executor.proposals.preview(preview.proposal_id,"websocket:main")
    with request_context(RequestContext(channel="websocket",chat_id="main",session_key="websocket:main")):
        assert (await registry.execute("trade_execute",{"preview_id":preview.id})).is_error
        assert (await registry.execute("trade_execute",{"preview_id":newer.id})).is_error
    assert executor.effects.find_effect(newer.effect_key) is None


async def test_timeout_never_retries_and_reconciliation_is_conservative(tmp_path,client):
    preview,executor,registry=await setup(tmp_path,client)
    transport=client.transport
    calls=[]
    matches=[]
    def handler(request):
        if request.method == "POST":
            calls.append(request)
            raise httpx.ReadTimeout("PRIVATE_META_SENTINEL",request=request)
        if request.url.path.endswith("positions"):
            return httpx.Response(200,json=matches)
        if request.url.path.endswith("orders") or "/history-orders/" in request.url.path:
            return httpx.Response(200,json=[])
        return transport.handler(request)
    client.transport=httpx.MockTransport(handler)
    context=RequestContext(channel="websocket",chat_id="main",session_key="websocket:main")
    with request_context(context):
        approve(preview,executor.effects)
        result=json.loads(await registry.execute("trade_execute",{"preview_id":preview.id}))
        assert result["state"] == "UNCERTAIN" and len(calls) == 1
        assert "PRIVATE_META_SENTINEL" not in json.dumps(result)
        assert json.loads(await registry.execute("trade_execute",{"preview_id":preview.id}))["state"] == "UNCERTAIN"
        effect_id=result["effect_id"]
        assert json.loads(await registry.execute("trade_reconcile",{"effect_id":effect_id}))["state"] == "UNCERTAIN"
        matches.append({"id":"order-1","symbol":"GOLDm","type":"POSITION_TYPE_BUY","volume":"0.1","clientId":preview.broker_request["clientId"]})
        assert json.loads(await registry.execute("trade_reconcile",{"effect_id":effect_id}))["state"] == "SUCCEEDED"
    assert len(calls) == 1


async def test_stale_responsibility_cannot_finalize_outbound_effect(tmp_path,client):
    preview,executor,registry=await setup(tmp_path,client)
    store=ResponsibilityStore(tmp_path)
    parent=store.create(objective="Trade",session_key="websocket:main",channel="websocket",chat_id="main")
    original=store.claim_foreground(parent.id)
    preview=executor.proposals.previews.save(preview.model_copy(update={"responsibility_id":parent.id}))
    transport=client.transport
    takeover=None
    def handler(request):
        nonlocal takeover
        if request.method == "POST":
            takeover=store.takeover(parent.id)
            return httpx.Response(200,json={"stringCode":"TRADE_RETCODE_DONE","orderId":"order-1"})
        return transport.handler(request)
    client.transport=httpx.MockTransport(handler)
    context=RequestContext(channel="websocket",chat_id="main",session_key="websocket:main")
    context.responsibility_scope.executions[parent.id]=ResponsibilityExecution(store,original,foreground=False)
    with request_context(context):
        approve(preview,executor.effects,parent.id)
        result=await registry.execute("trade_execute",{"preview_id":preview.id})
        assert result.is_error and "Stale" in result
        assert executor.effects.find_effect(preview.effect_key).state == "STARTED"
        assert (await registry.execute("trade_execute",{"preview_id":preview.id})).is_error
    assert takeover.generation == original.generation + 1
    assert executor.effects.recover() == 1
    assert executor.effects.find_effect(preview.effect_key).state == "UNCERTAIN"


async def test_process_death_after_outbound_request_cannot_replay(tmp_path,client):
    import subprocess
    import sys
    from pathlib import Path
    preview,executor,registry=await setup(tmp_path,client)
    approve(preview,executor.effects)
    marker=tmp_path / "sent-request"
    script='''
import os,sys,asyncio
from pathlib import Path
sys.path.insert(0,sys.argv[4])
import httpx
from conftest import client as fixture
from nanobot.security.actions import ActionStore,ActionPolicy
from nanobot.agent.tools.context import RequestContext,request_context
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.trade_execute import TradeExecuteTool
from nanobot.session.records import RecordStore
from nanobot.trading.instruments import InstrumentMappings,SymbolMapping
from nanobot.trading.proposals import TradeProposals,TradeProposal,TradePreview
from nanobot.trading.execution import TradeExecutor
root=Path(sys.argv[1])
client=fixture.__wrapped__(root)
transport=client.transport
journal=ActionStore(root / "state.db")
proposals=TradeProposals(client,InstrumentMappings(RecordStore("mappings",SymbolMapping,journal)),RecordStore("proposals",TradeProposal,journal),RecordStore("previews",TradePreview,journal))
executor=TradeExecutor(proposals,journal)
def handler(request):
 if request.method=="POST":
  with open(sys.argv[3],"w") as marker:
   marker.write("sent once");marker.flush();os.fsync(marker.fileno())
  os._exit(17)
 return transport.handler(request)
client.transport=httpx.MockTransport(handler)
registry=ToolRegistry(ActionPolicy(journal))
registry.register(TradeExecuteTool(executor))
async def main():
 with request_context(RequestContext(channel="websocket",chat_id="main",session_key="websocket:main")):
  await registry.execute("trade_execute",{"preview_id":sys.argv[2]})
asyncio.run(main())
'''
    result=subprocess.run([sys.executable,"-c",script,str(tmp_path),preview.id,str(marker),str(Path(__file__).parent)])
    assert result.returncode == 17 and marker.read_text() == "sent once"
    assert executor.effects.find_effect(preview.effect_key).state == "STARTED"
    assert executor.effects.recover() == 1
    with request_context(RequestContext(channel="websocket",chat_id="main",session_key="websocket:main")):
        assert json.loads(await registry.execute("trade_execute",{"preview_id":preview.id}))["state"] == "UNCERTAIN"
    assert marker.read_text() == "sent once"
