import asyncio
import datetime
import os
import re
import secrets
import threading

import jwt

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.star import Context, Star

from .api.assets import AssetAPI
from .api.audio import AudioAPI
from .api.bgm import BGMAPI
from .api.config import ConfigAPI
from .api.favorites import FavoritesAPI
from .api.prefs import PrefsAPI
from .api.session import SessionAPI
from .galgame_web import tts
from .galgame_web.session_helpers import (
    ASSETS_DIR,
    AUDIO_DIR,
    BGM_DIR,
    SESSIONS_DIR,
    delete_astrbot_conv,
    gc_audio_files,
    gc_sessions,
    gc_temp_voice_files,
    load_all_sessions,
    save_session,
    sync_sessions_to_db,
)
from .galgame_web.utils import (
    _EMOTION_TYPO_PATTERN,
    PLUGIN_NAME,
    extract_all_emotions,
    get_emotion_tags,
)
from .galgame_web.web_handler import (
    BoundedThreadingHTTPServer,
    GalgameWebHandler,
    resolve_web_bind_host,
)


class GalgamePlugin(
    AssetAPI, AudioAPI, BGMAPI, ConfigAPI, FavoritesAPI, PrefsAPI, SessionAPI, Star
):
    _plugin_name = PLUGIN_NAME

    def __init__(self, context: Context, config: dict | None = None):
        Star.__init__(self, context)
        self.config = config or {}
        self._sessions: dict[str, dict] = {}
        self._web_server = None
        self._web_thread: threading.Thread | None = None
        self._proxy_jwt_secret = ""
        self._proxy_jwt_username = ""
        self._background_tasks: set[asyncio.Task] = set()
        self._active_send_tasks: set[asyncio.Task] = set()
        self._terminating = False
        cfg = self.context.get_config()
        dashboard_cfg = cfg.get("dashboard", {}) if cfg else {}
        self._webchat_username = dashboard_cfg.get("username", "astrbot")

        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        gc_sessions(
            self._sessions,
            self.config,
            lambda sid: self._track_task(
                delete_astrbot_conv(self.context, self._webchat_username, sid)
            ),
        )
        load_all_sessions(self._sessions)
        self._track_task(
            sync_sessions_to_db(
                self.context,
                self._webchat_username,
                self.config,
                self._sessions,
                lambda sid: save_session(self._sessions, sid),
            )
        )
        gc_audio_files(self._sessions)
        gc_temp_voice_files()

        self._register_apis()

        web_port = int(self.config.get("web_port", 0) or 0)
        web_enabled = self.config.get("web_enabled", True)
        if web_enabled and web_port > 0:
            configured_password = self.config.get("web_password", "")
            web_password = (
                configured_password if isinstance(configured_password, str) else ""
            )
            configured_host = self.config.get("web_host", "0.0.0.0")
            web_host = resolve_web_bind_host(configured_host, web_password)
            if web_host != str(configured_host or "0.0.0.0").strip():
                logger.warning(
                    "Galgame WebUI has no password; binding to 127.0.0.1 only. "
                    "Set web_password to allow LAN access."
                )
                web_host = "127.0.0.1"
            GalgameWebHandler.web_password = web_password
            GalgameWebHandler.auth_secret = secrets.token_bytes(32)
            self._setup_proxy_auth()
            self._start_web_server(web_host, web_port)

    def _register_apis(self):
        self._register_asset_apis()
        self._register_audio_apis()
        self._register_bgm_apis()
        self._register_config_apis()
        self._register_favorites_apis()
        self._register_prefs_apis()
        self._register_session_apis()

    def _track_task(self, awaitable):
        task = asyncio.ensure_future(awaitable)
        if getattr(self, "_terminating", False):
            task.cancel()
            return task
        self._background_tasks.add(task)

        def _done(completed):
            self._background_tasks.discard(completed)
            if completed.cancelled():
                return
            try:
                error = completed.exception()
            except asyncio.CancelledError:
                return
            if error:
                logger.warning(f"Galgame background task failed: {error}")

        task.add_done_callback(_done)
        return task

    def _get_history_limit(self) -> int:
        max_turns = (
            self.context.get_config()
            .get("provider_settings", {})
            .get("max_context_length", 50)
        )
        if max_turns <= 0:
            max_turns = 200
        return max_turns * 2

    # ---- web server ----

    def _start_web_server(self, host: str, port: int):
        cfg = self.context.get_config()
        dashboard_cfg = cfg.get("dashboard", {}) if cfg else {}
        upstream_port = (
            os.environ.get("DASHBOARD_PORT")
            or os.environ.get("ASTRBOT_DASHBOARD_PORT")
            or dashboard_cfg.get("port", 6185)
        )
        GalgameWebHandler.upstream = f"http://127.0.0.1:{upstream_port}"
        GalgameWebHandler.assets_dir = ASSETS_DIR
        GalgameWebHandler.audio_dir = AUDIO_DIR
        GalgameWebHandler.bgm_dir = BGM_DIR
        try:
            self._web_server = BoundedThreadingHTTPServer(
                (host, port), GalgameWebHandler
            )
            self._web_thread = threading.Thread(
                target=self._web_server.serve_forever, daemon=True
            )
            self._web_thread.start()
            logger.info(f"Galgame WebUI started at http://{host}:{port}")
        except OSError as e:
            logger.warning(f"Failed to start Galgame WebUI on port {port}: {e}")

    def _setup_proxy_auth(self):
        GalgameWebHandler.jwt_token = ""
        GalgameWebHandler.jwt_token_factory = None
        try:
            cfg = self.context.get_config()
            dcfg = cfg.get("dashboard", {}) if cfg else {}
            secret = dcfg.get("jwt_secret", "")
            username = dcfg.get("username", "astrbot")
            if secret and username:
                self._proxy_jwt_secret = secret
                self._proxy_jwt_username = username
                GalgameWebHandler.jwt_token_factory = self._make_proxy_jwt
                logger.info("Galgame proxy authentication configured")
            else:
                logger.warning(
                    "Could not generate JWT for proxy: jwt_secret or username missing"
                )
        except Exception as e:
            logger.warning(f"Failed to setup proxy auth: {e}")

    def _make_proxy_jwt(self) -> str:
        if not self._proxy_jwt_secret or not self._proxy_jwt_username:
            return ""
        now = datetime.datetime.now(datetime.timezone.utc)
        return jwt.encode(
            {
                "username": self._proxy_jwt_username,
                "iat": now,
                "exp": now + datetime.timedelta(minutes=5),
            },
            self._proxy_jwt_secret,
            algorithm="HS256",
        )

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
            if self.config.get("tts_enabled", True):
                session["_bg_tts_task"] = self._track_task(
                    tts.bg_tts(text, session, self.config, self.context)
                )
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
                comp.text = re.sub(_EMOTION_TYPO_PATTERN, "", comp.text)

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
        if getattr(self, "_terminating", False):
            return
        self._terminating = True
        if self._web_server:
            try:
                await asyncio.to_thread(self._web_server.shutdown)
                self._web_server.server_close()
            except Exception:
                pass
            self._web_server = None
        if self._web_thread:
            await asyncio.to_thread(self._web_thread.join, 2)
            self._web_thread = None
        GalgameWebHandler.jwt_token = ""
        GalgameWebHandler.jwt_token_factory = None
        GalgameWebHandler.web_password = ""
        self.context.registered_web_apis[:] = [
            api
            for api in self.context.registered_web_apis
            if getattr(api[1], "__self__", None) is not self
        ]
        current_task = asyncio.current_task()
        tasks = list(
            (self._background_tasks | getattr(self, "_active_send_tasks", set()))
            - ({current_task} if current_task else set())
        )
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._background_tasks.clear()
        getattr(self, "_active_send_tasks", set()).clear()
        save_results = [
            save_session(self._sessions, sid) for sid in list(self._sessions.keys())
        ]
        if all(save_results):
            gc_audio_files(self._sessions)
        self._sessions.clear()
