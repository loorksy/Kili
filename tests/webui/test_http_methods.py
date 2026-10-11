"""HEAD and POST must reach the HTTP application instead of dropping the socket."""
from websockets.http11 import Request

from nanobot.webui.http_methods import head_response, install_plain_http_methods, request_method
from nanobot.webui.http_utils import http_error, http_response


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
