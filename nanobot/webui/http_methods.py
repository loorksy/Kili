"""Accept ordinary HTTP methods on the WebSocket listener.

The bundled handshake parser only allows GET. HEAD probes and plain POST
then die before the application can answer, which a proxy reports as 502.
"""
from __future__ import annotations

from collections.abc import Callable, Generator

from websockets.datastructures import Headers
from websockets.http11 import Request, parse_headers, parse_line

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


def install_plain_http_methods() -> None:
    """Replace the GET-only handshake parser for this process."""
    global _installed
    if _installed:
        return
    Request.parse = classmethod(parse_plain_http)  # type: ignore[method-assign]
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
