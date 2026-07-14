from quart import request


class PrefsAPI:
    def _register_prefs_apis(self):
        pn = self._plugin_name
        self.context.register_web_api(
            f"/{pn}/prefs", self._api_prefs_get, ["GET"], "Get user preferences"
        )
        self.context.register_web_api(
            f"/{pn}/prefs", self._api_prefs_set, ["POST"], "Save user preferences"
        )

    async def _api_prefs_get(self):
        from ..main import _load_prefs

        return _load_prefs()

    async def _api_prefs_set(self):
        data = await request.get_json() or {}
        if not isinstance(data, dict) or not data:
            return {"error": "no data"}, 400
        from ..galgame_web.assets_helpers import safe_path
        from ..main import BGM_DIR, _load_prefs, _save_prefs

        prefs = _load_prefs()
        if "bgm_file" in data:
            filename = data["bgm_file"]
            if not isinstance(filename, str):
                return {"error": "invalid bgm_file"}, 400
            if filename:
                bgm_path = safe_path(filename, BGM_DIR)
                if not bgm_path or not bgm_path.is_file():
                    return {"error": "bgm file not found"}, 404
            prefs["bgm_file"] = filename
        for key in ("bgm_volume", "voice_volume"):
            if key in data:
                value = data[key]
                if not isinstance(value, (int, float)) or isinstance(value, bool):
                    return {"error": f"invalid {key}"}, 400
                prefs[key] = max(0.0, min(float(value), 1.0))
        if "bgm_playing" in data:
            if not isinstance(data["bgm_playing"], bool):
                return {"error": "invalid bgm_playing"}, 400
            prefs["bgm_playing"] = data["bgm_playing"]
        _save_prefs(prefs)
        return {"status": "ok"}
