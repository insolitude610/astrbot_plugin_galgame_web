class ConfigAPI:
    def _register_config_apis(self):
        pn = self._plugin_name
        self.context.register_web_api(
            f"/{pn}/config", self._api_config, ["GET"], "Get plugin configuration"
        )

    async def _api_config(self):
        from ..galgame_web.assets_helpers import (
            find_asset_for,
            list_asset_files,
            resolve_assets,
        )
        from ..galgame_web.session_helpers import ASSETS_DIR, load_prefs
        from ..galgame_web.utils import get_emotion_tags

        files = list_asset_files(ASSETS_DIR)
        resolved = resolve_assets(self.config, files)
        emotion_keys = get_emotion_tags(self.config)
        prefs = load_prefs()
        history_avatar = (
            self.config.get("history_avatar", "")
            or find_asset_for("history_avatar", files, "avatar")
            or find_asset_for("avatar", files)
        )
        vrm_model = self.config.get("vrm_model", "") or resolved.get("vrm_model", "")
        return {
            "sprite_mode": self.config.get("sprite_mode", "single"),
            "rapid_click_threshold": self.config.get("rapid_click_threshold", 5),
            "rapid_window_seconds": self.config.get("rapid_window_seconds", 3),
            "rapid_click_enabled": self.config.get("rapid_click_enabled", True),
            "tts_provider": self.config.get("tts_provider", ""),
            "expressions": resolved["expressions"],
            "expressions_blink": resolved.get("expressions_blink", {}),
            "emotion_keys": emotion_keys,
            "layers": resolved["layers"],
            "vrm_model": vrm_model,
            "character_name": self.config.get("character_name", ""),
            "background": resolved["background"],
            "sprite_scale": self.config.get("sprite_scale", 1.0),
            "sprite_bottom": self.config.get("sprite_bottom", 28.0),
            "sprite_left": self.config.get("sprite_left", 50.0),
            "typewriter_speed": self.config.get("typewriter_speed", 60),
            "history_avatar": history_avatar,
            "bgm_file": prefs.get("bgm_file", ""),
            "bgm_volume": prefs.get("bgm_volume", 0.5),
            "bgm_playing": prefs.get("bgm_playing", True),
            "voice_volume": prefs.get("voice_volume", 1.0),
            "tts_enabled": self.config.get("tts_enabled", True),
            "history_limit": self._get_history_limit(),
            "font_size": self.config.get("font_size", 17),
            "web_port": self.config.get("web_port", 6186),
            "web_host": self.config.get("web_host", "0.0.0.0"),
            "web_enabled": self.config.get("web_enabled", True),
            "font_style": prefs.get("font_style", "serif"),
        }
