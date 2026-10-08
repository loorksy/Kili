"""Internal runtime state is outside the model's filesystem capability.

Path checks protect file tools. Shell children need OS isolation as well: a
workspace check or chmod cannot protect state from a child with the same UID.
"""

from __future__ import annotations

import sys
from pathlib import Path

from nanobot.security.workspace_policy import WorkspaceBoundaryError

_RUNTIME_CODE_ROOT = Path(__file__).resolve().parents[1]


def get_config_path() -> Path:
    # The config package resolves tool DTOs. Importing it while provider/tool
    # modules are still loading can leave ToolsConfig forward references open.
    from nanobot.config.paths import get_config_path as active_config_path
    return active_config_path()


def internal_state_root(*, create: bool = False) -> Path:
    root = get_config_path().parent.resolve() / "internal"
    if create:
        root.mkdir(parents=True, exist_ok=True, mode=0o700)
        root.chmod(0o700)
    return root.resolve()


def require_non_internal_path(path: Path) -> None:
    root = internal_state_root()
    code = _RUNTIME_CODE_ROOT
    if path.is_relative_to(root) or path.is_relative_to(code) or path == get_config_path().resolve():
        raise WorkspaceBoundaryError("Protected runtime state is not an agent workspace resource")


def protect_runtime_command(command: list[str]) -> list[str]:
    """Mandatory outer boundary, also for unrestricted and persistent shells.

    Preserve the configured filesystem access outside internal state. Every
    ancestor is a mount point so a child cannot rename an ancestor to unmask
    state. A private PID namespace hides gateway memory/file descriptors.
    Configured sandbox bind overrides run inside this boundary, not after it.
    Unsupported platforms fail closed rather than launch an unprotected child.
    """
    root = internal_state_root(create=True)
    if sys.platform == "linux":
        bwrap = next((p for p in ("/usr/bin/bwrap", "/bin/bwrap") if type(root)(p).is_file()), None)
        if bwrap is None:
            raise RuntimeError("Protected runtime storage requires bubblewrap for shell execution")
        args = [bwrap, "--die-with-parent", "--new-session", "--unshare-user",
                "--unshare-pid", "--cap-drop", "ALL", "--bind", "/", "/",
                "--proc", "/proc", "--dev", "/dev"]
        code = _RUNTIME_CODE_ROOT
        config_file = get_config_path().resolve()
        config_file.parent.mkdir(parents=True, exist_ok=True)
        # A missing configuration must not become a model-created authorization
        # file. Trusted configuration loading already accepts an empty file.
        if not config_file.exists():
            config_file.touch(mode=0o600)
        ancestors = sorted(set(root.parents) | set(code.parents) | set(config_file.parents), key=lambda p: len(p.parts))
        for ancestor in ancestors:
            if str(ancestor) != root.anchor:
                args.extend(["--bind", str(ancestor), str(ancestor)])
        args.extend(["--ro-bind", str(code), str(code)])
        args.extend(["--ro-bind", "/dev/null", str(config_file)])
        args.extend(["--tmpfs", str(root), "--remount-ro", str(root), "--", *command])
        return args
    if sys.platform == "darwin":
        from nanobot.agent.tools.sandbox import quote_sandbox_path
        rules = ["(version 1)", "(allow default)",
                 f"(deny file-read* file-write* (subpath {quote_sandbox_path(str(root))}))",
                 f"(deny file-write* (subpath {quote_sandbox_path(str(_RUNTIME_CODE_ROOT))}))",
                 f"(deny file-read* file-write* (literal {quote_sandbox_path(str(get_config_path().resolve()))}))",
                 "(deny process-info*)", "(deny signal (target others))"]
        rules.append("(deny file-write-unlink " + " ".join(
            f"(literal {quote_sandbox_path(str(p))})" for p in (root, *root.parents)) + ")")
        return ["/usr/bin/sandbox-exec", "-p", "\n".join(rules), *command]
    raise RuntimeError("Protected runtime storage has no shell isolation backend on this platform")
