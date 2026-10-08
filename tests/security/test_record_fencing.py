import pytest

from nanobot.agent.tools.context import RequestContext, ResponsibilityExecution, request_context
from nanobot.security.actions import ActionStore
from nanobot.security.secrets import SecretStore
from nanobot.session.records import RecordStore, RuntimeRecord
from nanobot.session.responsibilities import ResponsibilityStore, StaleExecutionError


def test_stale_scope_cannot_write_chart_journal_or_other_runtime_records(tmp_path):
    store = ResponsibilityStore(tmp_path)
    record = store.create(objective="Research", session_key="websocket:main", channel="websocket", chat_id="main")
    original = store.claim_foreground(record.id)
    records = RecordStore("test", RuntimeRecord, ActionStore(tmp_path / "state.db"))
    saved = records.create(RuntimeRecord(id="result"))
    request = RequestContext(channel="websocket", chat_id="main", session_key="websocket:main")
    request.responsibility_scope.executions[record.id] = ResponsibilityExecution(store, original, foreground=False)
    store.takeover(record.id)
    with request_context(request):
        for operation in (lambda: records.save(saved), lambda: records.create(RuntimeRecord(id="new"))):
            with pytest.raises(StaleExecutionError):
                operation()
    assert records.get("result").revision == 0


def test_secret_store_rejects_symlink_and_atomically_replaces(tmp_path):
    secrets = SecretStore(tmp_path / "secrets")
    secrets.put("connection", "FIRST_SENTINEL")
    secrets.put("connection", "SECOND_SENTINEL")
    assert secrets.resolve("connection").reveal() == "SECOND_SENTINEL"
    external = tmp_path / "external"
    external.write_text("untouched")
    (secrets.root / "escape").symlink_to(external)
    with pytest.raises(ValueError):
        secrets.put("escape", "overwrite")
    with pytest.raises(ValueError):
        secrets.resolve("escape")
    assert external.read_text() == "untouched"
