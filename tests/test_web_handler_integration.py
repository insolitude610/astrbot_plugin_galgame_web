import http.client
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from galgame_web.web_handler import GalgameWebHandler


class _UpstreamHandler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, fmt, *args):
        pass

    def _respond(self):
        type(self).requests.append(
            {
                "method": self.command,
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
            }
        )
        body = json.dumps({"ok": True}).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        self._respond()

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        self._respond()


def _start_server(handler):
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def _stop_server(server, thread):
    server.shutdown()
    server.server_close()
    thread.join(timeout=2)


def test_external_webui_keeps_static_and_plugin_apis_but_blocks_admin_routes(
    tmp_path,
):
    upstream, upstream_thread = _start_server(_UpstreamHandler)
    GalgameWebHandler.upstream = f"http://127.0.0.1:{upstream.server_port}"
    GalgameWebHandler.web_password = ""
    GalgameWebHandler.jwt_token = ""
    GalgameWebHandler.jwt_token_factory = lambda: "test-token"
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    (assets_dir / "sprite.png").write_bytes(b"image")
    (assets_dir / "script.html").write_text("<script>bad()</script>", "utf-8")
    GalgameWebHandler.assets_dir = assets_dir
    _UpstreamHandler.requests = []
    web, web_thread = _start_server(GalgameWebHandler)
    connection = http.client.HTTPConnection("127.0.0.1", web.server_port, timeout=5)

    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        body = response.read()
        assert response.status == 200
        assert b'<script src="./app.js"></script>' in body
        assert response.getheader("X-Frame-Options") == "SAMEORIGIN"
        assert response.getheader("Access-Control-Allow-Origin") is None

        connection.request("GET", "/assets/sprite.png")
        response = connection.getresponse()
        assert response.status == 200
        assert response.read() == b"image"

        connection.request("GET", "/assets/script.html")
        response = connection.getresponse()
        response.read()
        assert response.status == 404

        connection.request("GET", "/api/v1/plugins")
        response = connection.getresponse()
        response.read()
        assert response.status == 404
        assert _UpstreamHandler.requests == []

        connection.request("GET", "/", headers={"Host": "evil.example"})
        response = connection.getresponse()
        response.read()
        assert response.status == 421
        assert _UpstreamHandler.requests == []

        connection.request(
            "GET", "/api/plug/astrbot_plugin_galgame_web/config"
        )
        response = connection.getresponse()
        assert response.status == 200
        assert json.loads(response.read()) == {"ok": True}
        assert _UpstreamHandler.requests[-1] == {
            "method": "GET",
            "path": "/api/plug/astrbot_plugin_galgame_web/config",
            "authorization": "Bearer test-token",
        }

        connection.request(
            "POST",
            "/api/plug/astrbot_plugin_galgame_web/prefs",
            body=b"{}",
            headers={
                "Content-Type": "application/json",
                "Origin": "https://evil.example",
            },
        )
        response = connection.getresponse()
        response.read()
        assert response.status == 403
        assert len(_UpstreamHandler.requests) == 1
    finally:
        connection.close()
        _stop_server(web, web_thread)
        _stop_server(upstream, upstream_thread)
        GalgameWebHandler.jwt_token_factory = None


def test_external_webui_password_cookie_is_required_and_same_site():
    GalgameWebHandler.web_password = "correct horse"
    GalgameWebHandler.jwt_token_factory = lambda: "test-token"
    web, web_thread = _start_server(GalgameWebHandler)
    connection = http.client.HTTPConnection("127.0.0.1", web.server_port, timeout=5)
    origin = f"http://127.0.0.1:{web.server_port}"

    try:
        connection.request("GET", "/")
        response = connection.getresponse()
        response.read()
        assert response.status == 302
        assert response.getheader("Location") == "/login"

        payload = "password=correct+horse"
        connection.request(
            "POST",
            "/api/login",
            body=payload,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Content-Length": str(len(payload)),
                "Origin": origin,
            },
        )
        response = connection.getresponse()
        response.read()
        cookie = response.getheader("Set-Cookie")
        assert response.status == 302
        assert "HttpOnly" in cookie
        assert "SameSite=Strict" in cookie

        connection.request("GET", "/", headers={"Cookie": cookie.split(";", 1)[0]})
        response = connection.getresponse()
        response.read()
        assert response.status == 200
    finally:
        connection.close()
        _stop_server(web, web_thread)
        GalgameWebHandler.web_password = ""
        GalgameWebHandler.jwt_token_factory = None
