
import pytest

from nanobot.security.workspace_collaboration import WorkspaceCollaboration


def test_publish_revision_and_private_boundary(tmp_path):
    workspace = WorkspaceCollaboration(tmp_path)
    worker = workspace.worker("worker-1")
    (worker / "report.txt").write_text("research")
    revision = workspace.publish("worker-1", "report.txt", "research/report.txt", expected_revision="absent")
    assert (tmp_path / "shared/research/report.txt").read_text() == "research"
    with pytest.raises(ValueError, match="changed"):
        workspace.publish("worker-1", "report.txt", "research/report.txt", expected_revision="absent")
    (worker / "report.txt").write_text("updated")
    assert workspace.publish("worker-1", "report.txt", "research/report.txt", expected_revision=revision) != revision
    with pytest.raises(PermissionError):
        workspace.publish("worker-1", "../worker-2/secret.txt", "secret", expected_revision="absent")
    with pytest.raises(PermissionError):
        workspace.publish("worker-1", "report.txt", "../main/report.txt", expected_revision="absent")


def test_symlink_escape(tmp_path):
    workspace = WorkspaceCollaboration(tmp_path / "work")
    worker = workspace.worker("worker-1")
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("private")
    (worker / "escape").symlink_to(outside, target_is_directory=True)
    with pytest.raises(PermissionError):
        workspace.publish("worker-1", "escape/secret", "report", expected_revision="absent")


async def test_existing_delegated_tool_publishes_into_parent_shared_scope(tmp_path):
    from nanobot.agent.tools.context import RequestContext, ResponsibilityExecution, request_context
    from nanobot.agent.tools.workspace_publish import WorkspacePublishTool
    from nanobot.session.responsibilities import ResponsibilityStore
    store = ResponsibilityStore(tmp_path)
    parent = store.create(objective="Research", session_key="websocket:main", channel="websocket", chat_id="main")
    parent_claim = store.claim_foreground(parent.id)
    child = store.create(objective="Worker", session_key=None, channel="", chat_id="")
    child.parent_responsibility_id, child.parent_execution_generation = parent.id, parent_claim.generation
    child.delegation_id = "worker-1"
    child = store.control_update(child)
    claim = store.claim_foreground(child.id)
    directory = WorkspaceCollaboration(tmp_path).worker("worker-1")
    (directory / "report.txt").write_text("Research evidence")
    request = RequestContext(channel="system", chat_id="main", session_key="subagent:worker-1")
    request.responsibility_scope.executions[child.id] = ResponsibilityExecution(store, claim, foreground=False)
    tool = WorkspacePublishTool(directory)
    with request_context(request):
        await tool.execute(source="report.txt", destination="research/report.txt", expected_revision="absent")
        assert (tmp_path / "shared/research/report.txt").read_text() == "Research evidence"
        store.takeover(parent.id)
        with pytest.raises(PermissionError):
            await tool.execute(source="report.txt", destination="research/new.txt", expected_revision="absent")
