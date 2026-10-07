"""Private delegated working directories and explicit, versioned publication."""
from __future__ import annotations

import hashlib
import os
import re
import uuid
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
        path = self.root / "workers" / worker_id
        path.mkdir(parents=True, exist_ok=True)
        if not path.resolve().is_relative_to(self.root / "workers"):
            raise PermissionError("Worker directory escaped its scope")
        return path

    @staticmethod
    def revision(path: Path) -> str:
        return hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else "absent"

    def publish(self, worker_id: str, source: str, destination: str, *, expected_revision: str) -> str:
        private = self.worker(worker_id)
        source_path = (private / source).resolve()
        shared = self.root / "shared"
        shared.mkdir(parents=True, exist_ok=True)
        target = (shared / destination).resolve()
        if not source_path.is_relative_to(private) or not target.is_relative_to(shared):
            raise PermissionError("Publication path escaped its scope")
        require_non_internal_path(source_path)
        require_non_internal_path(target)
        if source_path.stat().st_size > 2_000_000:
            raise ValueError("Publication exceeds the artifact size limit")
        namespace = hashlib.sha256(str(self.root).encode()).hexdigest()
        lock = FileLock(str(internal_state_root(create=True) / f"workspace-{namespace}.lock"))
        with lock:
            if self.revision(target) != expected_revision:
                raise ValueError("Shared artifact changed; reload its revision")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(f".{target.name}.{uuid.uuid4().hex}.tmp")
            try:
                with temporary.open("xb") as stream:
                    stream.write(source_path.read_bytes())
                    stream.flush()
                    os.fsync(stream.fileno())
                os.replace(temporary, target)
                if os.name != "nt":
                    descriptor = os.open(target.parent, os.O_RDONLY)
                    try:
                        os.fsync(descriptor)
                    finally:
                        os.close(descriptor)
            finally:
                temporary.unlink(missing_ok=True)
            return self.revision(target)
