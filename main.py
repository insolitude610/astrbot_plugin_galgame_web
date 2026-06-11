import asyncio
import base64
import datetime
import json
import os
import pathlib
import re
import subprocess
import threading
import time
import uuid

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
    EMOTION_PATTERN,
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

    def _get_history_limit(self) -> int:
        max_turns = self.context.get_config().get("provider_settings", {}).get("max_context_length", 50)
        if max_turns <= 0:
            max_turns = 200
        return max_turns * 2

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
        GalgameWebHandler.audio_dir = AUDIO_DIR
        GalgameWebHandler.bgm_dir = BGM_DIR
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
                session["_bg_tts_task"] = asyncio.ensure_future(
                    self._do_bg_tts(text, session)
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

    async def _do_bg_tts(self, raw_text: str, session: dict):
        """Synthesize TTS in background, parallel to pipeline decorate/respond stages."""
        try:
            emotion_tags = get_emotion_tags(self.config)

            clean_text = re.sub(EMOTION_PATTERN, "", raw_text)
            clean_text = re.sub(r"\([a-z-]+\)", "", clean_text)
            clean_text = re.sub(r"<#\d+\.?\d*#>", "", clean_text).strip()

            if not clean_text:
                session["_bg_tts_result"] = ("", "", "")
                return

            _, _, emotions_all = extract_all_emotions(raw_text, emotion_tags)

            tts_emotion_map: dict = {}
            try:
                tts_emotion_map = json.loads(self.config.get("tts_emotion_map", "{}") or "{}")
            except (json.JSONDecodeError, TypeError):
                pass

            tts_provider_id = self.config.get("tts_provider", "").strip()
            if tts_provider_id:
                tts_provider = self.context.provider_manager.inst_map.get(tts_provider_id)
            else:
                tts_provider = self.context.get_using_tts_provider()

            if not tts_provider:
                session["_bg_tts_result"] = ("", "", "")
                return

            t0 = time.time()
            logger.info(f"[bg-tts-debug] calling _parallel_tts clean_len={len(clean_text)} emos={emotions_all}")
            audio_path = await self._parallel_tts(clean_text, emotions_all, tts_emotion_map, tts_provider)
            logger.info(f"[bg-tts-debug] _parallel_tts returned {'path' if audio_path else 'None'}")
            if audio_path:
                raw = audio_path.read_bytes()
                mime = self._detect_audio_mime(raw)
                audio_b64 = base64.b64encode(raw).decode()
                audio_mime_val = mime
                AUDIO_DIR.mkdir(parents=True, exist_ok=True)
                audio_file = f"{uuid.uuid4().hex}{self._ext_for_mime(mime)}"
                (AUDIO_DIR / audio_file).write_bytes(raw)
                if self.config.get("audio_format", "wav") == "mp3":
                    converted = await asyncio.to_thread(_convert_audio, AUDIO_DIR / audio_file)
                    if converted:
                        audio_file = converted.name
                        raw = converted.read_bytes()
                        audio_b64 = base64.b64encode(raw).decode()
                        audio_mime_val = "audio/mpeg"
                logger.info(f"[bg-tts] synthesized {len(raw)} bytes {mime} in {time.time() - t0:.1f}s (parallel)")
                session["_bg_tts_result"] = (audio_b64, audio_mime_val, audio_file)
            else:
                session["_bg_tts_result"] = ("", "", "")
        except Exception as e:
            logger.warning(f"[bg-tts] synthesis failed: {e}")
            session["_bg_tts_result"] = ("", "", "")

    def _split_sentences(self, text: str):
        parts = re.split(r'(?<=[。！？…~])\s*|(?<=[\.!\?])\s+', text)
        return [p for p in parts if p.strip()]

    def _build_sentence_tagged_texts(self, clean_text, emotions_all, emotion_map):
        sentences = self._split_sentences(clean_text)
        if len(sentences) <= 1:
            if emotions_all:
                return [self._build_tagged_text(clean_text, emotions_all, emotion_map)]
            return [f"[neutral]{clean_text}"]
        cursor = 0
        result = []
        for sent in sentences:
            sent_start = clean_text.index(sent, cursor)
            if emotions_all:
                sent_end_field = sent_start + len(sent)
                sent_emotions = [(tag, pos) for tag, pos in emotions_all
                                if sent_start <= pos < sent_end_field]
            else:
                sent_emotions = []
            if sent_emotions:
                forced = [(tag, 0) for tag, _ in sent_emotions]
                tagged = self._build_tagged_text(sent, forced, emotion_map)
            else:
                tagged = f"[neutral]{sent}"
            result.append(tagged)
            cursor = sent_start + len(sent)
        return result

    async def _parallel_tts(self, clean_text, emotions_all, emotion_map, tts_provider):
        tagged_sentences = self._build_sentence_tagged_texts(
            clean_text, emotions_all, emotion_map
        )
        logger.info(f"[bg-tts-debug] _parallel_tts {len(tagged_sentences)} sentences, first={tagged_sentences[0][:50] if tagged_sentences else 'none'}")
        if len(tagged_sentences) <= 1:
            path = await tts_provider.get_audio(tagged_sentences[0])
            return pathlib.Path(path) if path else None

        sem = asyncio.Semaphore(5)

        async def _do_one(ts):
            async with sem:
                return await asyncio.to_thread(tts_provider.get_audio, ts)

        tasks = [_do_one(ts) for ts in tagged_sentences]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        paths = []
        for r in results:
            if isinstance(r, str) and pathlib.Path(r).exists():
                paths.append(pathlib.Path(r))
            elif isinstance(r, Exception):
                logger.warning(f"[bg-tts] parallel TTS sentence failed: {r}")

        if not paths:
            return None
        if len(paths) == 1:
            return paths[0]

        return await asyncio.to_thread(self._concat_audio, paths)

    def _concat_audio(self, paths):
        concat_file = paths[0].parent / f"_concat_{uuid.uuid4().hex}.txt"
        output = paths[0].parent / f"{uuid.uuid4().hex}.wav"
        with open(concat_file, 'w', encoding='utf-8') as f:
            for p in paths:
                f.write(f"file '{p}'\n")
        try:
            result = subprocess.run(
                ['ffmpeg', '-y', '-f', 'concat', '-safe', '0',
                 '-i', str(concat_file), '-c', 'copy', str(output)],
                capture_output=True, timeout=30
            )
            if result.returncode == 0 and output.exists():
                for p in paths:
                    try:
                        p.unlink()
                    except OSError:
                        pass
                return output
        except Exception:
            pass
        finally:
            try:
                concat_file.unlink()
            except OSError:
                pass
        return paths[0]

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
