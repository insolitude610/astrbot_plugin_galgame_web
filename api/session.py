import asyncio
import json
import pathlib
import re
import time
import uuid

from quart import request

from astrbot.api import logger

from ..galgame_web import audio_utils, pipeline, tts

MAX_TEXT_CHARS = 20_000
MAX_SESSIONS = 200


class SessionAPI:
    def _register_session_apis(self):
        pn = self._plugin_name
        self.context.register_web_api(
            f"/{pn}/session/init",
            self._api_session_init,
            ["POST"],
            "Initialize or resume a galgame session",
        )
        self.context.register_web_api(
            f"/{pn}/send",
            self._api_send,
            ["POST"],
            "Send a user message to the AI character",
        )
        self.context.register_web_api(
            f"/{pn}/history", self._api_history, ["GET"], "Get conversation history"
        )
        self.context.register_web_api(
            f"/{pn}/session/list",
            self._api_session_list,
            ["GET"],
            "List available sessions for recovery",
        )
        self.context.register_web_api(
            f"/{pn}/session/delete",
            self._api_session_delete,
            ["POST"],
            "Delete a session and its AstrBot conversation",
        )
        self.context.register_web_api(
            f"/{pn}/rapid_action",
            self._api_rapid_action,
            ["POST"],
            "Notify rapid click activity",
        )

    # ---- session init ----

    @staticmethod
    def _find_latest_session() -> str | None:
        from ..galgame_web.session_helpers import SESSIONS_DIR, is_valid_session_id

        best_sid = None
        best_mtime = 0
        for path in SESSIONS_DIR.glob("*.json"):
            if not is_valid_session_id(path.stem):
                continue
            try:
                mtime = path.stat().st_mtime
                if mtime > best_mtime:
                    best_mtime = mtime
                    best_sid = path.stem
            except OSError:
                pass
        return best_sid

    def _find_blank_session(self) -> str | None:
        from ..galgame_web.session_helpers import SESSIONS_DIR, is_valid_session_id

        best_sid = None
        best_mtime = 0
        for path in SESSIONS_DIR.glob("*.json"):
            sid = path.stem
            if not is_valid_session_id(sid):
                continue
            try:
                in_memory = self._sessions.get(sid)
                if in_memory is not None:
                    send_lock = in_memory.get("_send_lock")
                    if (
                        in_memory.get("history")
                        or (send_lock is not None and send_lock.locked())
                        or in_memory.get("pending_rapid_clicks", 0) > 0
                    ):
                        continue
                    is_blank = True
                else:
                    with open(path, encoding="utf-8") as f:
                        data = json.load(f)
                    is_blank = isinstance(data, dict) and not data.get("history")
                if is_blank:
                    mtime = path.stat().st_mtime
                    if mtime > best_mtime:
                        best_mtime = mtime
                        best_sid = sid
            except (OSError, json.JSONDecodeError):
                pass
        return best_sid

    async def _api_session_init(self):
        init_lock = getattr(self, "_session_init_lock", None)
        if init_lock is None:
            init_lock = asyncio.Lock()
            self._session_init_lock = init_lock
        async with init_lock:
            return await self._api_session_init_serialized()

    async def _api_session_init_serialized(self):
        from ..galgame_web.session_helpers import (
            SESSIONS_DIR,
            is_valid_session_id,
            load_session,
            session_path,
        )

        try:
            data = await request.get_json() or {}
            if not isinstance(data, dict):
                return {"error": "invalid request"}, 400
            raw_resume_id = data.get("resume_id", "")
            if not isinstance(raw_resume_id, str):
                return {"error": "invalid resume_id"}, 400
            resume_id = raw_resume_id.strip()
            if resume_id and not is_valid_session_id(resume_id):
                return {"error": "invalid resume_id"}, 400
            force_new = data.get("force_new", False) is True

            in_mem = resume_id in self._sessions if resume_id else False
            on_disk = session_path(resume_id).exists() if resume_id else False
            logger.info(
                f"[session] init resume_id={resume_id} in_memory={in_mem} on_disk={on_disk} total_loaded={len(self._sessions)}"
            )

            if resume_id and resume_id in self._sessions:
                return {
                    "session_id": resume_id,
                    "current_emotion": self._sessions[resume_id].get(
                        "current_emotion", "neutral"
                    ),
                }

            if resume_id:
                s = load_session(resume_id)
                if s:
                    self._sessions[resume_id] = s
                    return {
                        "session_id": resume_id,
                        "current_emotion": s.get("current_emotion", "neutral"),
                    }

            if not force_new:
                latest = self._find_latest_session()
                if latest:
                    s = self._sessions.get(latest)
                    if s is None:
                        s = load_session(latest)
                    send_lock = s.get("_send_lock") if s else None
                    if s and (
                        s.get("history")
                        or (send_lock is not None and send_lock.locked())
                    ):
                        logger.info(f"[session] auto-resume latest: {latest}")
                        if latest not in self._sessions:
                            self._sessions[latest] = s
                        return {
                            "session_id": latest,
                            "current_emotion": s.get("current_emotion", "neutral"),
                        }

            # A forced new conversation may reuse an existing empty session. This
            # avoids accumulating blank, undeletable sessions on repeated clicks.
            blank_sid = self._find_blank_session()
            if blank_sid:
                s = self._sessions.get(blank_sid)
                if s is None:
                    s = load_session(blank_sid)
                if s:
                    if not s.get("umo"):
                        from ..galgame_web.session_helpers import build_umo

                        s["umo"] = build_umo(self._webchat_username, blank_sid)
                    logger.info(f"[session] reusing blank session: {blank_sid}")
                    if blank_sid not in self._sessions:
                        self._sessions[blank_sid] = s
                    return {
                        "session_id": blank_sid,
                        "current_emotion": s.get("current_emotion", "neutral"),
                    }

            session_count = sum(
                1
                for path in SESSIONS_DIR.glob("*.json")
                if is_valid_session_id(path.stem)
            )
            if session_count >= MAX_SESSIONS:
                return {"error": "session limit reached"}, 429

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
                "_send_lock": asyncio.Lock(),
            }
            self._sessions[sid] = session
            try:
                from ..galgame_web.session_helpers import build_umo

                session["umo"] = build_umo(self._webchat_username, sid)
            except Exception:
                logger.exception(f"Failed to build umo for {sid}")
            from ..galgame_web.session_helpers import save_session

            save_session(self._sessions, sid)
            return {"session_id": sid}
        except Exception:
            logger.exception("session/init failed")
            return {"error": "internal error"}, 500

    async def _api_history(self):
        from ..galgame_web.session_helpers import is_valid_session_id

        sid = request.args.get("session_id", "")
        if not is_valid_session_id(sid) or sid not in self._sessions:
            return {"error": "invalid session_id"}, 400
        return {"messages": self._sessions[sid]["history"]}

    async def _api_session_list(self):
        from ..galgame_web.session_helpers import SESSIONS_DIR, is_valid_session_id

        sessions_list = []
        for path in SESSIONS_DIR.glob("*.json"):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
            except (OSError, json.JSONDecodeError):
                continue
            sid = path.stem
            if not is_valid_session_id(sid) or not isinstance(data, dict):
                continue
            history = data.get("history", [])
            if not isinstance(history, list):
                continue
            last_msg = ""
            for msg in reversed(history):
                if not isinstance(msg, dict):
                    continue
                content = msg.get("content")
                if msg.get("role") == "assistant" and isinstance(content, str):
                    last_msg = content
                    break
            created_at = data.get("created_at", 0)
            if not isinstance(created_at, (int, float)):
                created_at = 0
            sessions_list.append(
                {
                    "session_id": sid,
                    "created_at": created_at,
                    "message_count": len(history),
                    "last_message": last_msg[:80],
                }
            )
        sessions_list.sort(key=lambda s: s["created_at"], reverse=True)
        return {"sessions": sessions_list}

    async def _api_session_delete(self):
        from ..galgame_web.session_helpers import (
            cleanup_unreferenced_audio,
            delete_astrbot_conv,
            is_valid_session_id,
            load_session,
            session_path,
        )

        data = await request.get_json() or {}
        if not isinstance(data, dict):
            return {"error": "invalid request"}, 400
        raw_sid = data.get("session_id", "")
        sid = raw_sid.strip() if isinstance(raw_sid, str) else ""
        if not is_valid_session_id(sid):
            return {"error": "invalid session_id"}, 400
        path = session_path(sid)
        if sid not in self._sessions and not path.exists():
            return {"error": "session not found"}, 404
        removed_history = []
        if sid in self._sessions:
            session = self._sessions[sid]
            send_lock = session.setdefault("_send_lock", asyncio.Lock())
            async with send_lock:
                removed_history = list(session.get("history", []))
                del self._sessions[sid]
        elif path.exists():
            stored = load_session(sid)
            if stored:
                removed_history = list(stored.get("history", []))
        if path.exists():
            path.unlink()
        cleanup_unreferenced_audio(removed_history, self._sessions)
        self._track_task(delete_astrbot_conv(self.context, self._webchat_username, sid))
        return {"status": "ok"}

    async def _api_rapid_action(self):
        from ..galgame_web.session_helpers import is_valid_session_id

        data = await request.get_json()
        if not isinstance(data, dict) or not data:
            return {"error": "no data"}, 400
        sid = data.get("session_id", "")
        count = data.get("count", 0)
        if not is_valid_session_id(sid) or sid not in self._sessions:
            return {"error": "invalid session_id"}, 400
        if not isinstance(count, int) or isinstance(count, bool):
            return {"error": "invalid count"}, 400
        if not self.config.get("rapid_click_enabled", True):
            return {"error": "rapid click disabled"}, 403
        threshold = self.config.get("rapid_click_threshold", 5)
        if not isinstance(threshold, int) or isinstance(threshold, bool):
            threshold = 5
        count = max(0, min(count, 1000))
        if count < max(1, threshold):
            return {"error": "rapid click threshold not reached"}, 400
        if sid in self._sessions:
            async with self._sessions[sid]["_lock"]:
                self._sessions[sid]["pending_rapid_clicks"] = max(
                    count,
                    self._sessions[sid].get("pending_rapid_clicks", 0),
                )
        return {"status": "ok"}

    # ---- message editing helpers ----

    def _edit_find_index(self, sid, message_id):
        session = self._sessions.get(sid)
        if not session:
            return None
        history = session.get("history", [])
        for i, msg in enumerate(history):
            if isinstance(msg, dict) and msg.get("id") == message_id:
                return i
        return None

    def _edit_truncate(self, sid, keep_n):
        """截断 history 到 keep_n 条，返回 (removed, coroutine)。

        调用方必须 await 返回的协程完成截断、落盘、DB 同步与音频回收。
        """
        from ..galgame_web.session_helpers import (
            cleanup_unreferenced_audio,
            save_session,
            sync_conv_to_db,
        )

        session = self._sessions[sid]
        removed = []

        async def _do():
            async with session["_lock"]:
                removed.extend(session["history"][keep_n:])
                session["history"] = session["history"][:keep_n]
            save_session(self._sessions, sid)
            try:
                await sync_conv_to_db(self.context, session)
            except Exception:
                pass
            cleanup_unreferenced_audio(removed, self._sessions)

        return removed, _do()

    # ---- _api_send broken into sub-steps ----

    async def _api_send(self):
        from ..galgame_web.session_helpers import is_valid_session_id

        if getattr(self, "_terminating", False):
            return {"error": "plugin is reloading"}, 503
        data = await request.get_json() or {}
        if not isinstance(data, dict) or not data:
            return {"error": "no data"}, 400
        sid = data.get("session_id", "")
        raw_text = data.get("text", "")
        audio_data = data.get("audio_data", "")
        if not is_valid_session_id(sid) or sid not in self._sessions:
            return {"error": "invalid session_id"}, 400
        if not isinstance(raw_text, str):
            return {"error": "text must be a string"}, 400
        if not isinstance(audio_data, str):
            return {"error": "audio_data must be a base64 string"}, 400
        text = raw_text.strip()
        if len(text) > MAX_TEXT_CHARS:
            return {"error": "message too long"}, 400
        try:
            audio_raw = audio_utils.decode_audio_data(audio_data) if audio_data else b""
        except ValueError as e:
            return {"error": str(e)}, 400

        active_tasks = getattr(self, "_active_send_tasks", None)
        if active_tasks is None:
            active_tasks = set()
            self._active_send_tasks = active_tasks
        current_task = asyncio.current_task()
        if current_task:
            active_tasks.add(current_task)
        try:
            session = self._sessions[sid]
            send_lock = session.setdefault("_send_lock", asyncio.Lock())
            async with send_lock:
                if getattr(self, "_terminating", False):
                    return {"error": "plugin is reloading"}, 503
                async with session["_lock"]:
                    rapid_count = session.get("pending_rapid_clicks", 0)
                    session["pending_rapid_clicks"] = 0
                if not text and not audio_raw:
                    if rapid_count <= 0:
                        return {"error": "text or audio required"}, 400
                    text = "(戳了戳)"
                return await self._do_send(sid, text, audio_raw)
        finally:
            if current_task:
                active_tasks.discard(current_task)

    async def _do_send(self, sid: str, text: str, audio_raw: bytes):
        """Core send logic, broken into sub-steps."""
        # Step 1: Parse input
        session = self._send_parse_input(sid)
        if isinstance(session, dict) and "error" in session:
            return session, 400

        response_event = session.get("_resp_event")
        if response_event:
            response_event.clear()
        session.pop("_last_resp_text", None)

        # Step 2: Handle commands
        matched_prefix, cmd = await self._send_handle_command(text, session, sid)

        # Step 3: Save audio if present
        audio_path = self._send_save_audio(audio_raw, text)
        user_audio_file = ""
        user_audio_mime = ""

        # Step 4: Run pipeline
        try:
            pipeline_result = await self._send_run_pipeline(text, sid, audio_path)
        finally:
            if audio_path:
                try:
                    pathlib.Path(audio_path).unlink(missing_ok=True)
                except OSError:
                    logger.warning(f"Failed to remove temporary audio: {audio_path}")
        if isinstance(pipeline_result, dict) and "error" in pipeline_result:
            return pipeline_result, 500

        if audio_raw:
            from ..galgame_web.session_helpers import AUDIO_DIR

            user_audio_mime = audio_utils.detect_audio_mime(audio_raw)
            user_audio_file = (
                f"{uuid.uuid4().hex}{audio_utils.ext_for_mime(user_audio_mime)}"
            )
            AUDIO_DIR.mkdir(parents=True, exist_ok=True)
            (AUDIO_DIR / user_audio_file).write_bytes(audio_raw)

        raw_reply = pipeline_result["text"]
        audio_b64 = pipeline_result.get("audio", "")

        # Step 5: Wait for LLM if needed (pipeline returned empty)
        if not raw_reply and text.strip() and not matched_prefix:
            raw_reply = await self._send_wait_for_llm(session, text)

        # Step 6: Check if command - return early
        is_command = bool(matched_prefix and cmd in ("new", "del", "reset"))
        if is_command:
            return await self._send_handle_command_result(
                cmd, session, sid, raw_reply, pipeline_result
            )

        # Step 7: Extract emotions
        clean_text, emotions, emotions_all = await self._send_extract_emotions(
            raw_reply, session
        )

        # Step 8: Synthesize TTS (use background result if available)
        _bg_task = session.pop("_bg_tts_task", None)
        logger.debug(
            f"[tts] bg_task={'yes' if _bg_task else 'no'} "
            f"text_len={len(clean_text)} emotion_count={len(emotions_all)}"
        )
        if _bg_task:
            await _bg_task
            audio_b64, audio_mime_val, audio_file = session.pop(
                "_bg_tts_result", ("", "", "")
            )
        else:
            audio_b64, audio_mime_val, audio_file = await self._send_synthesize_tts(
                clean_text, emotions_all, text, matched_prefix, audio_b64
            )

        # Step 9: Save and return
        return await self._send_save_and_return(
            session,
            text,
            clean_text,
            emotions,
            emotions_all,
            audio_b64,
            audio_mime_val,
            audio_file,
            sid,
            user_audio_file,
            user_audio_mime,
        )

    def _send_parse_input(self, sid):
        if not sid or sid not in self._sessions:
            return {"error": "invalid session_id"}
        session = self._sessions[sid]
        return session

    async def _send_handle_command(self, text, session, sid):
        cfg = self.context.get_config()
        wake_prefixes = cfg.get("wake_prefix", ["/"])
        matched_prefix = next((p for p in wake_prefixes if text.startswith(p)), None)
        cmd = ""
        if matched_prefix:
            cmd = (
                text[len(matched_prefix) :].strip().split()[0].lower()
                if text[len(matched_prefix) :].strip()
                else ""
            )
            if cmd in ("reset", "new", "del"):
                removed_history = []
                async with session["_lock"]:
                    removed_history = list(session.get("history", []))
                    session["history"] = []
                    session["current_emotion"] = "neutral"
                from ..galgame_web.session_helpers import (
                    cleanup_unreferenced_audio,
                    save_session,
                )

                if save_session(self._sessions, sid):
                    cleanup_unreferenced_audio(removed_history, self._sessions)
        return matched_prefix, cmd

    def _send_save_audio(self, audio_raw, text):
        audio_path = ""
        if audio_raw:
            try:
                audio_path = audio_utils.save_audio(audio_raw)
            except Exception as e:
                logger.warning(f"Failed to save audio: {e}")
                if not text:
                    raise
        return audio_path

    async def _send_run_pipeline(self, text, sid, audio_path):
        try:
            t_pipe = time.time()
            result = await pipeline.push_through_pipeline(
                self.config, self._webchat_username, sid, text, audio_path
            )
            logger.info(f"[perf] pipeline roundtrip: {time.time() - t_pipe:.2f}s")
            return result
        except Exception as e:
            logger.exception(f"[pipeline] push failed: {e}")
            return {"error": "回复生成失败"}

    async def _send_wait_for_llm(self, session, text):
        ready_text = session.pop("_last_resp_text", "")
        if ready_text:
            return ready_text
        ev = session.get("_resp_event", asyncio.Event())
        try:
            await asyncio.wait_for(ev.wait(), timeout=300)
        except asyncio.TimeoutError:
            pass
        return session.pop("_last_resp_text", "")

    async def _send_handle_command_result(
        self, cmd, session, sid, raw_reply, pipeline_result
    ):
        if cmd == "new":
            new_cid = await self.context.conversation_manager.get_curr_conversation_id(
                session["umo"]
            )
            if new_cid:
                async with session["_lock"]:
                    session["conv_id"] = new_cid
        elif cmd == "del":
            async with session["_lock"]:
                session["conv_id"] = ""

        from ..galgame_web.session_helpers import save_session

        save_session(self._sessions, sid)
        raw_reply = raw_reply.replace("\\n", "\n") if raw_reply else ""
        return {
            "reply": raw_reply or "",
            "emotion": "neutral",
            "emotions": [],
            "audio": pipeline_result.get("audio", ""),
            "audio_mime": pipeline_result.get("audio_mime", ""),
            "audio_file": pipeline_result.get("audio_file", ""),
            "audio_segments": [],
        }

    async def _send_extract_emotions(self, raw_reply, session):
        from ..galgame_web.utils import (
            EMOTION_PATTERN,
            extract_all_emotions,
            get_emotion_tags,
        )

        raw_reply = raw_reply.replace("\\n", "\n")
        raw_reply = re.sub(r"\[IMAGE\][^\s]+", "", raw_reply)
        emotion_tags = get_emotion_tags(self.config)

        async with session["_lock"]:
            need_sync = not session.get("conv_id")
            pending_emotions = session.pop("_pending_emotions", None)
            pending_all = session.pop("_pending_all_emotions", None)

        if need_sync:
            try:
                new_cid = (
                    await self.context.conversation_manager.get_curr_conversation_id(
                        session["umo"]
                    )
                )
                if new_cid:
                    async with session["_lock"]:
                        session["conv_id"] = new_cid
            except Exception:
                pass

        if pending_emotions:
            clean_text = raw_reply
            emotions = pending_emotions
            emotions_all = pending_all if pending_all else pending_emotions
            clean_text = re.sub(EMOTION_PATTERN, "", clean_text)
            clean_text = re.sub(r"\([a-z-]+\)", "", clean_text)
            clean_text = re.sub(r"<#\d+\.?\d*#>", "", clean_text).strip()
        else:
            clean_text, emotions, emotions_all = extract_all_emotions(
                raw_reply, emotion_tags
            )

        return clean_text, emotions, emotions_all

    async def _send_synthesize_tts(
        self, clean_text, emotions_all, text, matched_prefix, pipeline_audio
    ):
        if not self.config.get("tts_enabled", True):
            return pipeline_audio, "", ""
        if not clean_text or matched_prefix:
            logger.debug(
                f"[tts] skipped text_len={len(clean_text)} "
                f"command={'yes' if matched_prefix else 'no'}"
            )
            return pipeline_audio, "", ""
        tts_provider = tts.select_tts_provider(self.config, self.context)
        if not tts_provider:
            logger.warning("[tts] No TTS provider configured, skipping TTS")
            return pipeline_audio, "", ""
        try:
            return await tts.synthesize_audio(
                clean_text, emotions_all, tts_provider, self.config
            )
        except Exception as e:
            logger.warning(f"[tts] TTS failed: {e}")
            return pipeline_audio, "", ""

    async def _send_save_and_return(
        self,
        session,
        text,
        clean_text,
        emotions,
        emotions_all,
        audio_b64,
        audio_mime_val,
        audio_file,
        sid,
        user_audio_file="",
        user_audio_mime="",
    ):
        from ..galgame_web.session_helpers import (
            PLATFORM_ID,
            cleanup_unreferenced_audio,
            save_session,
            sync_conv_to_db,
        )

        final_emotion = emotions[-1][0] if emotions else "neutral"

        removed_history = []
        async with session["_lock"]:
            user_content = text if text else "(语音消息)"
            session["history"].append(
                {
                    "role": "user",
                    "content": user_content,
                    "audio_file": user_audio_file,
                    "audio_mime": user_audio_mime,
                }
            )
            session["history"].append(
                {
                    "role": "assistant",
                    "content": clean_text,
                    "audio_file": audio_file,
                    "audio_mime": audio_mime_val,
                }
            )
            session["current_emotion"] = final_emotion
            hist_limit = self._get_history_limit()
            if len(session["history"]) > hist_limit:
                removed_history = session["history"][:-hist_limit]
                session["history"] = session["history"][-hist_limit:]

        if save_session(self._sessions, sid):
            cleanup_unreferenced_audio(removed_history, self._sessions)

        character_name = self.config.get("character_name", "角色")
        try:

            async def _save_history():
                await self.context.message_history_manager.insert(
                    platform_id=PLATFORM_ID,
                    user_id=sid,
                    content={
                        "type": "user",
                        "message": [{"type": "plain", "text": user_content}],
                    },
                    sender_id="user",
                    sender_name="用户",
                )
                await self.context.message_history_manager.insert(
                    platform_id=PLATFORM_ID,
                    user_id=sid,
                    content={
                        "type": "bot",
                        "message": [{"type": "plain", "text": clean_text}],
                    },
                    sender_id="bot",
                    sender_name=character_name,
                )

            self._track_task(_save_history())
        except Exception as e:
            logger.warning(f"Failed to save user message to history: {e}")

        try:

            async def _sync():
                await sync_conv_to_db(self.context, session)

            self._track_task(_sync())
        except Exception as e:
            logger.warning(f"Failed to sync conversation to DB: {e}")

        return {
            "reply": clean_text,
            "emotion": final_emotion,
            "emotions": [[emo, pos] for emo, pos in emotions],
            "audio": audio_b64,
            "audio_mime": audio_mime_val,
            "audio_file": audio_file,
            "audio_segments": [],
        }
