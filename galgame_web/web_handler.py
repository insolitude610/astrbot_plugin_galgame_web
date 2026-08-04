import hmac
import pathlib
import secrets
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs

from astrbot.api import logger

PLUGIN_NAME = "astrbot_plugin_galgame_web"
PLUGIN_API_PREFIX = f"/api/plug/{PLUGIN_NAME}/"
MAX_LOGIN_BODY_BYTES = 4096
MAX_PROXY_REQUEST_BYTES = 45 * 1024 * 1024
MAX_PROXY_RESPONSE_BYTES = 64 * 1024 * 1024
LOGIN_WINDOW_SECONDS = 60
MAX_LOGIN_FAILURES = 8
MAX_SERVER_THREADS = 32
MAX_PROXY_CONCURRENCY = 8
ASSET_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".vrm"}
AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus"}

ALLOWED_API_ROUTES = {
    "GET": frozenset(
        {
            "assets/file",
            "assets/list",
            "audio/data",
            "bgm/data",
            "bgm/file",
            "bgm/list",
            "config",
            "favorites/list",
            "history",
            "prefs",
            "session/list",
        }
    ),
    "POST": frozenset(
        {
            "assets/batch",
            "assets/batch-delete",
            "assets/copy",
            "assets/delete",
            "assets/upload",
            "assets/upload-key",
            "bgm/delete",
            "bgm/upload",
            "favorites/add",
            "favorites/delete",
            "prefs",
            "rapid_action",
            "send",
            "session/delete",
            "session/init",
        }
    ),
}


def resolve_web_bind_host(configured_host: str, password: str) -> str:
    host = str(configured_host or "0.0.0.0").strip() or "0.0.0.0"
    if not password and host.lower() not in ("127.0.0.1", "localhost"):
        return "127.0.0.1"
    return host


LOGIN_HTML = """\
<!doctype html>
<html lang="zh-CN">
<head><meta charset="utf-8"/><meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Galgame - 身份验证</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
body{display:flex;align-items:center;justify-content:center;min-height:100vh;
background:radial-gradient(ellipse at center,#1a1330 0%,#0a0618 100%);font-family:system-ui,-apple-system,sans-serif}
.login-box{width:min(360px,90vw);background:rgba(20,14,40,.85);border:1px solid rgba(180,140,240,.12);
border-radius:14px;padding:32px 28px;box-shadow:0 8px 48px rgba(0,0,0,.4)}
.login-box h1{font-size:18px;font-weight:700;color:rgba(230,200,255,.88);text-align:center;margin-bottom:6px}
.login-box p{font-size:13px;color:rgba(180,150,210,.45);text-align:center;margin-bottom:24px}
.login-box label{display:block;font-size:13px;color:rgba(200,170,230,.55);margin-bottom:6px}
.login-box input{width:100%;padding:10px 14px;font-size:15px;color:#e0d8f0;
background:rgba(255,255,255,.06);border:1px solid rgba(180,140,240,.15);border-radius:8px;outline:none;transition:border .2s}
.login-box input:focus{border-color:rgba(200,160,255,.35)}
.login-box button{width:100%;margin-top:18px;padding:12px;font-size:15px;font-weight:600;color:#f0e8ff;
background:rgba(140,100,220,.35);border:1px solid rgba(180,140,240,.25);border-radius:8px;cursor:pointer;transition:background .2s}
.login-box button:hover{background:rgba(160,120,240,.45)}
.login-box .err{color:rgba(255,130,130,.7);font-size:13px;text-align:center;margin-top:12px;display:none}
</style>
</head>
<body>
<div class="login-box">
<h1>AI Galgame 虚拟伙伴</h1>
<p>请输入访问密码</p>
<form method="post" action="/api/login">
<label for="pwd">密码</label>
<input id="pwd" type="password" name="password" autofocus placeholder="输入密码..."/>
<button type="submit">进入</button>
<div class="err" id="err">密码错误</div>
</form>
</div>
<script>
var p=new URLSearchParams(location.search);
if(p.get("err")) document.getElementById("err").style.display="block";
</script>
</body>
</html>"""


def _safe_path(name: str, base_dir: pathlib.Path) -> pathlib.Path | None:
    if (
        not isinstance(name, str)
        or not name
        or "\x00" in name
        or "/" in name
        or "\\" in name
    ):
        return None
    candidate = pathlib.Path(name)
    if candidate.is_absolute() or candidate.name != name:
        return None
    base = base_dir.resolve()
    resolved = (base / candidate).resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        return None
    return resolved


