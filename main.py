import asyncio
import datetime
import json
import os
import pathlib
import subprocess
import threading

import jwt

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.star import Context, Star, StarTools

from .api.assets import AssetAPI
from .api.audio import AudioAPI
from .api.bgm import BGMAPI
from .api.config import ConfigAPI
from .api.favorites import FavoritesAPI
from .api.prefs import PrefsAPI
from .api.session import SessionAPI
from .galgame_web.session_helpers import (
    SESSIONS_DIR,
    delete_astrbot_conv,
    gc_audio_files,
    gc_sessions,
    load_all_sessions,
    save_session,
    sync_sessions_to_db,
)
from .galgame_web.utils import (
    PLUGIN_NAME,
    extract_all_emotions,
    get_emotion_tags,
)
from .galgame_web.web_handler import GalgameWebHandler

_DATA_BASE = StarTools.get_data_dir(PLUGIN_NAME)
ASSETS_DIR = _DATA_BASE / "assets"
AUDIO_DIR = _DATA_BASE / "audio"
BGM_DIR = _DATA_BASE / "bgm"
FAVORITES_PATH = _DATA_BASE / "favorites.json"
PREFS_PATH = _DATA_BASE / "prefs.json"


def _load_prefs() -> dict:
    if not PREFS_PATH.exists():
        return {}
    try:
        return json.loads(PREFS_PATH.read_text(encoding="utf-8")) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_prefs(data: dict):
    PREFS_PATH.parent.mkdir(parents=True, exist_ok=True)
    PREFS_PATH.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _convert_audio(wav_path: pathlib.Path) -> pathlib.Path | None:
    mp3_path = wav_path.with_suffix(".mp3")
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_path), "-b:a", "128k", str(mp3_path)],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0 and mp3_path.exists():
            wav_path.unlink()
            return mp3_path
    except Exception:
        pass
    logger.warning("[audio] ffmpeg conversion failed, keeping wav")
    return None


