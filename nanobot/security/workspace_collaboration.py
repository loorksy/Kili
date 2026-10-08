"""Private delegated working directories and explicit, versioned publication."""
from __future__ import annotations

import hashlib
import os
import re
import stat
import uuid
from contextlib import ExitStack
from pathlib import Path

from filelock import FileLock

from nanobot.security.runtime_storage import internal_state_root, require_non_internal_path


class WorkspaceCollaboration:
    def __init__(self, root: Path):
        self.root = root.resolve()
        require_non_internal_path(self.root)

    def worker(self, worker_id: str) -> Path:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", worker_id):
            raise ValueError("Invalid worker identity")
        workers = self.root / "workers"
        if workers.is_symlink():
            raise PermissionError("Worker directory escaped its scope")
        path = workers / worker_id
        if path.is_symlink():
            raise PermissionError("Worker directory escaped its scope")
        path.mkdir(parents=True, exist_ok=True)
        if not path.resolve().is_relative_to(self.root / "workers"):
            raise PermissionError("Worker directory escaped its scope")
        return path

    @staticmethod
    def revision(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "absent"

    @staticmethod
    def _parts(value: str) -> tuple[str, ...]:
        path = Path(value)
        if path.is_absolute() or not path.parts or any(part in {".", ".."} for part in path.parts):
            raise PermissionError("Publication path escaped its scope")
        return path.parts

    @staticmethod
    def _directory(stack: ExitStack, parent: int, parts: tuple[str, ...], *, create: bool) -> int:
        current = parent
        for part in parts:
            if create:
                try:
                    os.mkdir(part, dir_fd=current)
                except FileExistsError:
                    pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=current)
            stack.callback(os.close, child)
            current = child
        return current

    def publish(self, worker_id: str, source: str, destination: str, *, expected_revision: str) -> str:
        if os.name == "nt":
            raise PermissionError("Protected publication requires directory-handle support")
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", worker_id):
            raise ValueError("Invalid worker identity")
        source_parts, target_parts = self._parts(source), self._parts(destination)
        namespace = hashlib.sha256(str(self.root).encode()).hexdigest()
        lock = FileLock(str(internal_state_root(create=True) / f"workspace-{namespace}.lock"))
        try:
            with lock, ExitStack() as stack:
                anchor = os.open(self.root.anchor, os.O_RDONLY | os.O_DIRECTORY)
                stack.callback(os.close, anchor)
                root = self._directory(stack, anchor, self.root.parts[1:], create=False)
                private = self._directory(stack, root, ("workers", worker_id), create=False)
                source_dir = self._directory(stack, private, source_parts[:-1], create=False)
                source_fd = os.open(source_parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=source_dir)
                stack.callback(os.close, source_fd)
                if not stat.S_ISREG(os.fstat(source_fd).st_mode):
                    raise PermissionError("Publication requires a regular artifact file")
                with os.fdopen(os.dup(source_fd), "rb") as stream:
                    content = stream.read(2_000_001)
                if len(content) > 2_000_000:
                    raise ValueError("Publication exceeds the artifact size limit")
                shared = self._directory(stack, root, ("shared",), create=True)
                target_dir = self._directory(stack, shared, target_parts[:-1], create=True)
                try:
                    fd = os.open(target_parts[-1], os.O_RDONLY | os.O_NOFOLLOW, dir_fd=target_dir)
                    with os.fdopen(fd, "rb") as stream:
                        current_revision = hashlib.sha256(stream.read(2_000_001)).hexdigest()
                except FileNotFoundError:
                    current_revision = "absent"
                if current_revision != expected_revision:
                    raise ValueError("Shared artifact changed; reload its revision")
                temporary = ".publish-" + uuid.uuid4().hex
                try:
                    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=target_dir)
                    with os.fdopen(fd, "wb") as stream:
                        stream.write(content)
                        stream.flush()
                        os.fsync(stream.fileno())
                    os.replace(temporary, target_parts[-1], src_dir_fd=target_dir, dst_dir_fd=target_dir)
                    os.fsync(target_dir)
                finally:
                    try:
                        os.unlink(temporary, dir_fd=target_dir)
                    except FileNotFoundError:
                        pass
                return hashlib.sha256(content).hexdigest()
        except OSError:
            raise PermissionError("Publication path is inaccessible or unsafe") from None
