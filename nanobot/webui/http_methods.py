"""Accept ordinary HTTP methods on the WebSocket listener.

The bundled handshake parser only allows GET. HEAD probes and plain POST
then die before the application can answer, which a proxy reports as 502.

A declared body has to be consumed before the WebSocket frame parser runs.
Otherwise those bytes are read as a frame, the connection fails, and the
later HTTP response calls ``send_eof`` a second time.
"""
from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

from websockets.datastructures import Headers
from websockets.exceptions import InvalidMessage, SecurityError
from websockets.http11 import MAX_BODY_SIZE, Request, parse_headers, parse_line
from websockets.protocol import CONNECTING, Protocol
from websockets.server import ServerProtocol

_installed = False


def _text(value: bytes | bytearray) -> str:
    return value.decode(errors="backslashreplace")


def parse_plain_http(
    cls: type[Request],
    read_line: Callable[[int], Generator[None, None, bytes | bytearray]],
) -> Generator[None, None, Request]:
    """Parse GET, HEAD, and other HTTP/1.1 requests, including a declared body."""
    try:
        request_line = yield from parse_line(read_line)
    except EOFError as exc:
        raise EOFError("connection closed while reading HTTP request line") from exc
    try:
        method, raw_path, protocol = request_line.split(b" ", 2)
    except ValueError:
        raise ValueError(f"invalid HTTP request line: {_text(request_line)}") from None
    if protocol != b"HTTP/1.1":
        raise ValueError(f"unsupported protocol; expected HTTP/1.1: {_text(request_line)}")
    if not method.isascii() or not method.isalpha() or not 1 <= len(method) <= 16:
        raise ValueError(f"unsupported HTTP method: {_text(method)}")
    path = raw_path.decode("ascii", "surrogateescape")
    headers = yield from parse_headers(read_line)
    request = cls(path, headers)
    request.method = method.decode("ascii")  # type: ignore[attr-defined]
    return request


def _drain_declared_body(reader: Any, headers: Headers) -> Generator[None, None, None]:
    """Read and discard a Content-Length body so it is not parsed as a frame."""
    if "Transfer-Encoding" in headers:
        raise NotImplementedError("transfer codings aren't supported")
    if "Content-Length" not in headers:
        return
    raw = headers["Content-Length"]
    try:
        length = int(raw)
    except ValueError:
        raise ValueError(f"invalid Content-Length: {raw}") from None
    if length < 0 or len(raw) > 18:
        raise ValueError(f"invalid Content-Length: {raw}")
    if length > MAX_BODY_SIZE:
        raise SecurityError(f"body too large: {length} bytes")
    if length:
        yield from reader.read_exact(length)


def _parse_request_and_drain_body(self: ServerProtocol) -> Generator[None]:
    """Parse one HTTP request, drop its body, then continue with frames."""
    if self.state is CONNECTING:
        try:
            request = yield from Request.parse(self.reader.read_line)
            yield from _drain_declared_body(self.reader, request.headers)
        except Exception as exc:
            self.handshake_exc = InvalidMessage("did not receive a valid HTTP request")
            self.handshake_exc.__cause__ = exc
            self.send_eof()
            self.parser = self.discard()
            next(self.parser)  # start coroutine
            yield
            return

        if self.debug:
            self.logger.debug("< %s %s HTTP/1.1", request_method(request), request.path)
            for key, value in request.headers.raw_items():
                self.logger.debug("< %s: %s", key, value)

        self.events.append(request)

    yield from Protocol.parse(self)


def install_plain_http_methods() -> None:
    """Replace the GET-only handshake parser for this process."""
    global _installed
    if _installed:
        return
    Request.parse = classmethod(parse_plain_http)  # type: ignore[method-assign]
    ServerProtocol.parse = _parse_request_and_drain_body  # type: ignore[method-assign]
    _installed = True


def request_method(request: Request) -> str:
    method = getattr(request, "method", None)
    if isinstance(method, str) and method:
        return method.upper()
    return "GET"


def head_response(response: object) -> object:
    """Keep the GET headers, including Content-Length, and send no body."""
    body = getattr(response, "body", None)
    headers = getattr(response, "headers", None)
    if not isinstance(body, (bytes, bytearray)) or not isinstance(headers, Headers):
        return response
    if "Content-Length" not in headers:
        headers["Content-Length"] = str(len(body))
    response.body = b""  # type: ignore[attr-defined]
    return response
