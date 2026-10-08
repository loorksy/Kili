"""Operator-only install of pinned SDK dependencies in protected runtime storage."""
from __future__ import annotations

import argparse
import subprocess
import sys
import venv
from pathlib import Path

from nanobot.security.runtime_storage import internal_state_root
from nanobot.trading.sdk_bridge import SDK_VERSION


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, help="Gateway configuration path")
    arguments = parser.parse_args()
    if arguments.config:
        from nanobot.config.loader import set_config_path
        set_config_path(arguments.config.expanduser().resolve())
    directory = internal_state_root(create=True) / "metaapi-sdk"
    venv.EnvBuilder(with_pip=True).create(directory)
    executable = directory / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
    subprocess.run([str(executable), "-m", "pip", "install", "--disable-pip-version-check",
                    f"metaapi-cloud-sdk=={SDK_VERSION}"], check=True)
    print("MetaApi SDK connector installed in protected runtime storage.")


if __name__ == "__main__":
    main()
