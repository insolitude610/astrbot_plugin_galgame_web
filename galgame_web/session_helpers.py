import asyncio
import json
import pathlib
import time

from astrbot.api import logger

SESSIONS_DIR = pathlib.Path("data/plugin_data") / "astrbot_plugin_galgame_web" / "sessions"

PLATFORM_ID = "webchat"


def build_umo(webchat_username: str, session_id: str) -> str:
    return f"{PLATFORM_ID}:FriendMessage:webchat!{webchat_username}!{session_id}"


def session_path(session_id: str) -> pathlib.Path:
    return SESSIONS_DIR / f"{session_id}.json"


def save_session(sessions: dict[str, dict], session_id: str):
    session = sessions.get(session_id)
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
        with open(session_path(session_id), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except OSError as e:
        logger.warning(f"Failed to save session {session_id}: {e}")


def load_session(session_id: str) -> dict | None:
    path = session_path(session_id)
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
            "_resp_event": asyncio.Event(),
            "_audio_event": asyncio.Event(),
            "created_at": data.get("created_at", time.time()),
            "_lock": asyncio.Lock(),
        }
    except (OSError, json.JSONDecodeError) as e:
        logger.warning(f"Failed to load session {session_id}: {e}")
        return None


def load_all_sessions(sessions: dict[str, dict]) -> int:
    count = 0
    for path in SESSIONS_DIR.glob("*.json"):
        sid = path.stem
        if sid in sessions:
            continue
        session = load_session(sid)
        if session:
            sessions[sid] = session
            count += 1
    if count:
        logger.info(f"Loaded {count} persisted sessions")
    return count


def gc_sessions(
    sessions: dict[str, dict],
    config: dict,
    delete_conv_callback,
):
    retain_days = config.get("session_retain_days", 7)
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
                asyncio.ensure_future(delete_conv_callback(sid))
        except (OSError, json.JSONDecodeError):
            pass
    if removed:
        logger.info(f"GC removed {removed} expired sessions")


async def init_astrbot_conv(
    context,
    webchat_username: str,
    config: dict,
    session_id: str,
    session: dict,
):
    umo = build_umo(webchat_username, session_id)
    persona_id = config.get("persona", "") or None

    existing_conv_id = await context.conversation_manager.get_curr_conversation_id(umo)
    if existing_conv_id:
        conv = await context.conversation_manager.get_conversation(umo, existing_conv_id)
        if conv:
            session["umo"] = umo
            session["conv_id"] = existing_conv_id
            return

    try:
        conv_id = await context.conversation_manager.new_conversation(
            unified_msg_origin=umo,
            platform_id=PLATFORM_ID,
            content=session.get("history", []),
            persona_id=persona_id,
        )
        session["umo"] = umo
        session["conv_id"] = conv_id
    except Exception as e:
        logger.warning(f"Failed to create AstrBot conversation for {session_id}: {e}")


async def sync_conv_to_db(context, session: dict):
    umo = session.get("umo")
    conv_id = session.get("conv_id")
    history = session.get("history", [])
    if not umo or not conv_id:
        return
    try:
        conv = await context.conversation_manager.get_conversation(umo, conv_id)
        if not conv:
            return
        await context.conversation_manager.update_conversation(
            unified_msg_origin=umo,
            conversation_id=conv_id,
            history=history,
        )
    except Exception as e:
        logger.warning(f"Failed to sync conversation to DB: {e}")


async def delete_astrbot_conv(context, webchat_username: str, session_id: str):
    umo = build_umo(webchat_username, session_id)
    try:
        await context.conversation_manager.delete_conversations_by_user_id(umo)
    except Exception as e:
        logger.warning(f"Failed to delete AstrBot conversation for {session_id}: {e}")


async def sync_sessions_to_db(
    context,
    webchat_username: str,
    config: dict,
    sessions: dict[str, dict],
    save_fn,
):
    for sid, session in list(sessions.items()):
        if not session.get("conv_id"):
            await init_astrbot_conv(context, webchat_username, config, sid, session)
            save_fn(sid)
        else:
            history = session.get("history", [])
            if not history:
                continue
            try:
                conv = await context.conversation_manager.get_conversation(
                    unified_msg_origin=session["umo"],
                    conversation_id=session["conv_id"],
                )
                if not conv:
                    await init_astrbot_conv(context, webchat_username, config, sid, session)
                    save_fn(sid)
            except Exception as e:
                logger.warning(f"Failed to ensure conversation exists for {sid}: {e}")