class GalgamePlugin(
    AssetAPI, AudioAPI, BGMAPI, ConfigAPI, FavoritesAPI, PrefsAPI, SessionAPI, Star
):
    _plugin_name = PLUGIN_NAME

    def __init__(self, context: Context, config: dict | None = None):
        Star.__init__(self, context)
        self.config = config or {}
        self._sessions: dict[str, dict] = {}
        self._web_server: threading.Thread = None
        cfg = self.context.get_config()
        dashboard_cfg = cfg.get("dashboard", {}) if cfg else {}
        self._webchat_username = dashboard_cfg.get("username", "astrbot")

        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        gc_sessions(
            self._sessions,
            self.config,
            lambda sid: delete_astrbot_conv(self.context, self._webchat_username, sid),
        )
        load_all_sessions(self._sessions)
        t = asyncio.ensure_future(
            sync_sessions_to_db(
                self.context,
                self._webchat_username,
                self.config,
                self._sessions,
                lambda sid: save_session(self._sessions, sid),
            )
        )
        t.add_done_callback(
            lambda _t: (
                logger.warning(f"sync_sessions_to_db failed: {_t.exception()}")
                if _t.exception()
                else None
            )
        )
        gc_audio_files(self._sessions)

        web_port = int(self.config.get("web_port", 0) or 0)
        web_enabled = self.config.get("web_enabled", True)
        if web_enabled and web_port > 0:
            GalgameWebHandler.web_password = self.config.get("web_password", "") or ""
            self._setup_proxy_auth()
            self._start_web_server(web_port)

        self._register_apis()

    def _register_apis(self):
        self._register_asset_apis()
        self._register_audio_apis()
        self._register_bgm_apis()
        self._register_config_apis()
        self._register_favorites_apis()
        self._register_prefs_apis()
        self._register_session_apis()

    # ---- web server ----

    def _start_web_server(self, port: int):
        from http.server import ThreadingHTTPServer

        upstream_port = (
            os.environ.get("DASHBOARD_PORT")
            or os.environ.get("ASTRBOT_DASHBOARD_PORT")
            or "6185"
        )
        GalgameWebHandler.upstream = f"http://127.0.0.1:{upstream_port}"
        GalgameWebHandler.assets_dir = ASSETS_DIR
        try:
            self._web_server = ThreadingHTTPServer(("0.0.0.0", port), GalgameWebHandler)
            t = threading.Thread(target=self._web_server.serve_forever, daemon=True)
            t.start()
            logger.info(f"Galgame WebUI started at http://localhost:{port}")
        except OSError as e:
            logger.warning(f"Failed to start Galgame WebUI on port {port}: {e}")

    def _setup_proxy_auth(self):
        try:
            cfg = self.context.get_config()
            dcfg = cfg.get("dashboard", {}) if cfg else {}
            secret = dcfg.get("jwt_secret", "")
            username = dcfg.get("username", "astrbot")
            if secret and username:
                payload = {
                    "username": username,
                    "exp": datetime.datetime.now(datetime.timezone.utc)
                    + datetime.timedelta(days=7),
                }
                GalgameWebHandler.jwt_token = jwt.encode(
                    payload, secret, algorithm="HS256"
                )
                logger.info("Galgame proxy JWT generated successfully")
            else:
                logger.warning(
                    "Could not generate JWT for proxy: jwt_secret or username missing"
                )
        except Exception as e:
            logger.warning(f"Failed to setup proxy auth: {e}")

    # ---- llm hooks ----

    @filter.on_llm_request()
    async def _inject_galgame_rules(self, event: AstrMessageEvent, req) -> None:
        from .galgame_web.utils import DEFAULT_GALGAME_PROMPT

        umo = event.unified_msg_origin
        if not umo:
            return
        parts = umo.partition(":FriendMessage:")
        sid = parts[2].rsplit("!", 1)[-1] if parts[2] else ""
        if sid not in self._sessions:
            return
        rules = self.config.get("system_prompt_extra", "")
        if not rules.strip():
            rules = DEFAULT_GALGAME_PROMPT
        emotion_tags = get_emotion_tags(self.config)
        rules = rules.replace("{{emotions}}", ", ".join(emotion_tags))
        req.system_prompt += "\n\n" + rules
        user_text = event.message_str.strip()
        for comp in event.message_obj.chain:
            if hasattr(comp, "text") and isinstance(comp.text, str):
                t = comp.text.strip()
                if t and "[系统自动注入]" not in t and "[ComponentType" not in t:
                    user_text = t
        if "[系统自动注入]" in user_text:
            parts = user_text.split("\n", 1)
            if len(parts) > 1:
                user_text = parts[1].strip()
            elif "：" in user_text:
                user_text = user_text.rsplit("：", 1)[-1].strip()
        self._sessions[sid]["_last_user_text"] = user_text

    @filter.on_llm_response()
    async def _capture_llm_response(self, event: AstrMessageEvent, resp) -> None:
        umo = event.unified_msg_origin
        if not umo:
            return
        parts = umo.partition(":FriendMessage:")
        sid = parts[2].rsplit("!", 1)[-1] if parts[2] else ""
        session = self._sessions.get(sid)
        if not session:
            return
        text = resp.completion_text or ""
        if text.strip():
            session["_last_resp_text"] = text
        ev = session.get("_resp_event")
        if ev and not ev.is_set():
            ev.set()

    @filter.on_decorating_result(priority=1)
    async def _handle_emotion_strip(self, event: AstrMessageEvent) -> None:
        umo = event.unified_msg_origin
        if not umo:
            return
        parts = umo.partition(":FriendMessage:")
        sid = parts[2].rsplit("!", 1)[-1] if parts[2] else ""
        session = self._sessions.get(sid)
        if not session:
            return
        result = event.get_result()
        if not result or not result.chain:
            return

        emotion_tags = get_emotion_tags(self.config)
        for comp in result.chain:
            if hasattr(comp, "text") and isinstance(comp.text, str):
                clean, known, all_emotions = extract_all_emotions(
                    comp.text, emotion_tags
                )
                if known:
                    session["_pending_emotions"] = known
                    session["_pending_all_emotions"] = (
                        all_emotions if all_emotions else known
                    )
                comp.text = clean

    # ---- command ----

    @filter.command("galgame")
    async def cmd_galgame(self, event: AstrMessageEvent) -> MessageEventResult:
        web_port = int(self.config.get("web_port", 0) or 0)
        url = (
            f"http://localhost:{web_port}"
            if web_port > 0
            else "（未启用独立 WebUI，请在插件设置中设置 web_port）"
        )
        yield event.plain_result(f"AI Galgame 虚拟伙伴\n\n浏览器访问：{url}")

    async def terminate(self):
        if self._web_server:
            try:
                self._web_server.shutdown()
            except Exception:
                pass
            self._web_server = None
        for sid in list(self._sessions.keys()):
            save_session(self._sessions, sid)
        self._sessions.clear()
