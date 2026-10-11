"""HEAD and POST must reach the HTTP application instead of dropping the socket."""
import asyncio

from websockets.asyncio.server import serve
from websockets.datastructures import Headers
from websockets.http11 import Request
from websockets.server import ServerProtocol

from nanobot.webui.http_methods import head_response, install_plain_http_methods, request_method
from nanobot.webui.http_utils import http_error, http_response
from nanobot.webui.ws_http import GatewayHTTPHandler


def _parse(raw: bytes) -> Request:
    install_plain_http_methods()
    lines = raw.splitlines(keepends=True)

    def read_line(_limit: int):
        if False:
            yield b""
        if not lines:
            raise EOFError("closed")
        return lines.pop(0)

    parsed = Request.parse(read_line)
    try:
        while True:
            next(parsed)
    except StopIteration as stop:
        return stop.value


def test_head_and_post_are_parsed():
    head = _parse(b"HEAD /downloads/kili.apk HTTP/1.1\r\nHost: kili.lork.cloud\r\n\r\n")
    assert request_method(head) == "HEAD"
    assert head.path == "/downloads/kili.apk"
    posted = _parse(
        b"POST /api/webui/action-approvals/resolve HTTP/1.1\r\n"
        b"Host: kili.lork.cloud\r\nContent-Length: 2\r\n\r\n"
    )
    assert request_method(posted) == "POST"


def test_head_keeps_the_length_and_drops_the_body():
    response = http_response(b"hello", content_type="text/plain")
    headed = head_response(response)
    assert headed.body == b""
    assert headed.headers["Content-Length"] == "5"
    denied = head_response(http_error(405, "Approval requires authenticated WebSocket"))
    assert denied.status_code == 405
    assert denied.body == b""


def _protocol() -> ServerProtocol:
    install_plain_http_methods()
    return ServerProtocol()


def _post(body: bytes, *, length: int | None = None) -> bytes:
    declared = len(body) if length is None else length
    return (
        b"POST /api/webui/action-approvals/resolve HTTP/1.1\r\n"
        b"Host: kili.lork.cloud\r\n"
        b"Content-Type: application/json\r\n"
        b"Content-Length: " + str(declared).encode("ascii") + b"\r\n"
        b"\r\n"
        + body
    )


def test_post_body_is_drained_before_the_http_response():
    protocol = _protocol()
    protocol.receive_data(_post(b"{}"))
    events = protocol.events_received()
    assert protocol.handshake_exc is None
    assert protocol.eof_sent is False
    assert protocol.reader.buffer == bytearray()
    assert len(events) == 1
    assert request_method(events[0]) == "POST"
    protocol.send_response(http_error(405, "Approval requires authenticated WebSocket"))
    assert protocol.eof_sent is True


def test_post_body_can_arrive_after_the_headers():
    protocol = _protocol()
    protocol.receive_data(_post(b"", length=2))
    assert protocol.events_received() == []
    assert protocol.handshake_exc is None
    protocol.receive_data(b"{}")
    events = protocol.events_received()
    assert len(events) == 1
    assert protocol.reader.buffer == bytearray()
    protocol.send_response(http_error(405, "Approval requires authenticated WebSocket"))
    assert protocol.eof_sent is True


def test_get_without_a_body_still_answers():
    protocol = _protocol()
    protocol.receive_data(b"GET /downloads/kili.apk HTTP/1.1\r\nHost: kili.lork.cloud\r\n\r\n")
    events = protocol.events_received()
    assert protocol.handshake_exc is None
    assert len(events) == 1
    assert request_method(events[0]) == "GET"
    protocol.send_response(http_response(b"apk"))
    assert protocol.eof_sent is True


async def test_plain_post_resolve_is_405_before_authentication():
    handler = object.__new__(GatewayHTTPHandler)

    def deny(_request: Request) -> bool:
        raise AssertionError("token check should not run for a plain HTTP resolve")

    handler.tokens = type("Tokens", (), {"check_api_token": staticmethod(deny)})()
    path = "/api/webui/action-approvals/resolve"
    response = await handler._handle_cloud_resource(Request(path, Headers()), path)
    assert response.status_code == 405
    assert response.body == b"Approval requires authenticated WebSocket"

    def allow(_request: Request) -> bool:
        return True

    handler.tokens = type("Tokens", (), {"check_api_token": staticmethod(allow)})()
    mutation = Request(path, Headers())
    setattr(mutation, "_nanobot_webui_mutation_request", True)
    setattr(mutation, "_nanobot_webui_mutation_payload", {"session_key": "nope"})
    reached = await handler._handle_cloud_resource(mutation, path)
    assert reached.status_code == 400


async def _read_status(port: int, payload: bytes) -> bytes:
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    writer.write(payload)
    await writer.drain()
    raw = await asyncio.wait_for(reader.read(4096), timeout=2)
    writer.close()
    await writer.wait_closed()
    return raw


async def test_listener_answers_post_with_a_json_body():
    install_plain_http_methods()

    async def process_request(_connection: object, request: Request):
        assert request_method(request) == "POST"
        return http_error(405, "Approval requires authenticated WebSocket")

    async with serve(lambda _connection: asyncio.sleep(0), "127.0.0.1", 0, process_request=process_request) as server:
        sockets = server.sockets
        assert sockets
        port = sockets[0].getsockname()[1]
        with_body = await _read_status(port, _post(b"{}") + b"")
        empty = await _read_status(port, _post(b"", length=0))
    assert with_body.startswith(b"HTTP/1.1 405 ")
    assert b"Approval requires authenticated WebSocket" in with_body
    assert empty.startswith(b"HTTP/1.1 405 ")
