
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
