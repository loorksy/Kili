"""Pinned library calculations, isolated from credentials and model-generated code."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from nanobot.charts.capabilities import BUILTIN_DEFAULTS
from nanobot.market.models import Candle
from nanobot.security.runtime_storage import protect_runtime_command


class NativeFigure(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    type: str
    title: str = ""


class NativeValues(BaseModel):
    model_config = ConfigDict(extra="forbid")
    values: list[dict[str, float | None]] = Field(max_length=5000)
    figures: list[NativeFigure]


def native_values(name: str, candles: list[Candle], parameters: list[float]) -> NativeValues:
    if name not in BUILTIN_DEFAULTS or len(candles) > 5000:
        raise ValueError("Unavailable built-in indicator or excessive candle history")
    import math
    defaults = BUILTIN_DEFAULTS[name]
    params = parameters or defaults
    if len(params) != len(defaults) or any(not math.isfinite(p) or not 0 < p <= 512 for p in params):
        raise ValueError("Invalid native indicator parameters")
    node = shutil.which("node")
    if node is None:
        raise ValueError("Chart built-in calculations require Node.js 24; structured OHLCV and custom IR remain available")
    assets = Path(__file__).parent / "assets"
    worker = assets / "calculator.cjs"
    payload = {"name": name, "parameters": params, "candles": [
        {"timestamp": int(c.time.timestamp() * 1000), "open": float(c.open), "high": float(c.high),
         "low": float(c.low), "close": float(c.close), "volume": c.volume or 0} for c in candles]}
    try:
        command = protect_runtime_command([node, "--permission", "--allow-fs-read=" + str(assets),
            "--max-old-space-size=64", str(worker)])
        if command[0].endswith("bwrap"):
            command.insert(1, "--unshare-net")
        completed = subprocess.run(command, input=json.dumps(payload), text=True,
            capture_output=True, timeout=3, env={}, cwd=assets, check=False)
    except (OSError, RuntimeError, subprocess.TimeoutExpired):
        raise ValueError("Chart indicator calculation unavailable") from None
    if completed.returncode or len(completed.stdout) > 2_000_000:
        raise ValueError("Chart indicator calculation failed")
    return NativeValues.model_validate_json(completed.stdout)
