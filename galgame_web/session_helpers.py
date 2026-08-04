import asyncio
import json
import os
import pathlib
import re
import time
import uuid
import wave

from astrbot.api import logger
from astrbot.api.star import StarTools

_PLUGIN = "astrbot_plugin_galgame_web"
_DATA = StarTools.get_data_dir(_PLUGIN)
SESSIONS_DIR = _DATA / "sessions"
AUDIO_DIR = _DATA / "audio"
FAVORITES_PATH = _DATA / "favorites.json"

PLATFORM_ID = "webchat"
SESSION_ID_PATTERN = re.compile(r"^[a-f0-9]{32}$")


def is_valid_session_id(session_id: str) -> bool:
    return isinstance(session_id, str) and bool(
        SESSION_ID_PATTERN.fullmatch(session_id)
    )


def build_umo(webchat_username: str, session_id: str) -> str:
    if not is_valid_session_id(session_id):
        raise ValueError("invalid session_id")
    return f"{PLATFORM_ID}:FriendMessage:webchat!{webchat_username}!{session_id}"


def session_path(session_id: str) -> pathlib.Path:
    if not is_valid_session_id(session_id):
        raise ValueError("invalid session_id")
    return SESSIONS_DIR / f"{session_id}.json"


def atomic_write_json(path: pathlib.Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass


_atomic_write_json = atomic_write_json


def concatenate_wav_files(paths: list[pathlib.Path], output: pathlib.Path) -> bool:
    try:
        params = None
        frames = []
        for path in paths:
            with wave.open(str(path), "rb") as source:
                current = (
                    source.getnchannels(),
                    source.getsampwidth(),
                    source.getframerate(),
                    source.getcomptype(),
                )
                if params is None:
                    params = current
                elif current != params:
                    raise wave.Error("incompatible WAV parameters")
                frames.append(source.readframes(source.getnframes()))
        if params is None:
            return False
        with wave.open(str(output), "wb") as target:
            target.setnchannels(params[0])
            target.setsampwidth(params[1])
            target.setframerate(params[2])
            target.setcomptype(params[3], "not compressed")
            for frame_data in frames:
                target.writeframes(frame_data)
        return True
    except (EOFError, OSError, wave.Error):
        output.unlink(missing_ok=True)
        return False


def save_session(sessions: dict[str, dict], session_id: str):
    session = sessions.get(session_id)
    if not session:
        return False
    data = {
        "umo": session.get("umo", ""),
        "conv_id": session.get("conv_id", ""),
        "history": session["history"],
        "current_emotion": session["current_emotion"],
        "created_at": session["created_at"],
    }
    try:
        atomic_write_json(session_path(session_id), data)
        return True
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"Failed to save session {session_id}: {e}")
        return False


def load_session(session_id: str) -> dict | None:
    path = session_path(session_id)
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError("session root must be an object")
        history = data.get("history", [])
        if not isinstance(history, list):
            raise ValueError("session history must be a list")
        created_at = data.get("created_at", time.time())
        if not isinstance(created_at, (int, float)):
            created_at = time.time()
        return {
            "umo": data.get("umo", "") if isinstance(data.get("umo", ""), str) else "",
            "conv_id": data.get("conv_id", "")
            if isinstance(data.get("conv_id", ""), str)
            else "",
            "history": [item for item in history if isinstance(item, dict)],
            "current_emotion": data.get("current_emotion", "neutral")
            if isinstance(data.get("current_emotion", "neutral"), str)
            else "neutral",
            "pending_rapid_clicks": 0,
            "_resp_event": asyncio.Event(),
            "_audio_event": asyncio.Event(),
            "created_at": created_at,
            "_lock": asyncio.Lock(),
            "_send_lock": asyncio.Lock(),
        }
    except (OSError, json.JSONDecodeError, ValueError) as e:
        logger.warning(f"Failed to load session {session_id}: {e}")
        return None


def load_all_sessions(sessions: dict[str, dict]) -> int:
    count = 0
    for path in SESSIONS_DIR.glob("*.json"):
        sid = path.stem
        if not is_valid_session_id(sid) or sid in sessions:
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
        if not is_valid_session_id(path.stem):
            logger.warning(f"Ignoring invalid session filename: {path.name}")
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                logger.warning(f"Ignoring invalid session file: {path.name}")
                continue
            created_at = data.get("created_at", 0)
            if not isinstance(created_at, (int, float)):
                logger.warning(f"Ignoring session with invalid timestamp: {path.name}")
                continue
            if now - created_at > ttl:
                path.unlink()
                removed += 1
                sid = path.stem
                asyncio.ensure_future(delete_conv_callback(sid))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
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

        if not history and not umo:
            path = session_path(sid)
            if path.exists():
                path.unlink()
            del sessions[sid]
            logger.info(f"Cleaned up dead session: {sid[:8]}")
            continue

        if not history:
            continue

        conv_exists = False
        if conv_id and umo:
            try:
                conv = await context.conversation_manager.get_conversation(umo, conv_id)
                conv_exists = conv is not None
            except Exception:
                pass

        if not conv_id or not conv_exists:
            await init_astrbot_conv(context, webchat_username, config, sid, session)
            save_fn(sid)

    for path in SESSIONS_DIR.glob("*.json"):
        sid = path.stem
        if not is_valid_session_id(sid) or sid in sessions:
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                continue
            if not data.get("history") and not data.get("umo"):
                path.unlink()
                logger.info(f"Cleaned up blank session file: {sid[:8]}")
        except (OSError, json.JSONDecodeError):
            pass


