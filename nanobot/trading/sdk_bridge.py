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
from collections.abc import AsyncIterator, Callable
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter

from nanobot.market.models import Connection
from nanobot.market.provider import ProviderUnavailableError
from nanobot.security.actions import current_authorized_action
from nanobot.security.runtime_storage import internal_state_root
from nanobot.security.secrets import SecretStore, SecretValue
from nanobot.trading.retcodes import ProviderDiagnostic

SDK_VERSION = "29.1.1"


class SDKReply(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ok: bool
    data: JsonValue = None
    error: str | None = None
    provider_error: ProviderDiagnostic | None = None


class SDKFrame(SDKReply):
    kind: Literal["reply", "prices", "stream_status"] = "reply"
    prices: list[dict[str, JsonValue]] = Field(default_factory=list, max_length=100)


class SDKRejectedError(RuntimeError):
    """An authenticated SDK operation received an explicit provider rejection."""

    def __init__(self, message: str, provider_error: ProviderDiagnostic | None = None):
        super().__init__(message)
        self.provider_error = provider_error


class SDKUnavailableError(ProviderUnavailableError):
    def __init__(self, message: str, provider_error: ProviderDiagnostic | None = None):
        super().__init__(message)
        self.provider_error = provider_error


class SDKBridge:
    def __init__(self, connection: Connection, secrets: SecretStore):
        self.connection, self.secrets = connection, secrets
        self._process: asyncio.subprocess.Process | None = None
        self._lock = asyncio.Lock()
        self._reader: asyncio.Task[None] | None = None
        self._pending: asyncio.Future[SDKReply] | None = None
        self._consumers: dict[int, tuple[set[str], asyncio.Queue[dict[str, JsonValue] | None]]] = {}
        self._next_consumer = 0
        self._credential: SecretValue | None = None

    def _redact(self, payload: object) -> object:
        # A running connector may still use the bootstrap credential after a
        # user rotates its reference. Scrub both values until it is restarted.
        if self._credential is not None:
            payload = self._credential.redact(payload)
        return self.secrets.resolve(self.connection.secret_ref).redact(payload)

    @staticmethod
    def _offer(queue: asyncio.Queue[dict[str, JsonValue] | None], value: dict[str, JsonValue] | None) -> None:
        if queue.full():
            previous = queue.get_nowait()
            if value is not None and previous is not None:
                value = {**previous, **value}
        queue.put_nowait(value)

    async def _read(self, process: asyncio.subprocess.Process) -> None:
        assert process.stdout is not None
        try:
            while raw := await process.stdout.readline():
                frame = SDKFrame.model_validate_json(raw)
                if frame.kind == "stream_status":
                    for _, queue in self._consumers.values():
                        self._offer(queue, None)
                elif frame.kind == "prices":
                    cleaned = TypeAdapter[list[dict[str, JsonValue]]](list[dict[str, JsonValue]]).validate_python(
                        self._redact(frame.prices))
                    for symbols, queue in self._consumers.values():
                        updates: dict[str, JsonValue] = {str(price["symbol"]): price for price in cleaned
                                                       if price.get("symbol") in symbols}
                        if updates:
                            self._offer(queue, updates)
                elif self._pending is not None and not self._pending.done():
                    self._pending.set_result(SDKReply(ok=frame.ok, data=frame.data, error=frame.error, provider_error=frame.provider_error))
        except (ValueError, OSError):
            pass
        finally:
            if self._pending is not None and not self._pending.done():
                self._pending.set_exception(ProviderUnavailableError("MetaApi SDK connector disconnected; mutation outcome may be uncertain"))
            for _, queue in self._consumers.values():
                self._offer(queue, None)

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
        self._credential = token
        assert self._process.stdin is not None
        self._process.stdin.write((json.dumps({"account_id": self.connection.account_id,
                                               "region": self.connection.region,
                                               "token": token.reveal()}) + "\n").encode())
        await self._process.stdin.drain()
        return self._process

    async def request(self, operation: str, parameters: dict[str, JsonValue] | None = None, *,
                      before_write: Callable[[], None] | None = None) -> JsonValue:
        if operation == "trade":
            grant = current_authorized_action()
            if (grant is None or grant.action.parameters.get("broker_request") != parameters
                    or grant.action.parameters.get("account_id") != self.connection.account_id):
                raise PermissionError("SDK trade requires exact gateway authorization")
        async with self._lock:
            self._pending = asyncio.get_running_loop().create_future()
            try:
                process = await self._start()
                assert process.stdin is not None and process.stdout is not None
                if self._reader is None or self._reader.done():
                    self._reader = asyncio.create_task(self._read(process))
                if before_write:
                    before_write()
                process.stdin.write((json.dumps({"operation": operation, "parameters": parameters or {}}, allow_nan=False) + "\n").encode())
                await process.stdin.drain()
                reply = await asyncio.wait_for(self._pending, timeout=75)
                if not reply.ok:
                    diagnostic = (ProviderDiagnostic.model_validate(self._redact(reply.provider_error.model_dump(mode="json")))
                                  if reply.provider_error else None)
                    if reply.error == "rejected":
                        raise SDKRejectedError("MetaApi rejected the requested operation", diagnostic)
                    raise SDKUnavailableError("MetaApi SDK account operation unavailable; verify deployment and synchronization", diagnostic)
                return TypeAdapter[JsonValue](JsonValue).validate_python(self._redact(reply.data))
            except (OSError, ValueError, asyncio.TimeoutError, asyncio.CancelledError, ProviderUnavailableError) as exc:
                # Cancellation after sending is uncertain too. Never replay a
                # financial request or leave unread replies in the IPC stream.
                await self.close()
                if isinstance(exc, asyncio.CancelledError):
                    raise
                if isinstance(exc, ProviderUnavailableError):
                    raise
                raise ProviderUnavailableError("MetaApi SDK connection interrupted; mutation outcome may be uncertain") from None
            finally:
                if not self._pending.done():
                    self._pending.cancel()
                self._pending = None

    async def stream_quotes(self, symbols: set[str]) -> AsyncIterator[dict[str, JsonValue]]:
        if not symbols or len(symbols) > 100:
            raise ValueError("Broker stream requires 1–100 exact symbols")
        self._next_consumer += 1
        identity = self._next_consumer
        queue: asyncio.Queue[dict[str, JsonValue] | None] = asyncio.Queue(maxsize=1)
        self._consumers[identity] = (set(symbols), queue)
        try:
            combined = set[str]().union(*(item[0] for item in self._consumers.values()))
            if len(combined) > 100:
                raise ValueError("Broker subscription union exceeds 100 symbols")
            parameters: dict[str, JsonValue] = {"symbols": [symbol for symbol in sorted(combined)]}
            await self.request("subscribe", parameters)
            while True:
                update = await queue.get()
                if update is None:
                    raise ProviderUnavailableError("Broker quote stream disconnected")
                for value in update.values():
                    if isinstance(value, dict):
                        yield value
        finally:
            self._consumers.pop(identity, None)
            if self._process is not None and self._process.returncode is None and self._reader is not None and not self._reader.done():
                combined = set[str]().union(*(item[0] for item in self._consumers.values()))
                parameters = {"symbols": [symbol for symbol in sorted(combined)]}
                await self.request("subscribe", parameters)

    async def close(self) -> None:
        reader, self._reader = self._reader, None
        if reader is not None:
            reader.cancel()
            await asyncio.gather(reader, return_exceptions=True)
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
