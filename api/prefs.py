from quart import request


class PrefsAPI:
    def _register_prefs_apis(self):
        pn = self._plugin_name
        self.context.register_web_api(f"/{pn}/prefs", self._api_prefs_get, ["GET"], "Get user preferences")
        self.context.register_web_api(f"/{pn}/prefs", self._api_prefs_set, ["POST"], "Save user preferences")

    async def _api_prefs_get(self):
        from ..main import _load_prefs
        return _load_prefs()

    async def _api_prefs_set(self):
        data = await request.get_json() or {}
        if not isinstance(data, dict) or not data:
            return {"error": "no data"}, 400
        from ..main import _load_prefs, _save_prefs
        prefs = _load_prefs()
        allowed = {"bgm_file", "bgm_volume", "voice_volume"}
        for key in data:
            if key in allowed:
                prefs[key] = data[key]
        _save_prefs(prefs)
        return {"status": "ok"}
