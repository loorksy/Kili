"""Export pinned KLineChart Pro through an ephemeral chart-only renderer."""
from __future__ import annotations

import base64
import os
import signal
import subprocess
import sys
from pathlib import Path

from nanobot.charts.scene import ChartScene


def render_scene(scene: ChartScene, width: int = 1000, height: int = 640) -> bytes:
    if not 320 <= width <= 1600 or not 240 <= height <= 1200:
        raise ValueError("Chart image dimensions outside bounded limits")
    payload = scene.model_dump_json().encode()
    if len(payload) > 8 * 1024 * 1024:
        raise ValueError("Chart render scene exceeds bounded size")
    worker = Path(__file__).with_name("render_worker.py")
    process = subprocess.Popen([sys.executable, "-I", str(worker), str(width), str(height)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        start_new_session=True, env={key: value for key, value in os.environ.items()
                                    if key in {"PATH", "SYSTEMROOT", "WINDIR"}})
    try:
        output, _ = process.communicate(payload, timeout=45)
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            os.killpg(process.pid, signal.SIGKILL)
        else:
            process.kill()
        process.communicate()
        raise ValueError("Chart export timed out; structured chart state remains available") from None
    if process.returncode != 0 or len(output) > 12 * 1024 * 1024:
        raise ValueError("KLineChart export unavailable; install documented chart renderer dependencies")
    try:
        data = base64.b64decode(output, validate=True)
    except ValueError:
        raise ValueError("Invalid chart export") from None
    if not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise ValueError("Invalid chart PNG export")
    return data
