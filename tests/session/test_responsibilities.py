"""Contracts for goal identity outside the conversation lifecycle."""

import json

import pytest

from nanobot.agent.goal_permission import goal_mutation_permission
from nanobot.agent.tools.context import RequestContext, request_context
from nanobot.agent.tools.long_task import CreateGoalTool, UpdateGoalTool
from nanobot.session.manager import SessionManager
from nanobot.session.responsibilities import ResponsibilityStore


@pytest.mark.asyncio
async def test_goal_survives_reset_and_can_bind_another_conversation(tmp_path):
    sessions = SessionManager(tmp_path)
    with request_context(RequestContext(channel="websocket", chat_id="one", session_key="websocket:one")), goal_mutation_permission(True):
        await CreateGoalTool(sessions).execute(objective="Watch gold this week")
        record, = sessions.responsibilities.list()
        await UpdateGoalTool(sessions).execute(action="wait", waiting_for="price changed")
    session = sessions.get_or_create("websocket:one")
    session.metadata.clear()
    session.messages.clear()
    sessions.save(session)
    restarted = SessionManager(tmp_path)
    assert restarted.responsibilities.get(record.id).state == "WAITING_FOR_EVENT"
    with request_context(RequestContext(channel="websocket", chat_id="two", session_key="websocket:two")):
        tool = UpdateGoalTool(restarted)
        assert json.loads(await tool.execute(action="list"))[0]["id"] == record.id
        await tool.execute(action="bind", responsibility_id=record.id)
    bound = ResponsibilityStore(tmp_path).get(record.id)
    assert bound.session_key == "websocket:two"
    assert bound.state == "WAITING_FOR_EVENT"


def test_stale_update_cannot_overwrite_progress(tmp_path):
    store = ResponsibilityStore(tmp_path)
    record = store.create(objective="Review", session_key=None, channel="", chat_id="")
    stale = store.get(record.id)
    record.progress = "First step complete"
    store.save(record)
    with pytest.raises(ValueError, match="changed"):
        store.save(stale)
    assert store.get(record.id).progress == "First step complete"


def test_checkpoint_and_wake_recovered_after_process_death(tmp_path):
    import subprocess
    import sys
    store = ResponsibilityStore(tmp_path)
    record = store.create(objective="Inspect report", session_key="websocket:one", channel="websocket", chat_id="one")
    script = '''
import os, sys
from pathlib import Path
from nanobot.session.responsibilities import ResponsibilityStore
s = ResponsibilityStore(Path(sys.argv[1]))
s.enqueue(sys.argv[2], "event:123", "report arrived")
s.claim(sys.argv[2], "event:123")
s.checkpoint_tools(sys.argv[2], {"pending_tool_calls": [{"id": "tool-1"}], "assistant_message": {"reasoning_content": "SECRET REASONING"}}, "websocket:one")
os._exit(17)
'''
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), record.id])
    assert result.returncode == 17
    restarted = ResponsibilityStore(tmp_path)
    assert restarted.recover() == [record.id]
    recovered = restarted.get(record.id)
    assert recovered.state == "PAUSED"
    assert recovered.checkpoint.pending_tools == ["tool-1"]
    assert recovered.wakes["event:123"].state == "UNCERTAIN"
    assert not restarted.enqueue(record.id, "event:123", "duplicate")
    assert restarted.claim(record.id, "event:123") is None
    assert "SECRET REASONING" not in next(store.root.glob("resp_*.json")).read_text()


def test_completed_wake_is_never_claimed_twice(tmp_path):
    store = ResponsibilityStore(tmp_path)
    record = store.create(objective="Review", session_key=None, channel="", chat_id="")
    assert store.enqueue(record.id, "event:1", "review")
    assert store.claim(record.id, "event:1") is not None
    assert ResponsibilityStore(tmp_path).claim(record.id, "event:1") is None
    store.finish(record.id, "event:1")
    restarted = ResponsibilityStore(tmp_path)
    assert restarted.recover() == []
    assert restarted.claim(record.id, "event:1") is None
    assert restarted.get(record.id).state == "WAITING"


@pytest.mark.asyncio
async def test_overdue_wake_uses_existing_cron_and_real_agent_loop(tmp_path):
    from unittest.mock import AsyncMock, MagicMock

    from nanobot.agent.loop import AgentLoop
    from nanobot.bus.queue import MessageBus
    from nanobot.cron.service import CronService
    from nanobot.cron.types import CronJob, CronPayload, CronSchedule
    from nanobot.providers.base import GenerationSettings, LLMResponse, ToolCallRequest
    from nanobot.session.responsibility_turns import run_responsibility_wakes

    store = ResponsibilityStore(tmp_path)
    record = store.create(objective="Inspect gold and sleep", session_key="cli:one", channel="cli", chat_id="one")
    record.state, record.next_wake_ms = "SCHEDULED", 1
    store.save(record)
    # Fresh store represents a gateway restart after the due time was missed.
    restarted = ResponsibilityStore(tmp_path)
    provider = MagicMock()
    provider.generation = GenerationSettings()
    provider.get_default_model.return_value = "test-model"
    provider.chat_stream_with_retry = AsyncMock(side_effect=[
        LLMResponse(content="wait", tool_calls=[ToolCallRequest(
            id="wait-1", name="update_goal", arguments={"action": "wait", "waiting_for": "user", "recap": "Checked the report"})]),
        LLMResponse(content="Nothing needs attention."),
    ])
    agent = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")
    import asyncio
    running = asyncio.create_task(agent.run())
    cron = CronService(tmp_path / "cron" / "jobs.json")
    cron.register_system_job(CronJob(id="responsibility_wakes", name="responsibility_wakes",
                                    schedule=CronSchedule(kind="every", every_ms=30_000),
                                    payload=CronPayload(kind="system_event")))
    async def callback(_job):
        await run_responsibility_wakes(restarted, submit_turn=agent.submit_cron_turn,
                                       is_channel_enabled=lambda _: True)
    cron.on_job = callback
    try:
        await cron.start()
        await asyncio.wait_for(cron.run_job("responsibility_wakes"), 10)
        await asyncio.wait_for(cron.run_job("responsibility_wakes"), 10)
        assert provider.chat_stream_with_retry.await_count == 2
        saved = restarted.get(record.id)
        assert saved.state == "WAITING_FOR_USER"
        assert saved.progress == "Checked the report"
        assert saved.wakes["schedule:0:1"].state == "COMPLETED"
        assert "session:cli:one:tool:wait-1" in saved.checkpoint.result_refs
    finally:
        cron.stop()
        agent.stop()
        running.cancel()
        await asyncio.gather(running, return_exceptions=True)
        await agent.aclose()