def _secret_bytes(secret: str | bytes) -> bytes:
    return secret if isinstance(secret, bytes) else secret.encode()


def _make_auth_token(secret: str | bytes, ts: int) -> str:
    h = hmac.new(_secret_bytes(secret), str(ts).encode(), "sha256").hexdigest()
    return f"{ts}:{h}"


def _check_auth_token(secret: str | bytes, token: str, max_age: int = 86400) -> bool:
    try:
        parts = token.split(":", 1)
        ts = int(parts[0])
        age = int(time.time()) - ts
        if age < 0 or age > max_age:
            return False
        expected = hmac.new(
            _secret_bytes(secret), str(ts).encode(), "sha256"
        ).hexdigest()
        return hmac.compare_digest(parts[1], expected)
    except (ValueError, IndexError):
        return False


class BoundedThreadingHTTPServer(ThreadingHTTPServer):
    daemon_threads = True
    request_queue_size = 64

    def __init__(self, server_address, handler_class, max_workers=MAX_SERVER_THREADS):
        self._worker_slots = threading.BoundedSemaphore(max_workers)
        super().__init__(server_address, handler_class)

    def process_request(self, request, client_address):
        if not self._worker_slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request, client_address)
        except Exception:
            self._worker_slots.release()
            raise

    def process_request_thread(self, request, client_address):
        try:
            super().process_request_thread(request, client_address)
        finally:
            self._worker_slots.release()


def _canonical_plugin_api_path(raw_path: str, method: str) -> tuple[str, str] | None:
    """Return a normalized, allowlisted Dashboard path and query string."""
    parsed = urllib.parse.urlsplit(raw_path)
    if parsed.scheme or parsed.netloc or parsed.fragment:
        return None
    try:
        decoded = urllib.parse.unquote(parsed.path, errors="strict")
    except (UnicodeDecodeError, ValueError):
        return None
    if (
        "\\" in decoded
        or "\x00" in decoded
        or not decoded.startswith(PLUGIN_API_PREFIX)
    ):
        return None
    if any(segment in ("", ".", "..") for segment in decoded.split("/")[1:]):
        return None
    endpoint = decoded[len(PLUGIN_API_PREFIX) :]
    if endpoint not in ALLOWED_API_ROUTES.get(method, frozenset()):
        return None
    encoded_path = urllib.parse.quote(decoded, safe="/:@!$&'()*+,;=-._~")
    return encoded_path, parsed.query


