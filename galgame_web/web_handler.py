import pathlib
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler

from astrbot.api import logger

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def _safe_path(name: str, base_dir: pathlib.Path) -> pathlib.Path | None:
    stem = pathlib.Path(name).name
    if not stem or stem != name.split("/")[-1].split("\\")[-1]:
        return None
    resolved = (base_dir / stem).resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        return None
    return resolved


class GalgameWebHandler(BaseHTTPRequestHandler):
    upstream = "http://127.0.0.1:6185"
    static_dir: pathlib.Path = pathlib.Path(__file__).parent / "galgame"
    assets_dir: pathlib.Path = pathlib.Path("data/plugin_data") / "astrbot_plugin_galgame_web" / "assets"
    jwt_token: str = ""

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
    }

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        if self.path.startswith("/api/"):
            return self._proxy("GET")
        return self._serve_static()

    def do_POST(self):
        if self.path.startswith("/api/"):
            return self._proxy("POST")
        self.send_error(404)

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
            req.add_header("Content-Type", self.headers.get("Content-Type", "application/json"))
        if GalgameWebHandler.jwt_token:
            req.add_header("Authorization", f"Bearer {GalgameWebHandler.jwt_token}")

        try:
            resp = urllib.request.urlopen(req, timeout=120)
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
            logger.warning(f"[proxy] upstream HTTP error {e.code} for {method} {self.path}")
            self.send_error(e.code or 502)
        except Exception as e:
            logger.warning(f"[proxy] upstream error for {method} {self.path}: {e}")
            self.send_error(502)
