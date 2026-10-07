import asyncio
from unittest.mock import AsyncMock, MagicMock

from nanobot.agent.memory import Consolidator
from nanobot.agent.subagent import SubagentManager, _SubagentOutcome
from nanobot.agent.tools.context import RequestContext, ResponsibilityExecution, request_context
from nanobot.bus.queue import MessageBus
from nanobot.providers.base import GenerationSettings, LLMProvider
from nanobot.session.manager import SessionManager
from nanobot.utils.llm_runtime import LLMRuntime


async def test_delegation_result_survives_deleted_parent_session(tmp_path):
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:parent")
    sessions.save(session)
    store = sessions.responsibilities
    parent = store.create(objective="Research", session_key=session.key, channel="websocket", chat_id="parent")
    claim = store.claim_foreground(parent.id)
    provider = MagicMock(spec=LLMProvider)
    provider.generation = GenerationSettings(temperature=.1, max_tokens=4096)
    runtime = LLMRuntime.capture(provider, "test", context_window_tokens=128000)
    manager = SubagentManager(workspace=tmp_path, bus=MessageBus(), session_manager=sessions, max_tool_result_chars=16000,
                              consolidator=MagicMock(spec=Consolidator))
    ready = asyncio.Event()
    async def research(record):
        await ready.wait()
        return _SubagentOutcome("done", "Research artifact is ready")
    manager._run_admitted_subagent = AsyncMock(side_effect=research)
    request = RequestContext(channel="websocket", chat_id="parent", session_key=session.key)
    request.responsibility_scope.executions[parent.id] = ResponsibilityExecution(store, claim)
    with request_context(request):
        await manager.spawn("Inspect gold", session_key=session.key, runtime=runtime)
        current = store.assert_owner(claim)
        current.state = "WAITING_FOR_SUBAGENT"
        store.save(current, claim=claim)
    sessions.delete_session(session.key)
    ready.set()
    await asyncio.gather(*list(manager._running_tasks.values()))
    child, = [r for r in store.list() if r.parent_responsibility_id == parent.id]
    assert child.state == "COMPLETED"
    assert child.result_summary == "Research artifact is ready"
    restarted = SessionManager(tmp_path)
    assert restarted.responsibilities.get(child.id).result_summary == child.result_summary
    parent = restarted.responsibilities.get(parent.id)
    assert parent.delivery_needed
    assert list(parent.wakes).count(f"subagent:{child.delegation_id}") == 1
    assert (tmp_path / "workers" / child.delegation_id).is_dir()
