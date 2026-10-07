"""Execution-only secrets. References are safe; resolved values are not serializable."""
from __future__ import annotations

import os
import re
from pathlib import Path

from nanobot.security.runtime_storage import internal_state_root


class SecretValue:
    __slots__ = ("_value",)

    def __init__(self, value: str):
        self._value = value

    def __repr__(self) -> str:
        return "SecretValue(<redacted>)"

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
        # Never return stored values through config/API readback.
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as stream:
            stream.write(value)
            stream.flush()
            os.fsync(stream.fileno())

    def resolve(self, reference: str) -> SecretValue:
        try:
            value = (self.root / self._name(reference)).read_text()
        except OSError:
            raise ValueError("Connection credential is not configured") from None
        if not value:
            raise ValueError("Connection credential is empty")
        return SecretValue(value)
