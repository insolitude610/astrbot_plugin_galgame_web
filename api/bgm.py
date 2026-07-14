import base64
import binascii
import uuid

from quart import Response, request

from astrbot.api import logger

_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus"}
MAX_BGM_BYTES = 30 * 1024 * 1024
MAX_BGM_BASE64_CHARS = ((MAX_BGM_BYTES + 2) // 3) * 4


class BGMAPI:
    def _register_bgm_apis(self):
        pn = self._plugin_name
        self.context.register_web_api(
            f"/{pn}/bgm/list", self._api_bgm_list, ["GET"], "List BGM files"
        )
        self.context.register_web_api(
            f"/{pn}/bgm/upload", self._api_bgm_upload, ["POST"], "Upload BGM file"
        )
        self.context.register_web_api(
            f"/{pn}/bgm/delete", self._api_bgm_delete, ["POST"], "Delete BGM file"
        )
        self.context.register_web_api(
            f"/{pn}/bgm/file", self._api_bgm_file, ["GET"], "Serve BGM file"
        )
        self.context.register_web_api(
            f"/{pn}/bgm/data",
            self._api_bgm_data,
            ["GET"],
            "Get BGM file as base64 JSON",
        )

    async def _api_bgm_list(self):
        from ..main import BGM_DIR

        BGM_DIR.mkdir(parents=True, exist_ok=True)
        entries = []
        for f in sorted(BGM_DIR.iterdir()):
            if f.is_file() and f.suffix.lower() in _AUDIO_EXTS:
                entries.append({"name": f.name, "size": f.stat().st_size})
        return {"files": entries}

    async def _api_bgm_upload(self):
        from ..galgame_web.assets_helpers import safe_path
        from ..main import BGM_DIR

        data = await request.get_json() or {}
        if not isinstance(data, dict):
            return {"error": "invalid request"}, 400
        b64 = data.get("data", "")
        raw_name = data.get("name", "")
        name = raw_name.strip() if isinstance(raw_name, str) else ""
        if not isinstance(b64, str) or not b64:
            return {"error": "no data"}, 400
        if not name:
            name = f"bgm_{uuid.uuid4().hex[:8]}.mp3"
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        if len(b64) > MAX_BGM_BASE64_CHARS:
            return {"error": "file too large (max 30MB)"}, 400
        sp = safe_path(name, BGM_DIR)
        if not sp or sp.suffix.lower() not in _AUDIO_EXTS:
            return {"error": "unsupported audio format"}, 400
        try:
            raw = base64.b64decode(b64, validate=True)
            if len(raw) > MAX_BGM_BYTES:
                return {"error": "file too large"}, 400
            BGM_DIR.mkdir(parents=True, exist_ok=True)
            sp.write_bytes(raw)
            logger.info(f"Uploaded BGM: {sp.name} ({len(raw)} bytes)")
            return {"uploaded": sp.name}
        except (binascii.Error, ValueError) as e:
            return {"error": f"invalid base64 data: {e}"}, 400
        except Exception as e:
            logger.warning(f"Failed to save BGM {name}: {e}")
            return {"error": str(e)}, 500

    async def _api_bgm_delete(self):
        from ..galgame_web.assets_helpers import safe_path
        from ..main import BGM_DIR, _load_prefs, _save_prefs

        data = await request.get_json() or {}
        if not isinstance(data, dict):
            return {"error": "invalid request"}, 400
        raw_filename = data.get("filename", "")
        filename = raw_filename.strip() if isinstance(raw_filename, str) else ""
        if not filename:
            return {"error": "no filename"}, 400
        sp = safe_path(filename, BGM_DIR)
        if not sp or not sp.exists() or not sp.is_file():
            return {"error": "file not found"}, 404
        try:
            sp.unlink()
            logger.info(f"Deleted BGM: {sp.name}")
        except OSError as e:
            return {"error": str(e)}, 500
        prefs = _load_prefs()
        if prefs.get("bgm_file") == filename:
            prefs["bgm_file"] = ""
            _save_prefs(prefs)
        return {"deleted": sp.name}

    async def _api_bgm_file(self):
        from ..galgame_web.assets_helpers import safe_path
        from ..main import BGM_DIR

        filename = request.args.get("name", "")
        sp = safe_path(filename, BGM_DIR)
        if not sp or not sp.exists() or not sp.is_file():
            return {"error": "file not found"}, 404
        mime_map = {
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".ogg": "audio/ogg",
            ".flac": "audio/flac",
            ".m4a": "audio/mp4",
            ".aac": "audio/aac",
            ".opus": "audio/ogg",
        }
        resp = Response(
            sp.read_bytes(),
            content_type=mime_map.get(sp.suffix.lower(), "application/octet-stream"),
        )
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    async def _api_bgm_data(self):
        from ..galgame_web.assets_helpers import safe_path
        from ..main import BGM_DIR

        filename = request.args.get("name", "")
        sp = safe_path(filename, BGM_DIR)
        if not sp or not sp.exists() or not sp.is_file():
            return {"error": "not found"}, 404
        raw = sp.read_bytes()
        mime_map = {
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".ogg": "audio/ogg",
            ".flac": "audio/flac",
            ".m4a": "audio/mp4",
            ".aac": "audio/aac",
            ".opus": "audio/ogg",
        }
        return {
            "audio": base64.b64encode(raw).decode(),
            "mime": mime_map.get(sp.suffix.lower(), "application/octet-stream"),
        }
