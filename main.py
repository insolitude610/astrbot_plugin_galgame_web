import asyncio
import base64
import json
import os
import re
import time
import uuid

from quart import Response, request

from astrbot.api import logger
from astrbot.api.event import AstrMessageEvent, MessageEventResult, filter
from astrbot.api.star import Context, Star

PLUGIN_NAME = "astrbot_plugin_galgame"

EMOTION_TAGS = ["neutral", "happy", "sad", "angry", "surprised", "blush", "thinking"]
EMOTION_PATTERN = re.compile(r"\[emotion:(\w+)\]")


class GalgamePlugin(Star):
    def __init__(self, context: Context, config: dict | None = None):
        super().__init__(context)
        self.config = config or {}
        self._sessions: dict[str, dict] = {}

        context.register_web_api(
            f"/{PLUGIN_NAME}/session/init",
            self._api_session_init,
            ["POST"],
            "Initialize a new galgame session",
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
            f"/{PLUGIN_NAME}/rapid_action",
            self._api_rapid_action,
            ["POST"],
            "Notify rapid click/keyboard activity",
        )

    def _get_config_tts_provider(self):
        prov_id = self.config.get("tts_provider", "")
        if not prov_id:
            return None
        return self.context.get_provider_by_id(prov_id)

    def _build_system_prompt(self):
        name = self.config.get("character_name", "小星")
        role = self.config.get("character_role", "")
        extra = self.config.get("system_prompt_extra", "")
        emotions = ", ".join(EMOTION_TAGS)

        prompt = f"""你是{name}，{role}

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
        session_id = uuid.uuid4().hex
        self._sessions[session_id] = {
            "history": [],
            "current_emotion": "neutral",
            "pending_rapid_clicks": 0,
            "sse_queue": asyncio.Queue(),
            "created_at": time.time(),
        }
        return {"session_id": session_id}

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

        rapid_count = session.pop("pending_rapid_clicks", 0)
        rapid_hint = ""
        if rapid_count > 0:
            rapid_hint = (
                f"\n\n（用户刚才在短时间内快速点击了{rapid_count}次鼠标或按键，"
                f"可能心情烦躁或着急，请关心一下ta怎么了）"
            )

        system_prompt = self._build_system_prompt() + rapid_hint

        messages = list(session["history"])
        messages.append({"role": "user", "content": text})

        try:
            llm_prov_id = self.config.get("llm_provider", "")
            if not llm_prov_id:
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
            current_emotion = "neutral"
            if emotion_match:
                tag = emotion_match.group(1).lower()
                if tag in EMOTION_TAGS:
                    current_emotion = tag

            clean_text = EMOTION_PATTERN.sub("", full_text).strip()

            session["history"].append({"role": "user", "content": text})
            session["history"].append({"role": "assistant", "content": clean_text})
            session["current_emotion"] = current_emotion

            if len(session["history"]) > 20:
                session["history"] = session["history"][-20:]

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
            await queue.put({"type": "error", "message": f"处理消息时出错: {e}"})

        return {"status": "ok"}

    async def _api_stream(self):
        session_id = request.args.get("session_id", "")
        if not session_id or session_id not in self._sessions:

            async def error_stream():
                yield f"event: error\ndata: {json.dumps({'message': 'invalid session_id'})}\n\n"

            return Response(error_stream(), content_type="text/event-stream")

        session = self._sessions[session_id]
        queue = session["sse_queue"]

        async def event_stream():
            while True:
                try:
                    msg = await asyncio.wait_for(queue.get(), timeout=25)
                    yield f"event: message\ndata: {json.dumps(msg, ensure_ascii=False)}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"

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
        return {
            "sprite_mode": self.config.get("sprite_mode", "single"),
            "rapid_click_threshold": self.config.get("rapid_click_threshold", 5),
            "rapid_window_seconds": self.config.get("rapid_window_seconds", 3),
            "tts_provider": self.config.get("tts_provider", ""),
            "expressions": self.config.get("expressions", {}),
            "layers": self.config.get("layers", {}),
            "character_name": self.config.get("character_name", "小星"),
            "background": self.config.get("background", ""),
        }

    async def _api_rapid_action(self):
        data = await request.get_json()
        if not data:
            return {"error": "no data"}, 400

        session_id = data.get("session_id", "")
        count = data.get("count", 0)

        if session_id in self._sessions:
            self._sessions[session_id]["pending_rapid_clicks"] = count

        return {"status": "ok"}

    @filter.command("galgame")
    async def cmd_galgame(self, event: AstrMessageEvent) -> MessageEventResult:
        yield event.plain_result(
            "AI Galgame 虚拟伙伴\n\n"
            "请在浏览器中打开 AstrBot Dashboard，\n"
            "进入「插件 → AI Galgame 虚拟伙伴」页面，\n"
            "点击「Galgame」页面即可打开虚拟伙伴界面。"
        )

    async def terminate(self):
        for session in self._sessions.values():
            queue = session.get("sse_queue")
            if queue:
                await queue.put({"type": "end"})
        self._sessions.clear()