def _collect_referenced_audio(
    sessions: dict[str, dict], favorites: list[dict]
) -> set[str]:
    refs: set[str] = set()
    if not isinstance(sessions, dict):
        raise ValueError("in-memory sessions must be an object")
    for sid, session in sessions.items():
        if not isinstance(session, dict) or "history" not in session:
            raise ValueError(f"in-memory session {sid!r} is incomplete")
        history = session["history"]
        if not isinstance(history, list):
            raise ValueError(f"in-memory session {sid!r} history must be a list")
        for index, msg in enumerate(history):
            if not isinstance(msg, dict):
                raise ValueError(
                    f"in-memory session {sid!r} history item {index} must be an object"
                )
            f = msg.get("audio_file", "")
            if not isinstance(f, str):
                raise ValueError(
                    f"in-memory session {sid!r} history item {index} has invalid audio_file"
                )
            if not f:
                continue
            audio_path = _safe_audio_path(f)
            if not audio_path:
                raise ValueError(
                    f"in-memory session {sid!r} history item {index} has unsafe audio_file"
                )
            refs.add(audio_path.name)

    if not isinstance(favorites, list):
        raise ValueError("favorites root must be a list")
    for fav in favorites:
        if not isinstance(fav, dict):
            continue
        f = fav.get("audio_file")
        if not isinstance(f, str) or not f:
            continue
        audio_path = _safe_audio_path(f)
        if audio_path:
            refs.add(audio_path.name)
    return refs


def _load_favorites_for_audio_gc() -> list[dict]:
    try:
        raw = FAVORITES_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return []
    loaded = json.loads(raw)
    if not isinstance(loaded, list):
        raise ValueError("favorites root must be a list")
    return loaded


def _collect_complete_audio_references(
    sessions: dict[str, dict],
) -> set[str] | None:
    try:
        refs = _collect_referenced_audio(sessions, [])
        for path in SESSIONS_DIR.iterdir():
            if path.suffix != ".json" or not is_valid_session_id(path.stem):
                continue
            if path.stem in sessions:
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or "history" not in data:
                raise ValueError(f"session file {path.name} is incomplete")
            refs.update(_collect_referenced_audio({path.stem: data}, []))
        refs.update(_collect_referenced_audio({}, _load_favorites_for_audio_gc()))
        return refs
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as exc:
        logger.warning(
            f"Skipping audio GC because reference metadata is incomplete: {exc}"
        )
        return None


def cleanup_unreferenced_audio(
    removed_history: list[dict], sessions: dict[str, dict]
) -> int:
    try:
        candidates = {
            path.name
            for msg in removed_history
            if isinstance(msg, dict)
            if (path := _safe_audio_path(msg.get("audio_file", "")))
        }
    except (OSError, RuntimeError) as exc:
        logger.warning(
            f"Skipping audio cleanup because candidates are unreadable: {exc}"
        )
        return 0
    if not candidates:
        return 0
    refs = _collect_complete_audio_references(sessions)
    if refs is None:
        return 0
    removed = 0
    for filename in candidates - refs:
        path = _safe_audio_path(filename)
        if not path or not path.is_file():
            continue
        try:
            path.unlink()
            removed += 1
        except OSError as exc:
            logger.warning(f"Failed to remove unreferenced audio {filename}: {exc}")
    return removed


def gc_audio_files(sessions: dict[str, dict]):
    refs = _collect_complete_audio_references(sessions)
    if refs is None:
        return
    count = 0
    for path in AUDIO_DIR.glob("*"):
        if path.is_file() and path.name not in refs:
            try:
                path.unlink()
                count += 1
            except OSError as exc:
                logger.warning(f"Failed to remove orphan audio {path.name}: {exc}")
    if count:
        logger.info(f"GC cleaned up {count} orphan audio files")


def gc_temp_voice_files():
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path

    temp_dir = pathlib.Path(get_astrbot_data_path()) / "temp"
    count = 0
    for path in temp_dir.glob("galgame_audio_*.wav"):
        try:
            if path.is_file() and time.time() - path.stat().st_mtime > 600:
                path.unlink()
                count += 1
        except OSError:
            pass
    if count:
        logger.info(f"GC cleaned up {count} stale voice staging files")


def cleanup_session_audio(history: list[dict]):
    for msg in history:
        if not isinstance(msg, dict):
            continue
        f = msg.get("audio_file", "")
        p = _safe_audio_path(f)
        if p and p.exists() and p.is_file():
            p.unlink()


def _safe_audio_path(filename: str) -> pathlib.Path | None:
    if (
        not isinstance(filename, str)
        or not filename
        or "/" in filename
        or "\\" in filename
    ):
        return None
    candidate = pathlib.Path(filename)
    if candidate.is_absolute() or candidate.name != filename:
        return None
    base = AUDIO_DIR.resolve()
    resolved = (base / filename).resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        return None
    return resolved
