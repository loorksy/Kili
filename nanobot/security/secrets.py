"""Execution-only secrets. References are safe; resolved values are not serializable."""
from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path
from typing import cast

from nanobot.security.runtime_storage import internal_state_root


class SecretValue:
    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

    def redact(self, payload: object) -> object:
        """Scrub credential reflection from provider JSON before parsing or persistence."""
        if isinstance(payload, str):
            return payload.replace(self._value, "[redacted]")
        if isinstance(payload, list):
            # Provider response.json() has JSON arrays/objects, never executable objects.
            return [self.redact(item) for item in cast(list[object], payload)]
        if isinstance(payload, dict):
            return {key.replace(self._value, "[redacted]"): self.redact(value)
                    for key, value in cast(dict[str, object], payload).items()}
        return payload

    def reveal(self) -> str:
        """Trusted HTTP adapter only; never put this value into a tool result."""
        return self._value


class SecretStore:
    def __init__(self, root: Path | None = None):
        self.root = root or internal_state_root(create=True) / "secrets"
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)

    @staticmethod
    def _name(reference: str) -> str:
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,80}", reference):
            raise ValueError("Invalid secret reference")
        return reference

    def put(self, reference: str, value: str) -> None:
        path = self.root / self._name(reference)
        if path.is_symlink():
            raise ValueError("Secret references cannot be symlinks")
        fd, temporary = tempfile.mkstemp(prefix=".secret-", dir=self.root)
        try:
            with os.fdopen(fd, "w") as stream:
                stream.write(value)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            if os.name != "nt":
                directory = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def resolve(self, reference: str) -> SecretValue:
        try:
            path = self.root / self._name(reference)
            if path.is_symlink():
                raise ValueError("Secret references cannot be symlinks")
            fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
            with os.fdopen(fd) as stream:
                value = stream.read()
        except OSError:
            raise ValueError("Connection credential is not configured") from None
        if not value:
            raise ValueError("Connection credential is empty")
        return SecretValue(value)
