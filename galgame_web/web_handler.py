import hashlib
import hmac
import pathlib
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs

from astrbot.api import logger

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}

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
    stem = pathlib.Path(name).name
    if not stem or stem != name.split("/")[-1].split("\\")[-1]:
        return None
    resolved = (base_dir / stem).resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        return None
    return resolved


def _make_auth_token(password: str, ts: int) -> str:
    h = hmac.new(password.encode(), str(ts).encode(), "sha256").hexdigest()
    return f"{ts}:{h}"


def _check_auth_token(password: str, token: str, max_age: int = 86400) -> bool:
    try:
        parts = token.split(":", 1)
        ts = int(parts[0])
        if int(time.time()) - ts > max_age:
            return False
        expected = hmac.new(password.encode(), str(ts).encode(), "sha256").hexdigest()
        return (
            hashlib.sha256(parts[1].encode()).hexdigest()
            == hashlib.sha256(expected.encode()).hexdigest()
        )
    except (ValueError, IndexError):
        return False


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
    web_password: str = ""

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
        return _check_auth_token(pwd, token)

    def _require_auth(self) -> bool:
        if self._auth_ok():
            return False
        path = self.path.split("?")[0]
        if path == "/login":
            return False
        if path == "/api/login":
            return False
        self.send_response(302)
        self.send_header("Location", "/login")
        self.end_headers()
        return True

    def do_GET(self):
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
        path = self.path.split("?")[0]

        if path == "/api/login":
            return self._handle_login()
        if path.startswith("/api/"):
            if self._require_auth():
                return
            return self._proxy("POST")
        self.send_error(404)

    def _handle_login(self):
        length = int(self.headers.get("Content-Length", 0))
        body = (
            self.rfile.read(length).decode("utf-8", errors="replace")
            if length > 0
            else ""
        )
        params = parse_qs(body)
        submitted = params.get("password", [""])[0]
        pwd = GalgameWebHandler.web_password
        if pwd and submitted == pwd:
            ts = int(time.time())
            token = _make_auth_token(pwd, ts)
            self.send_response(302)
            self.send_header("Location", "/")
            self.send_header(
                "Set-Cookie", f"galgame_auth={token}; Path=/; HttpOnly; Max-Age=86400"
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
        path = self.path.split("?")[0]
        if path == "/":
            path = "/index.html"
        filename = path.lstrip("/")
        safe = _safe_path(filename, self.static_dir)
        if filename.startswith("assets/"):
            safe_assets = _safe_path(filename, self.assets_dir)
            if safe_assets and safe_assets.is_file():
                safe = safe_assets
        elif filename.startswith("audio/"):
            safe_audio = _safe_path(filename, self.audio_dir)
            if safe_audio and safe_audio.is_file():
                safe = safe_audio
        elif filename.startswith("bgm/"):
            safe_bgm = _safe_path(filename, self.bgm_dir)
            if safe_bgm and safe_bgm.is_file():
                safe = safe_bgm
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
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)
        except OSError:
            self.send_error(500)

    def _proxy(self, method):
        url = self.upstream + self.path
        body = None
        length = 0
        if method == "POST":
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length > 0 else None

        logger.debug(
            f"[proxy] {method} {self.path} cl={length} "
            f"body_bytes={len(body) if body else 0} "
            f"jwt={'yes' if GalgameWebHandler.jwt_token else 'no'}"
        )

        req = urllib.request.Request(url, data=body, method=method)
        for key, val in self.headers.items():
            low = key.lower()
            if low not in ("host", "connection", "content-length", "transfer-encoding"):
                req.add_header(key, val)
        if body and method == "POST":
            req.add_header(
                "Content-Type", self.headers.get("Content-Type", "application/json")
            )
        if GalgameWebHandler.jwt_token:
            req.add_header("Authorization", f"Bearer {GalgameWebHandler.jwt_token}")

        try:
            resp = urllib.request.urlopen(req, timeout=300)
            status = resp.status
            logger.debug(f"[proxy] upstream responded {status}")

            self.send_response(status)
            for key, val in resp.headers.items():
                low = key.lower()
                if low in ("transfer-encoding", "connection", "keep-alive"):
                    continue
                self.send_header(key, val)
            self.send_header("Access-Control-Allow-Origin", "*")

            body_bytes = resp.read()
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
