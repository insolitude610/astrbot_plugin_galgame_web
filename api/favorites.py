import json
import time
import uuid

from quart import request


class FavoritesAPI:
    def _register_favorites_apis(self):
        pn = self._plugin_name
        self.context.register_web_api(
            f"/{pn}/favorites/list",
            self._api_favorites_list,
            ["GET"],
            "List saved favorites",
        )
        self.context.register_web_api(
            f"/{pn}/favorites/add", self._api_favorites_add, ["POST"], "Add a favorite"
        )
        self.context.register_web_api(
            f"/{pn}/favorites/delete",
            self._api_favorites_delete,
            ["POST"],
            "Delete a favorite",
        )

    async def _api_favorites_list(self):
        return {"favorites": self._load_favorites()}

    async def _api_favorites_add(self):
        data = await request.get_json() or {}
        text = data.get("text", "").strip()
        audio_file = data.get("audio_file", "").strip()
        audio_mime = data.get("audio_mime", "")
        if not text or not audio_file:
            return {"error": "text and audio_file required"}, 400
        favs = self._load_favorites()
        favs.insert(
            0,
            {
                "id": uuid.uuid4().hex,
                "text": text,
                "audio_file": audio_file,
                "audio_mime": audio_mime,
                "saved_at": time.time(),
            },
        )
        self._save_favorites(favs)
        return {"status": "ok"}

    async def _api_favorites_delete(self):
        data = await request.get_json() or {}
        fid = data.get("id", "").strip()
        if not fid:
            return {"error": "id required"}, 400
        favs = self._load_favorites()
        orig_len = len(favs)
        favs = [f for f in favs if f.get("id") != fid]
        if len(favs) == orig_len:
            return {"error": "not found"}, 404
        self._save_favorites(favs)
        return {"status": "ok"}

    def _load_favorites(self) -> list[dict]:
        from ..main import FAVORITES_PATH

        if not FAVORITES_PATH.exists():
            return []
        try:
            return json.loads(FAVORITES_PATH.read_text(encoding="utf-8")) or []
        except (OSError, json.JSONDecodeError):
            return []

    def _save_favorites(self, favs: list[dict]):
        from ..main import FAVORITES_PATH

        FAVORITES_PATH.parent.mkdir(parents=True, exist_ok=True)
        FAVORITES_PATH.write_text(
            json.dumps(favs, ensure_ascii=False, indent=2), encoding="utf-8"
        )
