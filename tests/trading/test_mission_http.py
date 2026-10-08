from types import SimpleNamespace

from test_delegation import delegated_setup
from websockets.datastructures import Headers
from websockets.http11 import Request

from nanobot.session.manager import SessionManager
from nanobot.webui.ws_http import GatewayHTTPHandler


class TokenGate:
    def check_api_token(self, request):
        return request.headers.get("Authorization") == "Bearer fixture"


async def test_http_snapshot_is_authenticated_and_plain_http_cannot_mutate(tmp_path,monkeypatch):
    service,mandate,_,_,_,_ = await delegated_setup(tmp_path)
    manager = SessionManager(tmp_path/"workspace")
    for principal in (mandate.principal,"websocket:other"):
        manager.save(manager.get_or_create(principal))
    handler = object.__new__(GatewayHTTPHandler)
    handler.tokens,handler.session_manager = TokenGate(),manager
    handler.settings = SimpleNamespace(config=SimpleNamespace(load=lambda: None))
    monkeypatch.setattr("nanobot.webui.mission_resources.service_for",lambda config: service)
    path = "/api/webui/trading-missions"
    query = "?session_key="+mandate.principal+"&mandate_id="+mandate.id
    assert (await handler._handle_cloud_resource(Request(path+query,Headers()),path)).status_code == 401
    headers = Headers({"Authorization":"Bearer fixture"})
    assert (await handler._handle_cloud_resource(Request(path+query,headers),path)).status_code == 200
    other = "?session_key=websocket:other&mandate_id="+mandate.id
    assert (await handler._handle_cloud_resource(Request(path+other,headers),path)).status_code == 403
    assert (await handler._handle_cloud_resource(Request(path+"/control"+query,headers),path+"/control")).status_code == 405
    assert service.mandates.get(mandate.id).status == "ACTIVE"
