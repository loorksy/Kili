"""Trusted, account-scoped IPC to the dependency-isolated official MetaApi SDK.

The SDK requires Socket.IO 4; Nanobot's MoChat channel requires Socket.IO 5.
Only this provider connector runs in a separate Python environment. Policy,
effects, risk, credentials and all authoritative records remain in the gateway.
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import weakref
from pathlib import Path

from pydantic import BaseModel, ConfigDict, JsonValue, TypeAdapter

from nanobot.market.models import Connection
from nanobot.market.oanda import ProviderUnavailableError
from nanobot.security.actions import current_authorized_action
from nanobot.security.runtime_storage import internal_state_root
from nanobot.security.secrets import SecretStore

SDK_VERSION = "29.1.1"


class SDKReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    data: JsonValue = None
    error: str | None = None


class SDKRejectedError(RuntimeError):
    """An authenticated SDK operation received an explicit provider rejection."""


class SDKBridge:
    def __init__(self, connection: Connection, secrets: SecretStore):
        self.connection, self.secrets = connection, secrets
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()

    async def _start(self) -> asyncio.subprocess.Process:
        if self._process is not None and self._process.returncode is None:
            return self._process
        executable = internal_state_root() / "metaapi-sdk" / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        if not executable.is_file():
            raise ProviderUnavailableError("MetaApi SDK connector is not installed; run python -m nanobot.trading.sdk_install")
        worker = Path(__file__).with_name("sdk_worker.py")
        # Paths are supplied only by trusted application code, never by tools.
        self._process = await asyncio.create_subprocess_exec(
            str(executable), "-I", str(worker), str(Path(__file__).resolve().parents[2]),
            *[p for p in sys.path if p.endswith("site-packages")],
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL, limit=8 * 1024 * 1024,
            env={key: value for key, value in os.environ.items() if key.upper() in {
                "PATH", "SYSTEMROOT", "HTTPS_PROXY", "HTTP_PROXY", "ALL_PROXY", "NO_PROXY",
                "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE",
            }},
        )
        token = self.secrets.resolve(self.connection.secret_ref)
        assert self._process.stdin is not None
        self._process.stdin.write((json.dumps({"account_id": self.connection.account_id,
                                               "region": self.connection.region,
                                               "token": token.reveal()}) + "\n").encode())
        await self._process.stdin.drain()
        return self._process

    async def request(self, operation: str, parameters: dict[str, JsonValue] | None = None) -> JsonValue:
        if operation == "trade":
            grant = current_authorized_action()
            if (grant is None or grant.action.parameters.get("broker_request") != parameters
                    or grant.action.parameters.get("account_id") != self.connection.account_id):
                raise PermissionError("SDK trade requires exact gateway authorization")
        async with self._lock:
            try:
                process = await self._start()
                assert process.stdin is not None and process.stdout is not None
                process.stdin.write((json.dumps({"operation": operation, "parameters": parameters or {}}, allow_nan=False) + "\n").encode())
                await process.stdin.drain()
                raw = await asyncio.wait_for(process.stdout.readline(), timeout=75)
                reply = SDKReply.model_validate_json(raw)
                if not reply.ok:
                    if reply.error == "rejected":
                        raise SDKRejectedError("MetaApi rejected the requested operation")
                    raise ProviderUnavailableError("MetaApi SDK account operation unavailable; verify deployment and synchronization")
                return TypeAdapter[JsonValue](JsonValue).validate_python(self.secrets.resolve(self.connection.secret_ref).redact(reply.data))
            except (OSError, ValueError, asyncio.TimeoutError, asyncio.CancelledError) as exc:
                # Cancellation after sending is uncertain too. Never replay a
                # financial request or leave unread replies in the IPC stream.
                await self.close()
                if isinstance(exc, asyncio.CancelledError):
                    raise
                raise ProviderUnavailableError("MetaApi SDK connection interrupted; mutation outcome may be uncertain") from None

    async def close(self) -> None:
        process, self._process = self._process, None
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=5)
            except asyncio.TimeoutError:
                process.kill()
                await process.wait()


_bridges: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, dict[tuple[str, str, str, str], SDKBridge]] = weakref.WeakKeyDictionary()


def account_bridge(connection: Connection, secrets: SecretStore) -> SDKBridge:
    pool = _bridges.setdefault(asyncio.get_running_loop(), {})
    key = (connection.account_id, connection.region, connection.secret_ref, str(secrets.root))
    if key not in pool:
        pool[key] = SDKBridge(connection, secrets)
    return pool[key]


async def close_sdk_connections() -> None:
    pool = _bridges.pop(asyncio.get_running_loop(), {})
    await asyncio.gather(*(bridge.close() for bridge in pool.values()))
