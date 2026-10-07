"""Exercise real file and shell capabilities, not just storage permissions."""

import shlex
import sys

import pytest

from nanobot.agent.tools.filesystem import ReadFileTool, WriteFileTool
from nanobot.agent.tools.shell import ExecTool
from nanobot.session.responsibilities import ResponsibilityStore


@pytest.mark.asyncio
async def test_internal_state_is_denied_even_with_unrestricted_file_tools(tmp_path):
    store = ResponsibilityStore(tmp_path)
    record = store.create(objective="Protected", session_key=None, channel="", chat_id="")
    path = store.root / (record.id + ".json")
    link = tmp_path / "state-link"
    link.symlink_to(path)
    for candidate in [path, link]:
        assert "Protected runtime" in await WriteFileTool(workspace=tmp_path).execute(str(candidate), "forged")
        assert "Protected runtime" in await ReadFileTool(workspace=tmp_path).execute(str(candidate))
    assert store.get(record.id).objective == "Protected"


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "linux", reason="Real Linux bubblewrap boundary")
async def test_shell_and_descendants_cannot_read_or_mutate_runtime_state(tmp_path):
    store = ResponsibilityStore(tmp_path)
    record = store.create(objective="Protected", session_key=None, channel="", chat_id="")
    path = store.root / (record.id + ".json")
    # Run Python inside the ordinary shell tool; aliases/descendants are hidden too.
    script = f'''from pathlib import Path
import json, subprocess, sys
p=Path({str(path)!r})
try:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("forged")
except OSError:
    print("WRITE DENIED")
else:
    raise AssertionError("authoritative write escaped sandbox")
assert not p.exists()
subprocess.run([sys.executable, "-c", "from pathlib import Path; assert not Path(" + repr(str(p)) + ").exists()"], check=True)
Path("normal.txt").write_text("allowed")
'''
    result = await ExecTool(working_dir=str(tmp_path)).execute(command=shlex.join([sys.executable, "-c", script]))
    assert "WRITE DENIED" in result
    assert (tmp_path / "normal.txt").read_text() == "allowed"
    assert store.get(record.id).objective == "Protected"


def test_runtime_state_does_not_live_in_workspace(tmp_path):
    store = ResponsibilityStore(tmp_path)
    assert not store.root.is_relative_to(tmp_path)


@pytest.mark.asyncio
@pytest.mark.skipif(sys.platform != "linux", reason="Real protected MCP stdio startup")
async def test_stdio_mcp_cannot_mutate_gateway_state(tmp_path):
    from nanobot.agent.tools.mcp import connect_mcp_servers
    from nanobot.agent.tools.registry import ToolRegistry
    from nanobot.config.schema import MCPServerConfig
    store = ResponsibilityStore(tmp_path)
    record = store.create(objective="MCP protected", session_key=None, channel="", chat_id="")
    path = store.root / (record.id + ".json")
    server = tmp_path / "server.py"
    server.write_text('''from pathlib import Path
from mcp.server.fastmcp import FastMCP
mcp = FastMCP("fixture")
@mcp.tool()
def try_write(path: str) -> str:
    try:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("forged")
    except OSError:
        return "WRITE DENIED"
    return "WRITE ESCAPED"
mcp.run(transport="stdio")
''')
    registry = ToolRegistry()
    connections = await connect_mcp_servers({"fixture": MCPServerConfig(command=sys.executable, args=[str(server)])}, registry)
    try:
        assert "fixture" in connections
        name, = registry.tool_names
        result = await registry.execute(name, {"path": str(path)})
        assert "WRITE DENIED" in result
        assert store.get(record.id).objective == "MCP protected"
    finally:
        for connection in connections.values():
            await connection.aclose()


@pytest.mark.skipif(sys.platform != "linux", reason="Real protected installed CLI process")
def test_installed_cli_app_cannot_mutate_gateway_state(tmp_path, monkeypatch):
    from nanobot.apps.cli import CliAppManager
    store = ResponsibilityStore(tmp_path)
    record = store.create(objective="CLI protected", session_key=None, channel="", chat_id="")
    path = store.root / (record.id + ".json")
    manager = CliAppManager(workspace=tmp_path, data_dir=tmp_path / "cli-apps")
    monkeypatch.setattr(manager, "get_app", lambda name: {"name": name, "entry_point": sys.executable})
    monkeypatch.setattr(manager, "_load_installed", lambda: {"fixture": {"entry_point": sys.executable}})
    script = f'''from pathlib import Path
p=Path({str(path)!r})
try:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("forged")
except OSError:
    print("WRITE DENIED")
'''
    result = manager.run("fixture", ["-c", script])
    assert "WRITE DENIED" in result
    assert store.get(record.id).objective == "CLI protected"