class GalgameWebHandler(BaseHTTPRequestHandler):
    upstream = "http://127.0.0.1:6185"
    static_dir: pathlib.Path = pathlib.Path(__file__).parent / "galgame"
    assets_dir: pathlib.Path = (
        pathlib.Path("data/plugin_data") / "astrbot_plugin_galgame_web" / "assets"
    )
    audio_dir: pathlib.Path = (
        pathlib.Path("data/plugin_data") / "astrbot_plugin_galgame_web" / "audio"
    )
    bgm_dir: pathlib.Path = (
        pathlib.Path("data/plugin_data") / "astrbot_plugin_galgame_web" / "bgm"
    )
    jwt_token: str = ""
    jwt_token_factory = None
    web_password: str = ""
    auth_secret: bytes = secrets.token_bytes(32)
    _login_failures: dict[str, list[float]] = {}
    _login_lock = threading.Lock()
    _proxy_slots = threading.BoundedSemaphore(MAX_PROXY_CONCURRENCY)

    MIME = {
        ".html": "text/html; charset=utf-8",
        ".css": "text/css",
        ".js": "text/javascript",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".webp": "image/webp",
        ".gif": "image/gif",
        ".svg": "image/svg+xml",
        ".ico": "image/x-icon",
        ".json": "application/json",
        ".mp3": "audio/mpeg",
        ".wav": "audio/wav",
        ".ogg": "audio/ogg",
        ".flac": "audio/flac",
        ".m4a": "audio/mp4",
        ".aac": "audio/aac",
        ".opus": "audio/ogg",
    }

    def log_message(self, fmt, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "SAMEORIGIN")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "frame-ancestors 'self'")
        super().end_headers()

    def _send_json_error(self, status: int, message: str):
        data = (f'{{"error":"{message}"}}').encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self, max_bytes: int) -> bytes | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except (TypeError, ValueError):
            self._send_json_error(400, "invalid content length")
            return None
        if length < 0:
            self._send_json_error(400, "invalid content length")
            return None
        if length > max_bytes:
            self._send_json_error(413, "request body too large")
            return None
        try:
            body = self.rfile.read(length) if length else b""
        except (OSError, TimeoutError):
            self._send_json_error(408, "request body timeout")
            return None
        if len(body) != length:
            self._send_json_error(400, "incomplete request body")
            return None
        return body

    def _origin_ok(self) -> bool:
        origin = self.headers.get("Origin", "").strip()
        if not origin:
            return True
        try:
            parsed = urllib.parse.urlsplit(origin)
        except ValueError:
            return False
        host = self.headers.get("Host", "").strip().lower()
        return (
            parsed.scheme in ("http", "https")
            and bool(host)
            and parsed.netloc.lower() == host
            and not parsed.path.strip("/")
            and not parsed.query
            and not parsed.fragment
        )

    def _host_ok(self) -> bool:
        if GalgameWebHandler.web_password:
            return True
        raw_host = self.headers.get("Host", "").strip()
        if not raw_host:
            return False
        try:
            hostname = urllib.parse.urlsplit(f"//{raw_host}").hostname
        except ValueError:
            return False
        return (hostname or "").lower() in ("127.0.0.1", "localhost", "::1")

    def _reserve_login_attempt(self, client_ip: str) -> bool:
        now = time.monotonic()
        with GalgameWebHandler._login_lock:
            recent = [
                ts
                for ts in GalgameWebHandler._login_failures.get(client_ip, [])
                if now - ts < LOGIN_WINDOW_SECONDS
            ]
            if len(recent) >= MAX_LOGIN_FAILURES:
                GalgameWebHandler._login_failures[client_ip] = recent
                return False
            recent.append(now)
            GalgameWebHandler._login_failures[client_ip] = recent
            return True

    def _clear_login_failures(self, client_ip: str):
        with GalgameWebHandler._login_lock:
            GalgameWebHandler._login_failures.pop(client_ip, None)

    def _auth_ok(self) -> bool:
        pwd = GalgameWebHandler.web_password
        if not pwd:
            return True
        cookie = self.headers.get("Cookie", "")
        token = ""
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith("galgame_auth="):
                token = part.split("=", 1)[1].strip()
                break
        return _check_auth_token(GalgameWebHandler.auth_secret, token)

    def _require_auth(self) -> bool:
        if self._auth_ok():
            return False
        path = self.path.split("?")[0]
        if path == "/login":
            return False
        if path == "/api/login":
            return False
        if path.startswith("/api/"):
            self._send_json_error(401, "authentication required")
            return True
        self.send_response(302)
        self.send_header("Location", "/login")
        self.end_headers()
        return True

    def do_GET(self):
        if not self._host_ok():
            self._send_json_error(421, "invalid host")
            return
        path = self.path.split("?")[0]

        if path == "/login":
            return self._serve_login()
        if path.startswith("/api/"):
            if path == "/api/login":
                self.send_error(405)
                return
            if self._require_auth():
                return
            return self._proxy("GET")
        if self._require_auth():
            return
        return self._serve_static()

    def do_POST(self):
        if not self._host_ok():
            self._send_json_error(421, "invalid host")
            return
        path = self.path.split("?")[0]

        if not self._origin_ok():
            self._send_json_error(403, "cross-origin request rejected")
            return

        if path == "/api/login":
            return self._handle_login()
        if path.startswith("/api/"):
            if self._require_auth():
                return
            return self._proxy("POST")
        self.send_error(404)

    def _handle_login(self):
        client_ip = self.client_address[0] if self.client_address else "unknown"
        if not self._reserve_login_attempt(client_ip):
            self._send_json_error(429, "too many login attempts")
            return
        raw_body = self._read_body(MAX_LOGIN_BODY_BYTES)
        if raw_body is None:
            return
        body = raw_body.decode("utf-8", errors="replace")
        params = parse_qs(body)
        submitted = params.get("password", [""])[0]
        pwd = GalgameWebHandler.web_password
        if pwd and hmac.compare_digest(submitted, pwd):
            self._clear_login_failures(client_ip)
            ts = int(time.time())
            token = _make_auth_token(GalgameWebHandler.auth_secret, ts)
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header(
                "Set-Cookie",
                f"galgame_auth={token}; Path=/; HttpOnly; SameSite=Strict; Max-Age=86400",
            )
            self.end_headers()
        else:
            self.send_response(302)
            self.send_header("Location", "/login?err=1")
            self.end_headers()

    def _serve_login(self):
        html = LOGIN_HTML.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html)))
        self.end_headers()
        self.wfile.write(html)

    def _serve_static(self):
        path = urllib.parse.unquote(self.path.split("?")[0])
        if path == "/":
            path = "/index.html"
        filename = path.lstrip("/")
        safe = None
        if filename.startswith("assets/"):
            safe_assets = _safe_path(filename[len("assets/") :], self.assets_dir)
            if (
                safe_assets
                and safe_assets.suffix.lower() in ASSET_EXTS
                and safe_assets.is_file()
            ):
                safe = safe_assets
        elif filename.startswith("audio/"):
            safe_audio = _safe_path(filename[len("audio/") :], self.audio_dir)
            if (
                safe_audio
                and safe_audio.suffix.lower() in AUDIO_EXTS
                and safe_audio.is_file()
            ):
                safe = safe_audio
        elif filename.startswith("bgm/"):
            safe_bgm = _safe_path(filename[len("bgm/") :], self.bgm_dir)
            if (
                safe_bgm
                and safe_bgm.suffix.lower() in AUDIO_EXTS
                and safe_bgm.is_file()
            ):
                safe = safe_bgm
        else:
            safe = _safe_path(filename, self.static_dir)
        if not safe or not safe.is_file():
            self.send_error(404)
            return

        ext = safe.suffix.lower()
        mime = self.MIME.get(ext, "application/octet-stream")
        try:
            data = safe.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self.send_error(500)

    def _proxy(self, method):
        if not GalgameWebHandler._proxy_slots.acquire(blocking=False):
            self._send_json_error(503, "server busy")
            return
        try:
            self._proxy_request(method)
        finally:
            GalgameWebHandler._proxy_slots.release()

    def _proxy_request(self, method):
        target = _canonical_plugin_api_path(self.path, method)
        if not target:
            self._send_json_error(404, "API route not found")
            return
        path, query = target
        url = self.upstream + path + (f"?{query}" if query else "")
        body = None
        if method == "POST":
            body = self._read_body(MAX_PROXY_REQUEST_BYTES)
            if body is None:
                return

        length = len(body) if body else 0

        logger.debug(
            f"[proxy] {method} {self.path} cl={length} "
            f"body_bytes={len(body) if body else 0} "
            f"jwt={'yes' if GalgameWebHandler.jwt_token else 'no'}"
        )

        req = urllib.request.Request(url, data=body, method=method)
        for key in ("Accept", "Accept-Language", "User-Agent"):
            val = self.headers.get(key)
            if val:
                req.add_header(key, val)
        if body and method == "POST":
            req.add_header(
                "Content-Type", self.headers.get("Content-Type", "application/json")
            )
        token = GalgameWebHandler.jwt_token
        if GalgameWebHandler.jwt_token_factory:
            try:
                token = GalgameWebHandler.jwt_token_factory()
            except Exception as e:
                logger.warning(f"[proxy] failed to generate auth token: {e}")
                self._send_json_error(502, "proxy authentication unavailable")
                return
        if token:
            req.add_header("Authorization", f"Bearer {token}")

        try:
            with urllib.request.urlopen(req, timeout=300) as resp:
                status = resp.status
                body_bytes = resp.read(MAX_PROXY_RESPONSE_BYTES + 1)
                response_headers = list(resp.headers.items())
            if len(body_bytes) > MAX_PROXY_RESPONSE_BYTES:
                self._send_json_error(502, "upstream response too large")
                return
            logger.debug(f"[proxy] upstream responded {status}")

            self.send_response(status)
            for key, val in response_headers:
                low = key.lower()
                if low in (
                    "transfer-encoding",
                    "connection",
                    "keep-alive",
                    "content-length",
                    "access-control-allow-origin",
                    "access-control-allow-credentials",
                ):
                    continue
                self.send_header(key, val)
            self.send_header("Content-Length", str(len(body_bytes)))
            self.end_headers()
            self.wfile.write(body_bytes)
        except urllib.error.HTTPError as e:
            logger.warning(
                f"[proxy] upstream HTTP error {e.code} for {method} {self.path}"
            )
            self.send_error(e.code or 502)
        except Exception as e:
            logger.warning(f"[proxy] upstream error for {method} {self.path}: {e}")
            self.send_error(502)
