"""Only bounded chart data crosses the native image-export boundary."""
import base64
from unittest.mock import Mock

import pytest

from nanobot.charts.render import render_scene
from nanobot.charts.scene import build_scene


def test_render_child_receives_no_credentials_and_failure_never_reflects_secret(workstation, monkeypatch):
    _, controller, actor, chart, _ = workstation
    monkeypatch.setattr("nanobot.charts.controller.MarketCache", lambda **_scope: controller.cache)
    scene = build_scene(chart, actor)
    monkeypatch.setenv("METAAPI_TOKEN", "private-sentinel-must-not-cross")
    monkeypatch.setenv("HOME", "/private-runtime-path")
    child = Mock(returncode=0)
    child.communicate.return_value = (base64.b64encode(b"\x89PNG\r\n\x1a\nfixture"), b"")
    launch = Mock(return_value=child)
    monkeypatch.setattr("nanobot.charts.render.subprocess.Popen", launch)
    assert render_scene(scene).startswith(b"\x89PNG")
    args, kwargs = launch.call_args
    assert "private-sentinel" not in repr(args) + repr(kwargs)
    assert "HOME" not in kwargs["env"] and "METAAPI_TOKEN" not in kwargs["env"]
    assert args[0][1] == "-I" and kwargs["start_new_session"] is True
    assert child.communicate.call_args.kwargs["timeout"] == 45
    child.returncode = 1
    child.communicate.return_value = (b"private-sentinel-must-not-cross", b"")
    with pytest.raises(ValueError, match="export unavailable") as error:
        render_scene(scene)
    assert "private-sentinel" not in str(error.value)
