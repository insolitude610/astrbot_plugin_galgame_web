import asyncio
import base64
import json
import pathlib
import time
import uuid

from astrbot.api import logger
from astrbot.core.platform.sources.webchat.webchat_queue_mgr import webchat_queue_mgr
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

from . import session_helpers
from .assets_helpers import safe_path
from .audio_utils import detect_audio_mime, ext_for_mime


def is_pure_json(text: str) -> bool:
    stripped = text.strip()
    if not stripped.startswith("{"):
        return False
    try:
        json.loads(stripped)
        return True
    except (json.JSONDecodeError, ValueError):
        return False


async def push_through_pipeline(
    config: dict, username: str, session_id: str, text: str, audio_path: str = ""
) -> dict:
    t0 = time.time()
    msg_id = str(uuid.uuid4())
    wc_sid = f"webchat!{username}!{session_id}"
    logger.info(
        f"[pipeline] start msg_id={msg_id[:8]} sid={session_id[:8]} "
        f"text_len={len(text)} audio={'yes' if audio_path else 'no'}"
    )
    back_queue = webchat_queue_mgr.get_or_create_back_queue(msg_id, wc_sid)
    parts = []
    if audio_path:
        parts.append({"type": "record", "path": audio_path})
    if text:
        parts.append({"type": "plain", "text": text})
    selected_provider = config.get("llm_provider", "").strip() or None
    payload = {
        "message": parts,
        "message_id": msg_id,
        "selected_provider": selected_provider,
        "selected_model": None,
        "enable_streaming": False,
    }
    t1 = time.time()
    chat_queue = webchat_queue_mgr.get_or_create_queue(session_id)
    await chat_queue.put((username, session_id, payload))
    logger.info(f"[pipeline] pushed to chat_queue (setup={t1 - t0:.3f}s)")
    collected = []
    audio_b64 = ""
    audio_mime = ""
    audio_file = ""
    first = True
    try:
        while True:
            result = await asyncio.wait_for(back_queue.get(), timeout=300)
            if first:
                logger.info(
                    f"[pipeline] first resp after {(time.time() - t1) * 1000:.0f}ms"
                )
                first = False
            mtype = result.get("type", "")
            dtext = result.get("data", "")
            if mtype == "end":
                break
            elif mtype == "record":
                record_file = dtext.replace("[RECORD]", "").strip()
                if record_file:
                    attachments_dir = (
                        pathlib.Path(get_astrbot_data_path()) / "attachments"
                    )
                    record_path = safe_path(record_file, attachments_dir)
                    if record_path and record_path.is_file():
                        raw = record_path.read_bytes()
                        audio_b64 = base64.b64encode(raw).decode()
                        audio_mime = detect_audio_mime(raw)
                        session_helpers.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
                        audio_file = f"{uuid.uuid4().hex}{ext_for_mime(audio_mime)}"
                        (session_helpers.AUDIO_DIR / audio_file).write_bytes(raw)
                        logger.info(
                            f"[pipeline] captured audio: {record_file} ({len(raw)} bytes, {audio_mime})"
                        )
            elif mtype in ("plain", "complete"):
                if dtext and not is_pure_json(dtext):
                    collected.append(dtext)
    except asyncio.TimeoutError:
        logger.warning("[pipeline] TIMEOUT after 300s")
    finally:
        webchat_queue_mgr.remove_back_queue(msg_id)
    result_text = "".join(collected).strip()
    logger.info(
        f"[pipeline] returning text_len={len(result_text)} audio={'yes' if audio_b64 else 'no'}"
    )
    return {
        "text": result_text,
        "audio": audio_b64,
        "audio_mime": audio_mime,
        "audio_file": audio_file,
    }
