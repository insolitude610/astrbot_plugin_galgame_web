import asyncio
import base64
import json
import os
import pathlib
import re
import shutil
import time
import uuid

from quart import Response, request, make_response

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.star import Context, Star

PLUGIN_NAME = "astrbot_plugin_galgame_web"

DEFAULT_EMOTION_TAGS = ["neutral", "happy", "sad", "angry", "surprised", "blush", "thinking"]
EMOTION_PATTERN = re.compile(r"\[emotion:(\w+)\]")

def _get_emotion_tags(config: dict) -> list[str]:
    expressions = config.get("expressions", {})
    if not isinstance(expressions, dict):
        expressions = {}
    keys = [k for k in expressions if k]

    custom_raw = config.get("custom_emotions", "")
    if custom_raw and isinstance(custom_raw, str):
        try:
            custom = json.loads(custom_raw)
        except (json.JSONDecodeError, TypeError):
            custom = {}
        if isinstance(custom, dict):
            for k in custom:
                if k and k not in keys:
                    keys.append(k)

    if keys:
        return keys
    return list(DEFAULT_EMOTION_TAGS)

SESSIONS_DIR = pathlib.Path("data/plugin_data") / PLUGIN_NAME / "sessions"

ASSETS_DIR = pathlib.Path(__file__).parent / "pages" / "galgame" / "assets"
IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10MB per file

EXPRESSION_KEYS = ["neutral", "happy", "sad", "angry", "surprised", "blush", "thinking"]
LAYER_KEYS = ["body", "hair_back", "head", "hair_front", "mouth_open", "mouth_closed", "orb"]

PLATFORM_ID = "webchat"
GALGAME_UMO_PREFIX = "webchat!galgame!"


def _list_asset_files() -> list[str]:
    if not ASSETS_DIR.is_dir():
        return []
    return sorted(
        f.name
        for f in ASSETS_DIR.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS
    )


def _find_asset_for(label: str, files: list[str], prefix: str = "") -> str:
    label_lower = label.lower()
    # 1) exact prefix match: prefix_label
    if prefix:
        prefixed = f"{prefix}_{label_lower}"
        for fname in files:
            stem = pathlib.Path(fname).stem.lower()
            if stem == prefixed:
                return fname
    # 2) exact label match
    for fname in files:
        stem = pathlib.Path(fname).stem.lower()
        if stem == label_lower:
            return fname
    # 3) word-parts contains both prefix and label
    if prefix:
        prefix_lower = prefix.lower()
        for fname in files:
            stem = pathlib.Path(fname).stem.lower()
            parts = stem.split("_")
            if prefix_lower in parts and label_lower in parts:
                return fname
    # 4) substring fallback
    for fname in files:
        stem = pathlib.Path(fname).stem.lower()
        if label_lower in stem or stem in label_lower:
            return fname
    return ""


def _resolve_assets(config: dict, files: list[str]) -> dict:
    sprite_mode = config.get("sprite_mode", "single")

    background = config.get("background", "")
    if not background:
        background = _find_asset_for("background", files) or _find_asset_for("bg", files)

    expr_prefix = "single" if sprite_mode == "single" else "expr"
    expressions = {}
    raw_expr = config.get("expressions", {}) or {}
    for key in EXPRESSION_KEYS:
        val = raw_expr.get(key, "")
        if not val:
            val = _find_asset_for(key, files, expr_prefix)
        expressions[key] = val

    layers = {}
    raw_layers = config.get("layers", {}) or {}
    for key in LAYER_KEYS:
        val = raw_layers.get(key, "")
        if not val:
            val = _find_asset_for(key, files, "layer")
        layers[key] = val

    return {
        "background": background,
        "expressions": expressions,
        "layers": layers,
    }


def _safe_path(name: str, base_dir: pathlib.Path) -> pathlib.Path | None:
    stem = pathlib.Path(name).name
    if not stem or stem != name.split("/")[-1].split("\\")[-1]:
        return None
    resolved = (base_dir / stem).resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        return None
    return resolved


class GalgamePlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self._sessions: dict[str, dict] = {}
        self._active_sse: set[str] = set()
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self._gc_sessions()
        self._load_all_sessions()
        t = asyncio.ensure_future(self._sync_sessions_to_db())
        t.add_done_callback(lambda _t: logger.warning(f"sync_sessions_to_db failed: {_t.exception()}") if _t.exception() else None)

        context.register_web_api(
            f"/{PLUGIN_NAME}/session/init",
            self._api_session_init,
            ["POST"],
            "Initialize a new galgame session (or resume with replay_id)",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/send",
            self._api_send,
            ["POST"],
            "Send a user message to the AI character",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/stream",
            self._api_stream,
            ["GET"],
            "SSE endpoint for receiving AI responses and emotions",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/config",
            self._api_config,
            ["GET"],
            "Get plugin configuration for the frontend",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/assets/list",
            self._api_assets_list,
            ["GET"],
            "List available image files in the assets directory",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/assets/upload",
            self._api_assets_upload,
            ["POST"],
            "Upload image files to the assets directory",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/assets/upload-key",
            self._api_assets_upload_key,
            ["POST"],
            "Upload an image and save with a fixed key name (e.g. happy.png)",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/assets/delete",
            self._api_assets_delete,
            ["POST"],
            "Delete an image file from the assets directory",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/assets/file",
            self._api_assets_file,
            ["GET"],
            "Serve an image file from the assets directory",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/assets/batch",
            self._api_assets_batch,
            ["POST"],
            "Get base64 data for multiple asset files",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/assets/copy",
            self._api_assets_copy,
            ["POST"],
            "Copy an existing asset to a new key name",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/rapid_action",
            self._api_rapid_action,
            ["POST"],
            "Notify rapid click/keyboard activity",
        )
        context.register_web_api(
            f"/{PLUGIN_NAME}/page/<path:filename>",
            self._api_page_serve,
            ["GET"],
            "Serve standalone web UI static files",
        )

    # ---- persistence helpers ----

    def _register_asset(self, key: str, filename: str):
        """Update self.config and remove old non-prefixed conflicting files."""
        if "_" not in key:
            return
        parts = key.split("_", 1)
        prefix, base = parts[0], parts[1]
        try:
            if prefix in ("single", "expr") and base in EXPRESSION_KEYS:
                if isinstance(self.config.get("expressions"), dict) and base in self.config["expressions"]:
                    self.config["expressions"][base] = filename
            elif prefix == "layer" and base in LAYER_KEYS:
                if isinstance(self.config.get("layers"), dict) and base in self.config["layers"]:
                    self.config["layers"][base] = filename
            elif prefix == "bg" and "background" in self.config:
                self.config["background"] = filename
        except Exception:
            logger.exception(f"_register_asset failed for key={key}")
        for ext in IMAGE_EXTS:
            old_path = ASSETS_DIR / f"{base}{ext}"
            if old_path.exists() and old_path.is_file() and old_path.name != filename:
                try:
                    old_path.unlink()
                    logger.info(f"Removed old non-prefixed file: {old_path.name}")
                except OSError:
                    pass

    def _build_umo(self, session_id: str) -> str:
        return f"{PLATFORM_ID}:FriendMessage:{GALGAME_UMO_PREFIX}{session_id}"

    async def _init_astrbot_conv(self, session_id: str, session: dict):
        umo = self._build_umo(session_id)
        persona_id = self.config.get("persona", "") or None
        try:
            conv_id = await self.context.conversation_manager.new_conversation(
                unified_msg_origin=umo,
                platform_id=PLATFORM_ID,
                content=session.get("history", []),
                persona_id=persona_id,
            )
            session["umo"] = umo
            session["conv_id"] = conv_id
        except Exception as e:
            logger.warning(f"Failed to create AstrBot conversation for {session_id}: {e}")

    async def _sync_conv_to_db(self, session: dict):
        umo = session.get("umo")
        conv_id = session.get("conv_id")
        history = session.get("history", [])
        if not umo or not conv_id:
            return
        try:
            await self.context.conversation_manager.update_conversation(
                unified_msg_origin=umo,
                conversation_id=conv_id,
                history=history,
            )
        except Exception as e:
            logger.warning(f"Failed to sync conversation to DB: {e}")

    async def _delete_astrbot_conv(self, session_id: str):
        umo = self._build_umo(session_id)
        try:
            await self.context.conversation_manager.delete_conversations_by_user_id(umo)
        except Exception as e:
            logger.warning(f"Failed to delete AstrBot conversation for {session_id}: {e}")

    def _session_path(self, session_id: str) -> pathlib.Path:
        return SESSIONS_DIR / f"{session_id}.json"

    def _save_session(self, session_id: str):
        session = self._sessions.get(session_id)
        if not session:
            return
        data = {
            "umo": session.get("umo", ""),
            "conv_id": session.get("conv_id", ""),
            "history": session["history"],
            "current_emotion": session["current_emotion"],
            "created_at": session["created_at"],
        }
        try:
            with open(self._session_path(session_id), "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except OSError as e:
            logger.warning(f"Failed to save session {session_id}: {e}")

    def _load_session(self, session_id: str) -> dict | None:
        path = self._session_path(session_id)
        if not path.exists():
            return None
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return {
                "umo": data.get("umo", ""),
                "conv_id": data.get("conv_id", ""),
                "history": data.get("history", []),
                "current_emotion": data.get("current_emotion", "neutral"),
                "pending_rapid_clicks": 0,
                "sse_queue": asyncio.Queue(),
                "created_at": data.get("created_at", time.time()),
                "_lock": asyncio.Lock(),
            }
        except (OSError, json.JSONDecodeError) as e:
            logger.warning(f"Failed to load session {session_id}: {e}")
            return None

    def _load_all_sessions(self):
        count = 0
        for path in SESSIONS_DIR.glob("*.json"):
            sid = path.stem
            if sid in self._sessions:
                continue
            session = self._load_session(sid)
            if session:
                self._sessions[sid] = session
                count += 1
        if count:
            logger.info(f"Loaded {count} persisted sessions")

    async def _sync_sessions_to_db(self):
        for sid, session in list(self._sessions.items()):
            if not session.get("conv_id"):
                await self._init_astrbot_conv(sid, session)
                self._save_session(sid)
            else:
                try:
                    await self.context.conversation_manager.get_conversation(
                        unified_msg_origin=session["umo"],
                        conversation_id=session["conv_id"],
                        create_if_not_exists=True,
                    )
                except Exception as e:
                    logger.warning(f"Failed to ensure conversation exists for {sid}: {e}")

    def _gc_sessions(self):
        retain_days = self.config.get("session_retain_days", 7)
        if retain_days <= 0:
            return
        now = time.time()
        ttl = retain_days * 86400
        removed = 0
        for path in SESSIONS_DIR.glob("*.json"):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if now - data.get("created_at", 0) > ttl:
                    path.unlink()
                    removed += 1
                    sid = path.stem
                    asyncio.ensure_future(self._delete_astrbot_conv(sid))
            except (OSError, json.JSONDecodeError):
                pass
        if removed:
            logger.info(f"GC removed {removed} expired sessions")

    def _get_config_tts_provider(self):
        prov_id = self.config.get("tts_provider", "")
        if not prov_id:
            return None
        return self.context.get_provider_by_id(prov_id)

    def _build_system_prompt(self):
        persona_id = self.config.get("persona", "")
        persona_prompt = ""
        if persona_id:
            persona = self.context.persona_manager.get_persona(persona_id)
            if persona:
                persona_prompt = persona.system_prompt

        extra = self.config.get("system_prompt_extra", "")
        emotion_tags = _get_emotion_tags(self.config)
        emotions = ", ".join(emotion_tags)

        prompt = f"""{persona_prompt}

回复规则：
1. 用口语化、亲切的中文回复，像朋友聊天一样自然
2. 回复长度控制在 1-4 句话，不要过长
3. 回复末尾必须加上情绪标签，格式为 [emotion:xxx]
   可选情绪：{emotions}
   根据对话内容选择最贴合当前心情的情绪标签
4. 不要在标签前后加任何多余文字
5. 你的回复中不应包含括号中的心理活动描写，直接说话即可"""

        if extra:
            prompt += f"\n\n{extra}"

        return prompt

    async def _api_session_init(self):
        try:
            data = await request.get_json() or {}
            resume_id = data.get("resume_id", "").strip()

            if resume_id and resume_id in self._sessions:
                return {"session_id": resume_id}

            if resume_id:
                session = self._load_session(resume_id)
                if session:
                    self._sessions[resume_id] = session
                    return {"session_id": resume_id}

            session_id = uuid.uuid4().hex
            session = {
                "umo": "",
                "conv_id": "",
                "history": [],
                "current_emotion": "neutral",
                "pending_rapid_clicks": 0,
                "sse_queue": asyncio.Queue(),
                "created_at": time.time(),
                "_lock": asyncio.Lock(),
            }
            self._sessions[session_id] = session
            try:
                await self._init_astrbot_conv(session_id, session)
            except Exception:
                logger.exception(f"Failed to init conversation for {session_id}")
            try:
                self._save_session(session_id)
            except Exception:
                logger.exception(f"Failed to save session {session_id}")
            return {"session_id": session_id}
        except Exception:
            logger.exception("session/init failed")
            return {"error": "internal error"}, 500

    async def _api_send(self):
        data = await request.get_json()
        if not data:
            return {"error": "no data"}, 400

        session_id = data.get("session_id", "")
        text = data.get("text", "").strip()

        if not session_id or session_id not in self._sessions:
            return {"error": "invalid session_id"}, 400
        if not text:
            return {"error": "empty text"}, 400

        session = self._sessions[session_id]
        queue = session["sse_queue"]

        async with session["_lock"]:
            rapid_count = session.pop("pending_rapid_clicks", 0)
            messages = list(session["history"])
            messages.append({"role": "user", "content": text})
            conv_id = session.get("conv_id", "")

        rapid_hint = ""
        if rapid_count > 0:
            rapid_hint = (
                f"\n\n（用户刚才在短时间内快速点击了{rapid_count}次鼠标或按键，"
                f"可能心情烦躁或着急，请关心一下ta怎么了）"
            )

        system_prompt = self._build_system_prompt() + rapid_hint

        try:
            await self.context.message_history_manager.insert(
                platform_id=PLATFORM_ID,
                user_id=conv_id,
                content={"type": "user", "message": text},
                sender_id="user",
                sender_name="用户",
            )
        except Exception as e:
            logger.warning(f"Failed to save user message to history: {e}")

        has_active = session_id in self._active_sse

        try:
            llm_prov_id = self.config.get("llm_provider", "")
            if not llm_prov_id:
                if has_active:
                    await queue.put({"type": "error", "message": "未配置对话模型，请在插件设置中选择 LLM Provider"})
                return {"status": "ok"}

            from astrbot.core.agent.message import (
                AssistantMessageSegment,
                UserMessageSegment,
                TextPart,
            )

            contexts = []
            for msg in messages:
                if msg["role"] == "user":
                    contexts.append(UserMessageSegment(content=[TextPart(text=msg["content"])]))
                elif msg["role"] == "assistant":
                    contexts.append(AssistantMessageSegment(content=[TextPart(text=msg["content"])]))

            resp = await self.context.llm_generate(
                chat_provider_id=llm_prov_id,
                system_prompt=system_prompt,
                contexts=contexts,
            )

            full_text = resp.completion_text or ""

            emotion_match = EMOTION_PATTERN.search(full_text)
            emotion_tags = _get_emotion_tags(self.config)
            current_emotion = "neutral"
            if emotion_match:
                tag = emotion_match.group(1).lower()
                if tag in emotion_tags:
                    current_emotion = tag

            clean_text = EMOTION_PATTERN.sub("", full_text).strip()

            async with session["_lock"]:
                session["history"].append({"role": "user", "content": text})
                session["history"].append({"role": "assistant", "content": clean_text})
                session["current_emotion"] = current_emotion
                if len(session["history"]) > 40:
                    session["history"] = session["history"][-40:]

            self._save_session(session_id)

            character_name = self.config.get("character_name", "角色")
            try:
                await self.context.message_history_manager.insert(
                    platform_id=PLATFORM_ID,
                    user_id=conv_id,
                    content={"type": "bot", "message": clean_text},
                    sender_id="bot",
                    sender_name=character_name,
                )
            except Exception as e:
                logger.warning(f"Failed to save bot message to history: {e}")

            try:
                await self._sync_conv_to_db(session)
            except Exception as e:
                logger.warning(f"Failed to sync conversation to DB: {e}")

            if has_active:
                await queue.put({"type": "emotion", "value": current_emotion})

                chunk_size = 3
                for i in range(0, len(clean_text), chunk_size):
                    chunk = clean_text[i : i + chunk_size]
                    await queue.put({"type": "text", "value": chunk})

                tts_prov = self._get_config_tts_provider()
                if tts_prov:
                    try:
                        audio_path = await tts_prov.get_audio(clean_text)
                        if audio_path and os.path.exists(audio_path):
                            with open(audio_path, "rb") as f:
                                audio_b64 = base64.b64encode(f.read()).decode()
                            await queue.put({"type": "audio", "value": audio_b64})
                            try:
                                os.remove(audio_path)
                            except OSError:
                                pass
                    except Exception as e:
                        logger.warning(f"TTS generation failed: {e}")

                await queue.put({"type": "end"})

        except Exception as e:
            logger.exception(f"Error processing message: {e}")
            if has_active:
                await queue.put({"type": "error", "message": f"处理消息时出错: {e}"})

        return {"status": "ok"}

    async def _api_stream(self):
        session_id = request.args.get("session_id", "")
        if not session_id or session_id not in self._sessions:

            async def error_stream():
                yield f"event: error\ndata: {json.dumps({'message': 'invalid session_id'})}\n\n"

            return Response(error_stream(), content_type="text/event-stream")

        self._active_sse.add(session_id)
        session = self._sessions[session_id]
        queue = session["sse_queue"]

        async def event_stream():
            try:
                while True:
                    try:
                        msg = await asyncio.wait_for(queue.get(), timeout=25)
                        yield f"event: message\ndata: {json.dumps(msg, ensure_ascii=False)}\n\n"
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
            finally:
                self._active_sse.discard(session_id)
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break

        return Response(
            event_stream(),
            content_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def _api_config(self):
        files = _list_asset_files()
        resolved = _resolve_assets(self.config, files)
        emotion_keys = _get_emotion_tags(self.config)
        return {
            "sprite_mode": self.config.get("sprite_mode", "single"),
            "rapid_click_threshold": self.config.get("rapid_click_threshold", 5),
            "rapid_window_seconds": self.config.get("rapid_window_seconds", 3),
            "tts_provider": self.config.get("tts_provider", ""),
            "expressions": resolved["expressions"],
            "emotion_keys": emotion_keys,
            "layers": resolved["layers"],
            "character_name": self.config.get("character_name", ""),
            "background": resolved["background"],
        }

    async def _api_assets_list(self):
        entries = []
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        for f in sorted(ASSETS_DIR.iterdir()):
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS:
                entries.append({"name": f.name})
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
            name = f.get("name", "")
            b64_data = f.get("data", "")
            if not name or not b64_data:
                continue
            if "," in b64_data:
                b64_data = b64_data.split(",", 1)[1]
            if len(b64_data) > MAX_UPLOAD_BYTES * 2:
                logger.warning(f"[assets] upload rejected oversize: {name}")
                continue
            safe_path = _safe_path(name, ASSETS_DIR)
            if not safe_path or safe_path.suffix.lower() not in IMAGE_EXTS:
                continue
            try:
                raw = base64.b64decode(b64_data)
                if len(raw) > MAX_UPLOAD_BYTES:
                    continue
                with open(safe_path, "wb") as fout:
                    fout.write(raw)
                uploaded.append(safe_path.name)
                logger.info(f"Uploaded asset: {safe_path.name}")
            except Exception as e:
                logger.warning(f"Failed to save {name}: {e}")
        if not uploaded:
            return {"error": "no valid image files uploaded"}, 400
        return {"uploaded": uploaded}

    async def _api_assets_upload_key(self):
        """Upload a single image and save as {key}.{ext}. Automatically deduces extension."""
        data = await request.get_json() or {}
        key = data.get("key", "").strip()
        b64_data = data.get("data", "")
        if not key or not b64_data:
            return {"error": "key and data required"}, 400
        if "," in b64_data:
            # Strip data:image/xxx;base64, prefix
            prefix, b64_data = b64_data.split(",", 1)
            # Detect extension from MIME prefix
            mime_ext = ".png"
            if "jpeg" in prefix or "jpg" in prefix:
                mime_ext = ".jpg"
            elif "webp" in prefix:
                mime_ext = ".webp"
            elif "bmp" in prefix:
                mime_ext = ".bmp"
            elif "gif" in prefix:
                mime_ext = ".gif"
            name = f"{key}{mime_ext}"
        else:
            name = f"{key}.png"
        if len(b64_data) > MAX_UPLOAD_BYTES * 2:
            return {"error": "file too large"}, 400
        safe_path = _safe_path(name, ASSETS_DIR)
        if not safe_path or safe_path.suffix.lower() not in IMAGE_EXTS:
            return {"error": "unsupported extension"}, 400
        try:
            raw = base64.b64decode(b64_data)
            if len(raw) > MAX_UPLOAD_BYTES:
                return {"error": "file too large"}, 400
            ASSETS_DIR.mkdir(parents=True, exist_ok=True)
            with open(safe_path, "wb") as fout:
                fout.write(raw)
            logger.info(f"Uploaded key asset: {safe_path.name}")
            self._register_asset(key, safe_path.name)
            return {"uploaded": safe_path.name}
        except Exception as e:
            return {"error": str(e)}, 500

    async def _api_assets_delete(self):
        data = await request.get_json() or {}
        filename = data.get("filename", "")
        if not filename:
            return {"error": "no filename"}, 400
        safe_path = _safe_path(filename, ASSETS_DIR)
        if not safe_path or not safe_path.exists() or not safe_path.is_file():
            return {"error": "file not found"}, 404
        safe_path.unlink()
        logger.info(f"Deleted asset: {safe_path.name}")
        return {"deleted": safe_path.name}

    async def _api_assets_file(self):
        filename = request.args.get("name", "")
        safe_path = _safe_path(filename, ASSETS_DIR)
        if not safe_path or not safe_path.exists() or not safe_path.is_file():
            return {"error": "file not found"}, 404
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".webp": "image/webp", ".bmp": "image/bmp", ".gif": "image/gif"}
        content_type = mime_map.get(safe_path.suffix.lower(), "application/octet-stream")
        raw = safe_path.read_bytes()
        return Response(raw, content_type=content_type)

    async def _api_assets_batch(self):
        data = await request.get_json() or {}
        names = data.get("names", [])
        logger.info(f"[assets] batch requested: {names}")
        if not names:
            return {"error": "no names"}, 400
        mime_map = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                    ".webp": "image/webp", ".bmp": "image/bmp", ".gif": "image/gif"}
        result = []
        for name in names:
            safe_path = _safe_path(name, ASSETS_DIR)
            if not safe_path or not safe_path.exists() or not safe_path.is_file():
                logger.warning(f"[assets] batch skip missing: {name}")
                continue
            try:
                if safe_path.stat().st_size > MAX_UPLOAD_BYTES:
                    logger.warning(f"[assets] batch skip oversize: {safe_path.name}")
                    continue
                raw = safe_path.read_bytes()
                b64 = base64.b64encode(raw).decode()
                mt = mime_map.get(safe_path.suffix.lower(), "image/png")
                logger.info(f"[assets] batch encoded: {safe_path.name} size={len(raw)} b64_len={len(b64)}")
                result.append({"name": safe_path.name, "data": f"data:{mt};base64,{b64}"})
            except Exception as e:
                logger.warning(f"[assets] batch read failed {name}: {e}")
        logger.info(f"[assets] batch return {len(result)} files")
        return {"files": result}

    async def _api_assets_copy(self):
        data = await request.get_json() or {}
        source = data.get("source", "").strip()
        dest_key = data.get("key", "").strip()
        if not source or not dest_key:
            return {"error": "source and key required"}, 400
        src_path = _safe_path(source, ASSETS_DIR)
        if not src_path or not src_path.is_file():
            return {"error": "source not found"}, 404
        ext = src_path.suffix.lower()
        if ext not in IMAGE_EXTS:
            return {"error": "unsupported extension"}, 400
        dest_name = f"{dest_key}{ext}"
        dst_path = _safe_path(dest_name, ASSETS_DIR)
        if not dst_path or dst_path.suffix.lower() not in IMAGE_EXTS:
            return {"error": "invalid destination"}, 400
        try:
            ASSETS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src_path, dst_path)
            logger.info(f"Copied asset: {source} -> {dst_path.name}")
            self._register_asset(dest_key, dst_path.name)
            return {"copied": dst_path.name, "source": source}
        except OSError as e:
            return {"error": str(e)}, 500

    async def _api_rapid_action(self):
        data = await request.get_json()
        if not data:
            return {"error": "no data"}, 400

        session_id = data.get("session_id", "")
        count = data.get("count", 0)

        if session_id in self._sessions:
            async with self._sessions[session_id]["_lock"]:
                self._sessions[session_id]["pending_rapid_clicks"] = count

        return {"status": "ok"}

    async def _api_page_serve(self, filename: str):
        base_dir = pathlib.Path(__file__).parent / "pages" / "galgame"
        safe_path = _safe_path(filename, base_dir)
        if not safe_path or not safe_path.is_file():
            return await make_response("not found", 404)

        mime = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css",
            ".js": "text/javascript",
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
            ".json": "application/json",
        }
        content_type = mime.get(safe_path.suffix.lower(), "application/octet-stream")
        data = safe_path.read_bytes()
        return await make_response(data, {"Content-Type": content_type})

    @filter.command("galgame")
    async def cmd_galgame(self, event: AstrMessageEvent) -> MessageEventResult:
        yield event.plain_result(
            "AI Galgame 虚拟伙伴\n\n"
            "打开方式：\n"
            "浏览器访问 Dashboard 地址后追加：\n"
            f"/api/plug/{PLUGIN_NAME}/page/index.html\n\n"
            "或在 Dashboard 中：插件 → AI Galgame 虚拟伙伴 → Galgame 页面"
        )

    async def terminate(self):
        for sid in list(self._sessions.keys()):
            session = self._sessions[sid]
            self._active_sse.discard(sid)
            queue = session.get("sse_queue")
            if queue:
                while not queue.empty():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        break
            self._save_session(sid)
        self._sessions.clear()
