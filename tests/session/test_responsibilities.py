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
    store.control_update(record)
    with pytest.raises(ValueError, match="changed"):
        store.control_update(stale)
    assert store.get(record.id).progress == "First step complete"


def test_checkpoint_and_wake_recovered_after_process_death(tmp_path):
    import subprocess
    import sys
    store = ResponsibilityStore(tmp_path)
    record = store.create(objective="Inspect report", session_key="websocket:one", channel="websocket", chat_id="one")
    script = '''
import os, sys
from pathlib import Path
from nanobot.config.loader import set_config_path
set_config_path(Path(sys.argv[3]))
from nanobot.session.responsibilities import ResponsibilityStore
s = ResponsibilityStore(Path(sys.argv[1]))
s.enqueue(sys.argv[2], "event:123", "report arrived")
claim = s.claim(sys.argv[2], "event:123")
s.checkpoint_tools(claim, {"pending_tool_calls": [{"id": "tool-1"}], "assistant_message": {"reasoning_content": "SECRET REASONING"}}, "websocket:one")
os._exit(17)
'''
    from nanobot.config.paths import get_config_path
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path), record.id, str(get_config_path())])
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
    claim = store.claim(record.id, "event:1")
    assert claim is not None
    assert ResponsibilityStore(tmp_path).claim(record.id, "event:1") is None
    store.finish(claim)
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
    store.control_update(record)
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
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("cli:one")
    sessions.save(session, fsync=True)
    agent = AgentLoop(bus=MessageBus(), provider=provider, workspace=tmp_path, model="test-model")
    import asyncio
    running = asyncio.create_task(agent.run())
    cron = CronService(tmp_path / "cron" / "jobs.json")
    cron.register_system_job(CronJob(id="responsibility_wakes", name="responsibility_wakes",
                                    schedule=CronSchedule(kind="every", every_ms=30_000),
                                    payload=CronPayload(kind="system_event")))
    async def callback(_job):
        await run_responsibility_wakes(restarted, submit_turn=agent.submit_cron_turn,
                                       is_channel_enabled=lambda _: True, session_exists=lambda _: True)
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
    store.control_update(first)
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
                                   is_channel_enabled=lambda _: True, session_exists=lambda _: True)
    await run_responsibility_wakes(store, submit_turn=submit, is_channel_enabled=lambda _: True, session_exists=lambda _: True)
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
    store.control_update(record)
    submit = AsyncMock()
    await run_responsibility_wakes(store, submit_turn=submit, is_channel_enabled=lambda _: False, session_exists=lambda _: True, now_ms=10)
    record = store.get(record.id)
    record.next_wake_ms, record.wake_generation = 100, 1
    store.control_update(record)
    await run_responsibility_wakes(store, submit_turn=submit, is_channel_enabled=lambda _: True, session_exists=lambda _: True, now_ms=10)
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


def test_takeover_fences_every_write_even_after_latest_record_reload(tmp_path):
    from nanobot.session.responsibilities import StaleExecutionError
    store = ResponsibilityStore(tmp_path)
    record = store.create(objective="Review", session_key=None, channel="", chat_id="")
    worker_a = store.claim_foreground(record.id)
    worker_b = ResponsibilityStore(tmp_path).takeover(record.id)
    assert worker_b.generation == worker_a.generation + 1
    for state in ["RUNNING", "WAITING", "SCHEDULED", "COMPLETED", "FAILED"]:
        latest = store.get(record.id)  # Re-reading does not acquire B's authority.
        latest.state = state
        latest.progress = "stale progress"
        latest.next_wake_ms = 123
        latest.wake_generation += 1
        latest.checkpoint.pending_work = ["stale retry"]
        with pytest.raises(StaleExecutionError):
            store.save(latest, claim=worker_a)
    with pytest.raises(StaleExecutionError):
        store.checkpoint_tools(worker_a, {"completed_tool_results": [{"tool_call_id": "stale"}]}, "cli:one")
    for uncertain in [False, True]:
        with pytest.raises(StaleExecutionError):
            store.finish(worker_a, uncertain=uncertain)
    latest = store.assert_owner(worker_b)
    latest.progress = "current worker"
    store.save(latest, claim=worker_b)
    assert store.get(record.id).progress == "current worker"
    assert store.get(record.id).checkpoint.result_refs == []
    store.finish(worker_b)


@pytest.mark.asyncio
async def test_deleted_delivery_stays_durable_until_explicit_bind(tmp_path):
    from unittest.mock import AsyncMock

    from nanobot.session.responsibility_turns import run_responsibility_wakes
    sessions = SessionManager(tmp_path)
    old = sessions.get_or_create("websocket:old")
    sessions.save(old)
    record = sessions.responsibilities.create(objective="Monitor", session_key=old.key,
                                             channel="websocket", chat_id="old")
    record.state, record.next_wake_ms = "SCHEDULED", 1
    sessions.responsibilities.control_update(record)
    sessions.delete_session(old.key)
    submit = AsyncMock(return_value=None)
    async def tick():
        await run_responsibility_wakes(sessions.responsibilities, submit_turn=submit,
                                      is_channel_enabled=lambda _: True,
                                      session_exists=lambda key: sessions.get_existing(key) is not None,
                                      now_ms=10)
    await tick()
    await tick()
    saved = sessions.responsibilities.get(record.id)
    assert saved.delivery_needed
    assert saved.state == "SCHEDULED"
    assert list(saved.wakes) == ["schedule:0:1"]
    assert saved.wakes["schedule:0:1"].state == "QUEUED"
    assert submit.await_count == 0
    assert sessions.get_existing(old.key) is None
    with request_context(RequestContext(channel="websocket", chat_id="new", session_key="websocket:new")):
        await UpdateGoalTool(sessions).execute(action="bind", responsibility_id=record.id)
    await tick()
    await tick()
    assert submit.await_count == 1
    assert submit.await_args.args[0].session_key == "websocket:new"
    assert submit.await_args.args[0].require_existing_session
    assert not sessions.responsibilities.get(record.id).delivery_needed


