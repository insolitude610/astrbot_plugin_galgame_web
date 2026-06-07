import base64
import uuid

from quart import Response, request

from astrbot.api import logger


_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus"}


class BGMAPI:
    def _register_bgm_apis(self):
        pn = self._plugin_name
        self.context.register_web_api(f"/{pn}/bgm/list", self._api_bgm_list, ["GET"], "List BGM files")
        self.context.register_web_api(f"/{pn}/bgm/upload", self._api_bgm_upload, ["POST"], "Upload BGM file")
        self.context.register_web_api(f"/{pn}/bgm/delete", self._api_bgm_delete, ["POST"], "Delete BGM file")
        self.context.register_web_api(f"/{pn}/bgm/file", self._api_bgm_file, ["GET"], "Serve BGM file")

    async def _api_bgm_list(self):
        from ..galgame_web.assets_helpers import safe_path
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
        b64 = data.get("data", "")
        name = data.get("name", "").strip()
        if not b64:
            return {"error": "no data"}, 400
        if not name:
            name = f"bgm_{uuid.uuid4().hex[:8]}.mp3"
        if "," in b64:
            b64 = b64.split(",", 1)[1]
        if len(b64) > 30 * 1024 * 1024:
            return {"error": "file too large (max 30MB)"}, 400
        sp = safe_path(name, BGM_DIR)
        if not sp or sp.suffix.lower() not in _AUDIO_EXTS:
            return {"error": "unsupported audio format"}, 400
        try:
            raw = base64.b64decode(b64)
            if len(raw) > 30 * 1024 * 1024:
                return {"error": "file too large"}, 400
            BGM_DIR.mkdir(parents=True, exist_ok=True)
            sp.write_bytes(raw)
            logger.info(f"Uploaded BGM: {sp.name} ({len(raw)} bytes)")
            return {"uploaded": sp.name}
        except Exception as e:
            logger.warning(f"Failed to save BGM {name}: {e}")
            return {"error": str(e)}, 500

    async def _api_bgm_delete(self):
        from ..galgame_web.assets_helpers import safe_path
        from ..main import BGM_DIR, _load_prefs, _save_prefs
        data = await request.get_json() or {}
        filename = data.get("filename", "").strip()
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
        mime_map = {".mp3": "audio/mpeg", ".wav": "audio/wav", ".ogg": "audio/ogg", ".flac": "audio/flac", ".m4a": "audio/mp4", ".aac": "audio/aac", ".opus": "audio/ogg"}
        origin = request.headers.get("Origin", "")
        resp = Response(sp.read_bytes(), content_type=mime_map.get(sp.suffix.lower(), "application/octet-stream"))
        resp.headers["Access-Control-Allow-Origin"] = origin if origin else "*"
        return resp