@pytest.mark.asyncio
async def test_replayed_trigger_wakes_correct_rebound_responsibility_once(tmp_path):
    from unittest.mock import AsyncMock

    from nanobot.session.responsibility_turns import (
        RESPONSIBILITY_TRIGGER_META,
        run_responsibility_wakes,
    )
    from nanobot.triggers.local_runner import _deliver_delivery
    from nanobot.triggers.local_store import LocalTriggerStore

    store = ResponsibilityStore(tmp_path)
    first = store.create(objective="First", session_key="websocket:one", channel="websocket", chat_id="one")
    second = store.create(objective="Second", session_key="websocket:two", channel="websocket", chat_id="two")
    first.state = "WAITING_FOR_EVENT"
    first.session_key, first.chat_id = "websocket:rebound", "rebound"
    store.save(first)
    triggers = LocalTriggerStore(tmp_path)
    trigger = triggers.create(name="gold", channel="websocket", chat_id="one", session_key="websocket:one",
                              origin_metadata={RESPONSIBILITY_TRIGGER_META: first.id})
    delivery = triggers.enqueue(trigger.id, "Changed")
    submit = AsyncMock(return_value=None)
    for _ in range(2):
        await _deliver_delivery(triggers, delivery, submit_turn=submit,
                                is_channel_enabled=lambda _: True, responsibilities=store)
    assert submit.await_count == 0  # Acknowledgment follows durable enqueue, not inference.
    await run_responsibility_wakes(ResponsibilityStore(tmp_path), submit_turn=submit,
                                   is_channel_enabled=lambda _: True)
    await run_responsibility_wakes(store, submit_turn=submit, is_channel_enabled=lambda _: True)
    assert submit.await_count == 1
    message = submit.await_args.args[0]
    assert message.session_key == "websocket:rebound"
    assert message.chat_id == "rebound"
    assert store.get(second.id).wakes == {}


def test_legacy_goal_migration_is_idempotent_and_does_not_schedule(tmp_path):
    from nanobot.session.responsibility_turns import migrate_session_goals
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("websocket:one")
    session.metadata["thread_goal"] = {"status": "active", "objective": "Existing goal"}
    sessions.save(session)
    migrate_session_goals(sessions)
    record, = sessions.responsibilities.list()
    assert record.next_wake_ms is None
    # Simulate the projection write being lost; the legacy import retains its ID.
    session.metadata.pop("goal_state")
    sessions.save(session)
    migrate_session_goals(SessionManager(tmp_path))
    assert len(sessions.responsibilities.list()) == 1
    sessions.delete_session("websocket:one")
    assert sessions.responsibilities.get(record.id).objective == "Existing goal"


@pytest.mark.asyncio
async def test_replaced_schedule_discards_queued_old_wake(tmp_path):
    from unittest.mock import AsyncMock

    from nanobot.session.responsibility_turns import run_responsibility_wakes
    store = ResponsibilityStore(tmp_path)
    record = store.create(objective="Review", session_key="websocket:x", channel="websocket", chat_id="x")
    record.state, record.next_wake_ms = "SCHEDULED", 1
    store.save(record)
    submit = AsyncMock()
    await run_responsibility_wakes(store, submit_turn=submit, is_channel_enabled=lambda _: False, now_ms=10)
    record = store.get(record.id)
    record.next_wake_ms, record.wake_generation = 100, 1
    store.save(record)
    await run_responsibility_wakes(store, submit_turn=submit, is_channel_enabled=lambda _: True, now_ms=10)
    assert submit.await_count == 0
    assert store.get(record.id).wakes["schedule:0:1"].state == "DISCARDED"


@pytest.mark.asyncio
async def test_deleting_event_source_pauses_but_keeps_responsibility(tmp_path):
    from nanobot.triggers.local_store import LocalTriggerStore
    sessions = SessionManager(tmp_path)
    with request_context(RequestContext(channel="websocket", chat_id="one", session_key="websocket:one")), goal_mutation_permission(True):
        await CreateGoalTool(sessions).execute(objective="Watch event")
        await UpdateGoalTool(sessions).execute(action="wait", waiting_for="Report arrived")
    triggers = LocalTriggerStore(tmp_path)
    trigger, = triggers.list_triggers()
    record, = sessions.responsibilities.list()
    assert triggers.delete(trigger.id)
    assert sessions.responsibilities.get(record.id).state == "PAUSED"


@pytest.mark.asyncio
async def test_transient_chat_cannot_create_durable_goal(tmp_path):
    sessions = SessionManager(tmp_path)
    with request_context(RequestContext(channel="websocket", chat_id="one", session_key="websocket:one", persist_session=False)), goal_mutation_permission(True):
        result = await CreateGoalTool(sessions).execute(objective="Private temporary work")
    assert "persistent conversation" in result
    assert sessions.responsibilities.list() == []