def test_draft_state_relocated_once_with_protected_backup(tmp_path):
    from nanobot.session.responsibilities import Responsibility
    legacy = tmp_path / "responsibilities"
    legacy.mkdir()
    record = Responsibility(version=1, id="resp_" + "a" * 32, objective="Legacy wait", state="WAITING_FOR_EVENT")
    source = legacy / (record.id + ".json")
    source.write_text(record.model_dump_json())
    store = ResponsibilityStore(tmp_path)
    store.migrate_workspace_records()
    assert not source.exists()
    assert (store.root / "legacy-backup" / source.name).exists()
    assert store.get(record.id).version == 3
    assert store.get(record.id).state == "WAITING_FOR_EVENT"
    store.migrate_workspace_records()
    assert len(store.list()) == 1


@pytest.mark.asyncio
async def test_empty_cron_tick_never_submits_a_turn(tmp_path):
    from unittest.mock import AsyncMock

    from nanobot.session.responsibility_turns import run_responsibility_wakes
    submit = AsyncMock()
    await run_responsibility_wakes(ResponsibilityStore(tmp_path), submit_turn=submit,
                                  is_channel_enabled=lambda _: True, session_exists=lambda _: True)
    submit.assert_not_awaited()


@pytest.mark.asyncio
async def test_stale_goal_tool_context_cannot_wait_complete_or_checkpoint(tmp_path):
    from nanobot.agent.tools.context import ResponsibilityExecution, ResponsibilityExecutionScope
    from nanobot.session.responsibilities import StaleExecutionError
    sessions = SessionManager(tmp_path)
    session = sessions.get_or_create("cli:one")
    sessions.save(session)
    store = sessions.responsibilities
    record = store.create(objective="Review", session_key=session.key, channel="cli", chat_id="one")
    old = store.claim_foreground(record.id)
    current = store.takeover(record.id)
    baseline = store.get(record.id).model_dump()
    request = RequestContext(channel="cli", chat_id="one", session_key=session.key,
                             responsibility_scope=ResponsibilityExecutionScope({record.id: ResponsibilityExecution(store, old, foreground=False)}))
    with request_context(request):
        tool = UpdateGoalTool(sessions)
        for action in ["complete", "cancel", "block", "pause", "wait", "checkpoint", "bind"]:
            with pytest.raises(StaleExecutionError):
                await tool.execute(action=action, responsibility_id=record.id, recap="stale",
                                   waiting_for="event", checkpoint_json='{"completed_steps":["stale"]}')
    assert store.get(record.id).model_dump() == baseline
    store.finish(current)


@pytest.mark.asyncio
async def test_late_callback_from_finished_turn_cannot_reacquire_ownership(tmp_path):
    from nanobot.agent.tools.context import (
        bind_request_context,
        current_request_context,
        reset_request_context,
    )
    from nanobot.session.responsibilities import StaleExecutionError
    sessions = SessionManager(tmp_path)
    request = RequestContext(channel="cli", chat_id="one", session_key="cli:one")
    with request_context(request), goal_mutation_permission(True):
        await CreateGoalTool(sessions).execute(objective="Review")
        captured = current_request_context()  # An async child inherits this scope.
        record, = sessions.responsibilities.list()
    assert captured is not None
    claim = sessions.responsibilities.claim_foreground(record.id)
    sessions.responsibilities.finish(claim)
    token = bind_request_context(captured)
    try:
        with pytest.raises(StaleExecutionError, match="scope has ended"):
            await UpdateGoalTool(sessions).execute(action="checkpoint", responsibility_id=record.id, recap="late")
    finally:
        reset_request_context(token)
    assert sessions.responsibilities.get(record.id).progress != "late"


@pytest.mark.asyncio
async def test_replacing_objective_invalidates_already_queued_schedule(tmp_path):
    from unittest.mock import AsyncMock

    from nanobot.session.responsibility_turns import run_responsibility_wakes
    sessions = SessionManager(tmp_path)
    context = RequestContext(channel="cli", chat_id="one", session_key="cli:one")
    with request_context(context), goal_mutation_permission(True):
        await CreateGoalTool(sessions).execute(objective="Old objective")
        await UpdateGoalTool(sessions).execute(action="wait", next_wake_ms=1)
    record, = sessions.responsibilities.list()
    old_wake = f"schedule:{record.wake_generation}:1"
    sessions.responsibilities.enqueue(record.id, old_wake, "Old schedule")
    with request_context(context), goal_mutation_permission(True):
        await UpdateGoalTool(sessions).execute(action="replace", objective="Replacement")
    submit = AsyncMock()
    await run_responsibility_wakes(sessions.responsibilities, submit_turn=submit,
                                  is_channel_enabled=lambda _: True, session_exists=lambda _: True)
    submit.assert_not_awaited()
    assert sessions.responsibilities.get(record.id).wakes[old_wake].state == "DISCARDED"
