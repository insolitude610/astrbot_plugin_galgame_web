import base64
import json
import pathlib
import time
import uuid

from quart import request

from astrbot.api import logger


class AudioAPI:
    def _register_audio_apis(self):
        pn = self._plugin_name
        self.context.register_web_api(f"/{pn}/audio/data", self._api_audio_data, ["GET"], "Get audio file as base64 JSON")

    async def _api_audio_data(self):
        from ..galgame_web.assets_helpers import safe_path
        from ..main import AUDIO_DIR

        filename = request.args.get("name", "")
        sp = safe_path(filename, AUDIO_DIR)
        if not sp or not sp.exists() or not sp.is_file():
            return {"error": "not found"}, 404
        raw = sp.read_bytes()
        mime_map = {".wav": "audio/wav", ".mp3": "audio/mpeg", ".ogg": "audio/ogg", ".flac": "audio/flac", ".m4a": "audio/mp4"}
        return {"audio": base64.b64encode(raw).decode(), "mime": mime_map.get(sp.suffix.lower(), "audio/wav")}
