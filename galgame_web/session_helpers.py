import asyncio
import json
import pathlib
import time

from astrbot.api import logger
from astrbot.api.star import StarTools

_PLUGIN = "astrbot_plugin_galgame_web"
_DATA = StarTools.get_data_dir(_PLUGIN)
SESSIONS_DIR = _DATA / "sessions"
AUDIO_DIR = _DATA / "audio"
FAVORITES_PATH = _DATA / "favorites.json"

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
        with open(path, encoding="utf-8") as f:
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
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if now - data.get("created_at", 0) > ttl:
                path.unlink()
                removed += 1
                sid = path.stem
                cleanup_session_audio(data.get("history", []))
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
        conv = await context.conversation_manager.get_conversation(
            umo, existing_conv_id
        )
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
        history = session.get("history", [])
        conv_id = session.get("conv_id", "")
        umo = session.get("umo", "")

        conv_exists = False
        if conv_id and umo:
            try:
                conv = await context.conversation_manager.get_conversation(umo, conv_id)
                conv_exists = conv is not None
            except Exception:
                pass

        if not history and not conv_exists:
            path = session_path(sid)
            if path.exists():
                path.unlink()
            del sessions[sid]
            logger.info(f"Cleaned up dead session: {sid[:8]}")
            continue

        if not conv_id or not conv_exists:
            await init_astrbot_conv(context, webchat_username, config, sid, session)
            save_fn(sid)
        elif not history:
            continue


def _collect_referenced_audio(
    sessions: dict[str, dict], favorites: list[dict]
) -> set[str]:
    refs: set[str] = set()
    for s in sessions.values():
        for msg in s.get("history", []):
            f = msg.get("audio_file", "")
            if f:
                refs.add(f)
    for fav in favorites:
        f = fav.get("audio_file", "")
        if f:
            refs.add(f)
    return refs


def gc_audio_files(sessions: dict[str, dict]):
    favs: list[dict] = []
    if FAVORITES_PATH.exists():
        try:
            favs = json.loads(FAVORITES_PATH.read_text(encoding="utf-8")) or []
        except (OSError, json.JSONDecodeError):
            pass
    refs = _collect_referenced_audio(sessions, favs)
    count = 0
    for path in AUDIO_DIR.glob("*"):
        if path.is_file() and path.name not in refs:
            path.unlink()
            count += 1
    if count:
        logger.info(f"GC cleaned up {count} orphan audio files")


def cleanup_session_audio(history: list[dict]):
    for msg in history:
        f = msg.get("audio_file", "")
        if f:
            p = AUDIO_DIR / f
            if p.exists():
                p.unlink()
