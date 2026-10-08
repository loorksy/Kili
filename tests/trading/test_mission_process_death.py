import json
import subprocess
import sys
from pathlib import Path

from test_delegation import delegated_setup, preview_for

from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.config.loader import get_config_path
from nanobot.trading.mission_observation import refresh


async def test_autonomous_process_death_retains_reserved_risk_and_never_replays(tmp_path):
    service,mandate,executor,registry,context,state = await delegated_setup(tmp_path)
    # Preview and approval survive; only the child sends the simulated request.
    preview = await preview_for(executor,mandate)
    claim = next(iter(context.responsibility_scope.executions.values())).claim
    claim_file = tmp_path/"claim.json"
    claim_file.write_text(claim.model_dump_json())
    marker = tmp_path/"accepted.json"
    script = '''
import asyncio,json,os,sys
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import httpx
from mission_helpers import broker_fixture
from nanobot.security.actions import ActionPolicy,ActionStore
from nanobot.session.records import RecordStore
from nanobot.session.responsibilities import ResponsibilityStore,ExecutionClaim
from nanobot.agent.tools.context import RequestContext,ResponsibilityExecution,request_context
from nanobot.agent.tools.registry import ToolRegistry
from nanobot.agent.tools.trade_execute import TradeExecuteTool
from nanobot.trading.proposals import TradeProposals,TradeProposal,TradePreview
from nanobot.trading.instruments import InstrumentMappings,SymbolMapping
from nanobot.trading.execution import TradeExecutor
root=Path(sys.argv[2])
from nanobot.config.loader import set_config_path
set_config_path(Path(sys.argv[6]))
client,state=broker_fixture(root)
transport=client.transport
def handler(request):
 if request.url.path.endswith('/trade'):
  with open(sys.argv[5],'w') as file:
   file.write(request.content.decode());file.flush();os.fsync(file.fileno())
  os._exit(17)
 return transport.handler(request)
client.transport=httpx.MockTransport(handler)
journal=ActionStore(root/'missions.db')
# Mapping namespace is the fixture's exact namespace, not a new platform.
mappings=InstrumentMappings(RecordStore('mappings',SymbolMapping,ActionStore(root/'proposals'/'state.db')))
proposals=TradeProposals(client,mappings,RecordStore('trade_proposals',TradeProposal,journal),RecordStore('trade_previews',TradePreview,journal))
executor=TradeExecutor(proposals,journal,live_enabled=True)
registry=ToolRegistry(ActionPolicy(journal));registry.register(TradeExecuteTool(executor))
claim=ExecutionClaim.model_validate_json(Path(sys.argv[4]).read_text())
store=ResponsibilityStore(root/'workspace')
context=RequestContext(channel='websocket',chat_id='main',session_key='websocket:main')
context.responsibility_scope.executions[claim.responsibility_id]=ResponsibilityExecution(store=store,claim=claim)
async def main():
 with request_context(context):
  result=await registry.execute('trade_execute',{'preview_id':sys.argv[3]})
  print(result)
asyncio.run(main())
'''
    result = subprocess.run([sys.executable,"-c",script,str(Path(__file__).parent),str(tmp_path),
        preview.id,str(claim_file),str(marker),str(get_config_path())],capture_output=True,text=True,timeout=30)
    assert result.returncode == 17, result.stdout+result.stderr
    effect = executor.effects.find_effect(preview.effect_key)
    assert effect.state == "STARTED" and effect.mandate_id == mandate.id
    assert len(service.reservations.list()) == 1
    assert executor.effects.recover() == 1
    # Account fixture exposes the exact accepted client identity on restart.
    payload = json.loads(marker.read_text())
    state["positions"].append({"id":"accepted-1","symbol":"GOLDm","type":"POSITION_TYPE_BUY",
        "clientId":payload["clientId"],"volume":".1","openPrice":"2701","stopLoss":"2699","profit":"0"})
    current,_,_,_ = await refresh(service,service.mandates.get(mandate.id))
    assert current.status == "NEEDS_ATTENTION"
    with request_context(RequestContext(channel="websocket",chat_id="main",session_key=mandate.principal)):
        assert json.loads(await registry.execute("trade_execute",{"preview_id":preview.id}))["state"] == "UNCERTAIN"
        assert (await executor.reconcile(effect.id,mandate.principal))["state"] == "SUCCEEDED"
    assert not state["calls"]
    assert json.loads(marker.read_text()) == payload
