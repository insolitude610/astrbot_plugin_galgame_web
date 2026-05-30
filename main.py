import asyncio
import base64
import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import threading
import time
import uuid
from http.server import ThreadingHTTPServer

import jwt
from quart import Response, request

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.provider import LLMResponse, ProviderRequest
from astrbot.api.star import Context, Star
from astrbot.core.platform.sources.webchat.webchat_queue_mgr import webchat_queue_mgr
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from .galgame_web.utils import (
    DEFAULT_EMOTION_TAGS,
    DEFAULT_GALGAME_PROMPT,
    EMOTION_PATTERN,
    EXPRESSION_KEYS,
    PLUGIN_NAME,
    get_emotion_tags,
    extract_emotions,
    extract_all_emotions,
)
from .galgame_web.assets_helpers import (
    IMAGE_EXTS,
    MAX_UPLOAD_BYTES,
    list_asset_files,
    resolve_assets,
    safe_path,
    register_asset,
)
from .galgame_web.session_helpers import (
    SESSIONS_DIR,
    PLATFORM_ID,
    build_umo,
    session_path,
    save_session,
    load_session,
    load_all_sessions,
    gc_sessions,
    init_astrbot_conv,
    sync_conv_to_db,
    delete_astrbot_conv,
    sync_sessions_to_db,
    cleanup_session_audio,
    gc_audio_files,
)
from .galgame_web.web_handler import GalgameWebHandler

ASSETS_DIR = pathlib.Path("data/plugin_data") / PLUGIN_NAME / "assets"
AUDIO_DIR = pathlib.Path("data/plugin_data") / PLUGIN_NAME / "audio"
FAVORITES_PATH = pathlib.Path("data/plugin_data") / PLUGIN_NAME / "favorites.json"

_MIME_EXT = {"audio/wav": ".wav", "audio/mpeg": ".mp3", "audio/ogg": ".ogg", "audio/flac": ".flac", "audio/mp4": ".m4a"}


def _ext_for_mime(mime: str) -> str:
    return _MIME_EXT.get(mime, ".wav")


def _detect_audio_mime(raw: bytes) -> str:
    if len(raw) < 4:
        return "audio/wav"
    head = raw[:4]
    if head == b"RIFF":
        return "audio/wav"
    if head == b"OggS":
        return "audio/ogg"
    if head == b"fLaC":
        return "audio/flac"
    if head[:2] == b"\xff\xfb" or head[:2] == b"\xff\xf3" or head[:2] == b"\xff\xf2":
        return "audio/mpeg"
    if head == b"ID3\x03" or head == b"ID3\x02" or head == b"ID3\x04":
        return "audio/mpeg"
    if len(raw) >= 12 and raw[4:8] == b"ftyp":
        return "audio/mp4"
    return "audio/wav"


def _is_pure_json(text: str) -> bool:
    stripped = text.strip()
    if not stripped.startswith("{"):
        return False
    try:
        json.loads(stripped)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


def _convert_audio(wav_path: pathlib.Path) -> pathlib.Path | None:
    mp3_path = wav_path.with_suffix(".mp3")
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_path), "-b:a", "128k", str(mp3_path)],
            capture_output=True, timeout=10
        )
        if result.returncode == 0 and mp3_path.exists():
            wav_path.unlink()
            return mp3_path
    except Exception:
        pass
    logger.warning("[audio] ffmpeg conversion failed, keeping wav")
    return None


class GalgamePlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self._sessions: dict[str, dict] = {}
        self._web_server: ThreadingHTTPServer | None = None
        cfg = self.context.get_config()
        dashboard_cfg = cfg.get("dashboard", {}) if cfg else {}
        self._webchat_username = dashboard_cfg.get("username", "astrbot")
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self._migrate_old_assets()
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        gc_sessions(self._sessions, self.config, lambda sid: delete_astrbot_conv(self.context, self._webchat_username, sid))
        load_all_sessions(self._sessions)
        t = asyncio.ensure_future(
            sync_sessions_to_db(self.context, self._webchat_username, self.config, self._sessions, lambda sid: save_session(self._sessions, sid))
        )
        t.add_done_callback(lambda _t: logger.warning(f"sync_sessions_to_db failed: {_t.exception()}") if _t.exception() else None)
        gc_audio_files(self._sessions)

        web_port = int(self.config.get("web_port", 0) or 0)
        if web_port > 0:
            self._setup_proxy_auth()
            self._start_web_server(web_port)

        self._register_apis()

    def _register_apis(self):
        ctx = self.context
        pn = PLUGIN_NAME
        ctx.register_web_api(f"/{pn}/session/init", self._api_session_init, ["POST"], "Initialize or resume a galgame session")
        ctx.register_web_api(f"/{pn}/send", self._api_send, ["POST"], "Send a user message to the AI character")
        ctx.register_web_api(f"/{pn}/history", self._api_history, ["GET"], "Get conversation history")
        ctx.register_web_api(f"/{pn}/config", self._api_config, ["GET"], "Get plugin configuration")
        ctx.register_web_api(f"/{pn}/assets/list", self._api_assets_list, ["GET"], "List asset files")
        ctx.register_web_api(f"/{pn}/assets/upload", self._api_assets_upload, ["POST"], "Upload image files")
        ctx.register_web_api(f"/{pn}/assets/upload-key", self._api_assets_upload_key, ["POST"], "Upload image by key")
        ctx.register_web_api(f"/{pn}/assets/delete", self._api_assets_delete, ["POST"], "Delete an asset")
        ctx.register_web_api(f"/{pn}/assets/file", self._api_assets_file, ["GET"], "Serve an asset file")
        ctx.register_web_api(f"/{pn}/assets/batch", self._api_assets_batch, ["POST"], "Get base64 data for multiple assets")
        ctx.register_web_api(f"/{pn}/assets/copy", self._api_assets_copy, ["POST"], "Copy an asset")
        ctx.register_web_api(f"/{pn}/rapid_action", self._api_rapid_action, ["POST"], "Notify rapid click activity")
        ctx.register_web_api(f"/{pn}/assets/batch-delete", self._api_assets_batch_delete, ["POST"], "Batch delete assets")
        ctx.register_web_api(f"/{pn}/session/list", self._api_session_list, ["GET"], "List available sessions for recovery")
        ctx.register_web_api(f"/{pn}/session/delete", self._api_session_delete, ["POST"], "Delete a session and its AstrBot conversation")
        ctx.register_web_api(f"/{pn}/favorites/list", self._api_favorites_list, ["GET"], "List saved favorites")
        ctx.register_web_api(f"/{pn}/favorites/add", self._api_favorites_add, ["POST"], "Add a favorite")
        ctx.register_web_api(f"/{pn}/favorites/delete", self._api_favorites_delete, ["POST"], "Delete a favorite")

    # ---- standalone web server ----

    def _start_web_server(self, port: int):
        upstream_port = os.environ.get("DASHBOARD_PORT") or os.environ.get("ASTRBOT_DASHBOARD_PORT") or "6185"
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
                    "exp": datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7),
                }
                GalgameWebHandler.jwt_token = jwt.encode(payload, secret, algorithm="HS256")
                logger.info("Galgame proxy JWT generated successfully")
            else:
                logger.warning("Could not generate JWT for proxy: jwt_secret or username missing")
        except Exception as e:
            logger.warning(f"Failed to setup proxy auth: {e}")

    # ---- asset migration ----

    def _migrate_old_assets(self):
        old_dir = pathlib.Path(__file__).parent / "galgame_web" / "galgame" / "assets"
        if not old_dir.is_dir():
            return
        marker = ASSETS_DIR / ".migrated"
        if marker.exists():
            return
        existing = set(f.name for f in ASSETS_DIR.iterdir()) if ASSETS_DIR.is_dir() else set()
        count = 0
        for f in old_dir.iterdir():
            if not f.is_file() or f.suffix.lower() not in IMAGE_EXTS or f.name in existing:
                continue
            try:
                shutil.copy2(f, ASSETS_DIR / f.name)
                count += 1
            except OSError:
                pass
        if count:
            logger.info(f"Migrated {count} assets from old location to {ASSETS_DIR}")
        marker.touch()

    # ---- audio ----

    def _save_audio(self, audio_b64: str) -> str:
        if "," in audio_b64:
            audio_b64 = audio_b64.split(",", 1)[1]
        raw = base64.b64decode(audio_b64)
        audio_dir = pathlib.Path("data/temp")
        audio_dir.mkdir(parents=True, exist_ok=True)
        audio_path = audio_dir / f"galgame_audio_{uuid.uuid4().hex}.wav"
        with open(audio_path, "wb") as f:
            f.write(raw)
        logger.info(f"Saved voice audio: {audio_path} ({len(raw)} bytes)")
        return str(audio_path.resolve())

    # ---- llm hooks ----

    @filter.on_llm_request()
    async def _inject_galgame_rules(self, event: AstrMessageEvent, req: ProviderRequest) -> None:
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
    async def _capture_llm_response(self, event: AstrMessageEvent, resp: LLMResponse) -> None:
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
                clean, known, all_emotions = extract_all_emotions(comp.text, emotion_tags)
                if known:
                    session["_pending_emotions"] = known
                    session["_pending_all_emotions"] = all_emotions if all_emotions else known
                comp.text = clean

    def _build_tagged_text(self, text: str, emotions: list, emotion_map: dict) -> str:
        sorted_emos = sorted(emotions, key=lambda e: e[1])
        result_parts = []
        cursor = 0
        current_emotion = sorted_emos[0][0] if sorted_emos else "neutral"
        for emo_label, char_pos in sorted_emos:
            if char_pos < cursor:
                current_emotion = emo_label
                continue
            seg_text = text[cursor:char_pos].strip()
            if seg_text:
                fish_emo = emotion_map.get(current_emotion, current_emotion)
                result_parts.append(f"[{fish_emo}]{seg_text}")
            cursor = char_pos
            current_emotion = emo_label
        tail = text[cursor:].strip()
        if tail or not result_parts:
            fish_emo = emotion_map.get(current_emotion, current_emotion)
            result_parts.append(f"[{fish_emo}]{tail or text.strip()}")
        return "".join(result_parts)

    # ---- session API ----

    async def _api_session_init(self):
        try:
            data = await request.get_json() or {}
            resume_id = data.get("resume_id", "").strip()

            if resume_id and resume_id in self._sessions:
                s = self._sessions[resume_id]
                return {"session_id": resume_id, "current_emotion": s.get("current_emotion", "neutral")}

            if resume_id:
                s = load_session(resume_id)
                if s:
                    self._sessions[resume_id] = s
                    return {"session_id": resume_id, "current_emotion": s.get("current_emotion", "neutral")}

            sid = uuid.uuid4().hex
            session = {
                "umo": "",
                "conv_id": "",
                "history": [],
                "current_emotion": "neutral",
                "pending_rapid_clicks": 0,
                "_resp_event": asyncio.Event(),
                "_audio_event": asyncio.Event(),
                "created_at": time.time(),
                "_lock": asyncio.Lock(),
            }
            self._sessions[sid] = session
            try:
                await init_astrbot_conv(self.context, self._webchat_username, self.config, sid, session)
            except Exception:
                logger.exception(f"Failed to init conversation for {sid}")
            save_session(self._sessions, sid)
            return {"session_id": sid}
        except Exception:
            logger.exception("session/init failed")
            return {"error": "internal error"}, 500

    async def _api_history(self):
        sid = request.args.get("session_id", "")
        if not sid or sid not in self._sessions:
            return {"error": "invalid session_id"}, 400
        return {"messages": self._sessions[sid]["history"]}

    async def _api_session_list(self):
        sessions_list = []
        for path in SESSIONS_DIR.glob("*.json"):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            sid = path.stem
            history = data.get("history", [])
            last_msg = ""
            for msg in reversed(history):
                if msg.get("role") == "assistant" and msg.get("content"):
                    last_msg = msg["content"]
                    break
            sessions_list.append({
                "session_id": sid,
                "created_at": data.get("created_at", 0),
                "message_count": len(history),
                "last_message": last_msg[:80],
            })
        sessions_list.sort(key=lambda s: s["created_at"], reverse=True)
        return {"sessions": sessions_list}

    async def _api_session_delete(self):
        data = await request.get_json() or {}
        sid = data.get("session_id", "").strip()
        if not sid:
            return {"error": "session_id required"}, 400
        if sid in self._sessions:
            cleanup_session_audio(self._sessions[sid]["history"])
            await delete_astrbot_conv(self.context, self._webchat_username, sid)
            del self._sessions[sid]
        path = session_path(sid)
        if path.exists():
            path.unlink()
        return {"status": "ok"}

    # ---- config API ----

    async def _api_config(self):
        files = list_asset_files(ASSETS_DIR)
        resolved = resolve_assets(self.config, files)
        emotion_keys = get_emotion_tags(self.config)
        return {
            "sprite_mode": self.config.get("sprite_mode", "single"),
            "rapid_click_threshold": self.config.get("rapid_click_threshold", 5),
            "rapid_window_seconds": self.config.get("rapid_window_seconds", 3),
            "tts_provider": self.config.get("tts_provider", ""),
            "expressions": resolved["expressions"],
            "expressions_blink": resolved.get("expressions_blink", {}),
            "emotion_keys": emotion_keys,
            "layers": resolved["layers"],
            "vrm_model": self.config.get("vrm_model", "") or resolved.get("vrm_model", ""),
            "character_name": self.config.get("character_name", ""),
            "background": resolved["background"],
            "sprite_scale": self.config.get("sprite_scale", 1.0),
            "sprite_bottom": self.config.get("sprite_bottom", 28.0),
            "sprite_left": self.config.get("sprite_left", 50.0),
            "typewriter_speed": self.config.get("typewriter_speed", 60),
            "history_avatar": self.config.get("history_avatar", ""),
        }

    # ---- asset APIs ----

    async def _api_assets_list(self):
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        entries = [{"name": f.name} for f in sorted(ASSETS_DIR.iterdir()) if f.is_file() and f.suffix.lower() in IMAGE_EXTS]
        return {"files": entries}

    async def _api_assets_upload(self):
        data = await request.get_json() or {}
        files_data = data.get("files", [])
        logger.info(f"[assets] upload received {len(files_data)} items")
        if not files_data:
            return {"error": "no files"}, 400
        uploaded = []
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        for f in files_data:
            name, b64 = f.get("name", ""), f.get("data", "")
            if not name or not b64:
                continue
            if "," in b64:
                b64 = b64.split(",", 1)[1]
            if len(b64) > MAX_UPLOAD_BYTES * 2:
                continue
            sp = safe_path(name, ASSETS_DIR)
            if not sp or sp.suffix.lower() not in IMAGE_EXTS:
                continue
            try:
                raw = base64.b64decode(b64)
                if len(raw) > MAX_UPLOAD_BYTES:
                    continue
                sp.write_bytes(raw)
                uploaded.append(sp.name)
                logger.info(f"Uploaded asset: {sp.name}")
            except Exception as e:
                logger.warning(f"Failed to save {name}: {e}")
        if not uploaded:
            return {"error": "no valid image files uploaded"}, 400
        return {"uploaded": uploaded}

    async def _api_assets_upload_key(self):
        data = await request.get_json() or {}
        key = data.get("key", "").strip()
        b64 = data.get("data", "")
        if not key or not b64:
            return {"error": "key and data required"}, 400
        if "," in b64:
            prefix, b64 = b64.split(",", 1)
            ext_map = {"jpeg": ".jpg", "jpg": ".jpg", "webp": ".webp", "bmp": ".bmp", "gif": ".gif"}
            mime_ext = ".png"
            for tag, ext in ext_map.items():
                if tag in prefix:
                    mime_ext = ext
                    break
            name = f"{key}{mime_ext}"
        else:
            name = f"{key}.png"
        if len(b64) > MAX_UPLOAD_BYTES * 2:
            return {"error": "file too large"}, 400
        sp = safe_path(name, ASSETS_DIR)
        if not sp or sp.suffix.lower() not in IMAGE_EXTS:
            return {"error": "unsupported extension"}, 400
        try:
            raw = base64.b64decode(b64)
            if len(raw) > MAX_UPLOAD_BYTES:
                return {"error": "file too large"}, 400
            ASSETS_DIR.mkdir(parents=True, exist_ok=True)
            sp.write_bytes(raw)
            logger.info(f"Uploaded key asset: {sp.name}")
            register_asset(self.config, key, sp.name, ASSETS_DIR)
            return {"uploaded": sp.name}
        except Exception as e:
            return {"error": str(e)}, 500

    async def _api_assets_delete(self):
        data = await request.get_json() or {}
        filename = data.get("filename", "")
        if not filename:
            return {"error": "no filename"}, 400
        sp = safe_path(filename, ASSETS_DIR)
        if not sp or not sp.exists() or not sp.is_file():
            return {"error": "file not found"}, 404
        sp.unlink()
        logger.info(f"Deleted asset: {sp.name}")
        return {"deleted": sp.name}

    async def _api_assets_file(self):
        filename = request.args.get("name", "")
        sp = safe_path(filename, ASSETS_DIR)
        if not sp or not sp.exists() or not sp.is_file():
            return {"error": "file not found"}, 404
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".bmp": "image/bmp", ".gif": "image/gif"}
        return Response(sp.read_bytes(), content_type=mime_map.get(sp.suffix.lower(), "application/octet-stream"))

    async def _api_assets_batch(self):
        data = await request.get_json() or {}
        names = data.get("names", [])
        if not names:
            return {"error": "no names"}, 400
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp", ".bmp": "image/bmp", ".gif": "image/gif"}
        result = []
        for name in names:
            sp = safe_path(name, ASSETS_DIR)
            if not sp or not sp.exists() or not sp.is_file():
                continue
            try:
                if sp.stat().st_size > MAX_UPLOAD_BYTES:
                    continue
                raw = sp.read_bytes()
                b64 = base64.b64encode(raw).decode()
                mt = mime_map.get(sp.suffix.lower(), "image/png")
                result.append({"name": sp.name, "data": f"data:{mt};base64,{b64}"})
            except Exception as e:
                logger.warning(f"[assets] batch read failed {name}: {e}")
        return {"files": result}

    async def _api_assets_copy(self):
        data = await request.get_json() or {}
        source = data.get("source", "").strip()
        dest_key = data.get("key", "").strip()
        if not source or not dest_key:
            return {"error": "source and key required"}, 400
        sp = safe_path(source, ASSETS_DIR)
        if not sp or not sp.is_file():
            return {"error": "source not found"}, 404
        if sp.suffix.lower() not in IMAGE_EXTS:
            return {"error": "unsupported extension"}, 400
        dest_name = f"{dest_key}{sp.suffix.lower()}"
        dp = safe_path(dest_name, ASSETS_DIR)
        if not dp or dp.suffix.lower() not in IMAGE_EXTS:
            return {"error": "invalid destination"}, 400
        try:
            ASSETS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sp, dp)
            logger.info(f"Copied asset: {source} -> {dp.name}")
            register_asset(self.config, dest_key, dp.name, ASSETS_DIR)
            return {"copied": dp.name, "source": source}
        except OSError as e:
            return {"error": str(e)}, 500

    async def _api_assets_batch_delete(self):
        data = await request.get_json() or {}
        filenames = data.get("filenames", [])
        if not filenames:
            return {"error": "no filenames"}, 400
        deleted = []
        for name in filenames:
            sp = safe_path(name, ASSETS_DIR)
            if sp and sp.is_file():
                sp.unlink()
                deleted.append(name)
        logger.info(f"Batch deleted {len(deleted)} assets")
        return {"deleted": deleted}

    # ---- pipeline ----

    async def _push_through_pipeline(self, text: str, session_id: str, audio_path: str = "") -> dict:
        t0 = time.time()
        msg_id = str(uuid.uuid4())
        wc_sid = f"webchat!{self._webchat_username}!{session_id}"
        logger.info(f"[pipeline] start msg_id={msg_id[:8]} sid={session_id[:8]} text={text[:40]} audio={'yes' if audio_path else 'no'}")
        back_queue = webchat_queue_mgr.get_or_create_back_queue(msg_id, wc_sid)
        parts = []
        if audio_path:
            parts.append({"type": "record", "path": audio_path})
        if text:
            parts.append({"type": "plain", "text": text})
        payload = {"message": parts, "message_id": msg_id, "selected_provider": None, "selected_model": None, "enable_streaming": False}
        t1 = time.time()
        chat_queue = webchat_queue_mgr.get_or_create_queue(session_id)
        await chat_queue.put((self._webchat_username, session_id, payload))
        logger.info(f"[pipeline] pushed to chat_queue (setup={t1 - t0:.3f}s)")
        collected = []
        audio_b64 = ""
        audio_mime = ""
        audio_file = ""
        first = True
        try:
            while True:
                result = await asyncio.wait_for(back_queue.get(), timeout=120)
                if first:
                    logger.info(f"[pipeline] first resp after {(time.time() - t1) * 1000:.0f}ms")
                    first = False
                mtype = result.get("type", "")
                dtext = result.get("data", "")
                if mtype == "end":
                    break
                elif mtype == "record":
                    record_file = dtext.replace("[RECORD]", "").strip()
                    if record_file:
                        record_path = pathlib.Path(get_astrbot_data_path()) / "attachments" / record_file
                        if record_path.exists():
                            raw = record_path.read_bytes()
                            audio_b64 = base64.b64encode(raw).decode()
                            audio_mime = _detect_audio_mime(raw)
                            AUDIO_DIR.mkdir(parents=True, exist_ok=True)
                            audio_file = f"{uuid.uuid4().hex}{_ext_for_mime(audio_mime)}"
                            (AUDIO_DIR / audio_file).write_bytes(raw)
                            logger.info(f"[pipeline] captured audio: {record_file} ({len(raw)} bytes, {audio_mime})")
                elif mtype in ("plain", "complete"):
                    if dtext and not _is_pure_json(dtext):
                        collected.append(dtext)
        except asyncio.TimeoutError:
            logger.warning(f"[pipeline] TIMEOUT after 120s")
        finally:
            webchat_queue_mgr.remove_back_queue(msg_id)
        result_text = "".join(collected).strip()
        logger.info(f"[pipeline] returning text_len={len(result_text)} audio={'yes' if audio_b64 else 'no'}")
        return {"text": result_text, "audio": audio_b64, "audio_mime": audio_mime, "audio_file": audio_file}

    async def _api_send(self):
        data = await request.get_json() or {}
        if not isinstance(data, dict) or not data:
            return {"error": "no data"}, 400
        sid = data.get("session_id", "")
        text = data.get("text", "").strip()
        audio_data = data.get("audio_data", "")
        if not sid or sid not in self._sessions:
            return {"error": "invalid session_id"}, 400

        session = self._sessions[sid]

        async with session["_lock"]:
            rapid_count = session.pop("pending_rapid_clicks", 0)
            conv_id = session.get("conv_id", "")

        if rapid_count > 0 and not text and not audio_data:
            text = "(戳了戳)"
        elif not text and not audio_data:
            return {"error": "empty text"}, 400

        audio_path = ""
        if audio_data:
            try:
                audio_path = self._save_audio(audio_data)
            except Exception as e:
                logger.warning(f"Failed to save audio: {e}")
                if not text:
                    return {"error": "语音处理失败，请重试"}, 500

        cfg = self.context.get_config()
        wake_prefixes = cfg.get("wake_prefix", ["/"])
        matched_prefix = next((p for p in wake_prefixes if text.startswith(p)), None)
        cmd = ""
        if matched_prefix:
            cmd = text[len(matched_prefix):].strip().split()[0].lower() if text[len(matched_prefix):].strip() else ""
            if cmd in ("reset", "new", "del"):
                async with session["_lock"]:
                    session["history"] = []
                    session["current_emotion"] = "neutral"
                save_session(self._sessions, sid)

        pipeline_text = text
        try:
            t_pipe = time.time()
            pipeline_result = await self._push_through_pipeline(pipeline_text, sid, audio_path)
            raw_reply = pipeline_result["text"]
            audio_b64 = pipeline_result.get("audio", "")
            logger.info(f"[perf] pipeline roundtrip: {time.time() - t_pipe:.2f}s")
        except Exception as e:
            logger.exception(f"[pipeline] push failed: {e}")
            return {"error": "回复生成失败"}, 500

        is_command = bool(matched_prefix and cmd in ("new", "del", "reset"))
        if is_command:
            async with session["_lock"]:
                if cmd == "new":
                    new_cid = await self.context.conversation_manager.get_curr_conversation_id(session["umo"])
                    if new_cid:
                        session["conv_id"] = new_cid
                elif cmd == "del":
                    session["conv_id"] = ""
            save_session(self._sessions, sid)
            raw_reply = raw_reply.replace("\\n", "\n") if raw_reply else ""
            return {"reply": raw_reply or "", "emotion": "neutral", "emotions": [],
                    "audio": audio_b64, "audio_mime": pipeline_result.get("audio_mime", ""),
                    "audio_file": pipeline_result.get("audio_file", ""), "audio_segments": []}

        if not raw_reply and text.strip() and not matched_prefix:
            ev = session.get("_resp_event", asyncio.Event())
            ev.clear()
            try:
                await asyncio.wait_for(ev.wait(), timeout=120)
            except asyncio.TimeoutError:
                pass
            raw_reply = session.pop("_last_resp_text", "") or raw_reply

        raw_reply = raw_reply.replace("\\n", "\n")
        raw_reply = re.sub(r"\[IMAGE\][^\s]+", "", raw_reply)
        emotion_tags = get_emotion_tags(self.config)
        async with session["_lock"]:
            if not session.get("conv_id"):
                new_cid = await self.context.conversation_manager.get_curr_conversation_id(session["umo"])
                if new_cid:
                    session["conv_id"] = new_cid
            pending_emotions = session.pop("_pending_emotions", None)
            pending_all = session.pop("_pending_all_emotions", None)
        if pending_emotions:
            clean_text = raw_reply
            emotions = pending_emotions
            emotions_all = pending_all if pending_all else pending_emotions
            clean_text = re.sub(EMOTION_PATTERN, "", clean_text)
            clean_text = re.sub(r"\([a-z-]+\)", "", clean_text)
            clean_text = re.sub(r"<#\d+\.?\d*#>", "", clean_text).strip()
        else:
            clean_text, emotions, emotions_all = extract_all_emotions(raw_reply, emotion_tags)
        final_emotion = emotions[-1][0] if emotions else "neutral"

        tts_emotion_map = {}
        try:
            tts_emotion_map = json.loads(self.config.get("tts_emotion_map", "{}") or "{}")
        except (json.JSONDecodeError, TypeError):
            pass

        audio_segments = []
        audio_file = ""
        audio_mime_val = ""
        if emotions and clean_text:
            tts_provider_id = self.config.get("tts_provider", "").strip()
            if tts_provider_id:
                tts_provider = self.context.provider_manager.inst_map.get(tts_provider_id)
            else:
                tts_provider = self.context.get_using_tts_provider()
            if tts_provider:
                tagged_text = self._build_tagged_text(clean_text, emotions_all, tts_emotion_map)
                try:
                    t0_tts = time.time()
                    audio_path = await tts_provider.get_audio(tagged_text)
                    if audio_path:
                        raw = pathlib.Path(audio_path).read_bytes()
                        mime = _detect_audio_mime(raw)
                        audio_b64 = base64.b64encode(raw).decode()
                        audio_mime_val = mime
                        AUDIO_DIR.mkdir(parents=True, exist_ok=True)
                        audio_file = f"{uuid.uuid4().hex}{_ext_for_mime(mime)}"
                        (AUDIO_DIR / audio_file).write_bytes(raw)
                        if self.config.get("audio_format", "wav") == "mp3":
                            converted = _convert_audio(AUDIO_DIR / audio_file)
                            if converted:
                                audio_file = converted.name
                                raw = converted.read_bytes()
                                mime = "audio/mpeg"
                                audio_b64 = base64.b64encode(raw).decode()
                                audio_mime_val = mime
                        logger.info(f"[fishaudio_tts] synthesized {len(raw)} bytes, {mime} in {time.time() - t0_tts:.1f}s")
                    else:
                        logger.warning("[fishaudio_tts] TTS returned no audio")
                except Exception as e:
                    logger.warning(f"[fishaudio_tts] TTS failed: {e}")
            else:
                logger.warning("[fishaudio_tts] No TTS provider configured, skipping TTS")

        async with session["_lock"]:
            session["history"].append({"role": "user", "content": text})
            session["history"].append({"role": "assistant", "content": clean_text, "audio_file": audio_file, "audio_mime": audio_mime_val})
            session["current_emotion"] = final_emotion
            if len(session["history"]) > 40:
                session["history"] = session["history"][-40:]

        save_session(self._sessions, sid)

        character_name = self.config.get("character_name", "角色")
        try:
            await self.context.message_history_manager.insert(platform_id=PLATFORM_ID, user_id=conv_id, content={"type": "user", "message": text}, sender_id="user", sender_name="用户")
        except Exception as e:
            logger.warning(f"Failed to save user message to history: {e}")
        try:
            await self.context.message_history_manager.insert(platform_id=PLATFORM_ID, user_id=conv_id, content={"type": "bot", "message": clean_text}, sender_id="bot", sender_name=character_name)
        except Exception as e:
            logger.warning(f"Failed to save bot message to history: {e}")

        try:
            await sync_conv_to_db(self.context, session)
        except Exception as e:
            logger.warning(f"Failed to sync conversation to DB: {e}")

        return {"reply": clean_text, "emotion": final_emotion, "emotions": [[emo, pos] for emo, pos in emotions], "audio": audio_b64, "audio_mime": audio_mime_val, "audio_file": audio_file, "audio_segments": []}

    def _load_favorites(self) -> list[dict]:
        if not FAVORITES_PATH.exists():
            return []
        try:
            return json.loads(FAVORITES_PATH.read_text(encoding="utf-8")) or []
        except (OSError, json.JSONDecodeError):
            return []

    def _save_favorites(self, favs: list[dict]):
        FAVORITES_PATH.parent.mkdir(parents=True, exist_ok=True)
        FAVORITES_PATH.write_text(json.dumps(favs, ensure_ascii=False, indent=2), encoding="utf-8")

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
        favs.insert(0, {
            "id": uuid.uuid4().hex,
            "text": text,
            "audio_file": audio_file,
            "audio_mime": audio_mime,
            "saved_at": time.time(),
        })
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

    async def _api_rapid_action(self):
        data = await request.get_json()
        if not data:
            return {"error": "no data"}, 400
        sid = data.get("session_id", "")
        count = data.get("count", 0)
        if sid in self._sessions:
            async with self._sessions[sid]["_lock"]:
                self._sessions[sid]["pending_rapid_clicks"] = count
        return {"status": "ok"}

    @filter.command("galgame")
    async def cmd_galgame(self, event: AstrMessageEvent) -> MessageEventResult:
        web_port = int(self.config.get("web_port", 0) or 0)
        url = f"http://localhost:{web_port}" if web_port > 0 else "（未启用独立 WebUI，请在插件设置中设置 web_port）"
        yield event.plain_result("AI Galgame 虚拟伙伴\n\n" f"浏览器访问：{url}")

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
