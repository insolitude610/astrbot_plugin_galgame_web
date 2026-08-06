import json
import pathlib
import re

from astrbot.api import logger

from .session_helpers import _DATA, atomic_write_json

MAX_CHARACTERS = 12
MAX_NAME_CHARS = 64
MAX_PROMPT_CHARS = 20_000
MAX_OPENING_CHARS = 2_000

CHARACTER_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")

CHARACTERS_PATH: pathlib.Path = _DATA / "characters.json"

# 角色卡字段白名单（tts_provider 预留，MVP 不消费但保留字段）
VALID_CHARACTER_KEYS = {
    "id",
    "name",
    "persona_id",
    "custom_prompt",
    "expressions",
    "background",
    "bgm",
    "opening",
    "tts_provider",
}


def is_valid_character_id(cid: object) -> bool:
    return isinstance(cid, str) and bool(CHARACTER_ID_PATTERN.fullmatch(cid))


def _clean_item(item: dict) -> dict | None:
    """校验并清洗单个角色卡条目，非法返回 None。"""
    if not isinstance(item, dict):
        return None
    cid = item.get("id", "")
    name = item.get("name", "")
    if not is_valid_character_id(cid):
        return None
    if not isinstance(name, str) or not name.strip() or len(name) > MAX_NAME_CHARS:
        return None
    cleaned = {}
    for key in VALID_CHARACTER_KEYS:
        value = item.get(key, "")
        if key == "id":
            cleaned[key] = cid
        elif key == "name":
            cleaned[key] = name.strip()
        elif key == "expressions":
            if not isinstance(value, dict):
                value = {}
            value = {
                k: v
                for k, v in value.items()
                if isinstance(k, str) and isinstance(v, str) and len(v) <= 255
            }
            cleaned[key] = value
        elif key == "custom_prompt":
            if not isinstance(value, str):
                value = ""
            cleaned[key] = value[:MAX_PROMPT_CHARS]
        elif key == "opening":
            if not isinstance(value, str):
                value = ""
            cleaned[key] = value[:MAX_OPENING_CHARS]
        else:
            cleaned[key] = value if isinstance(value, str) else ""
    return cleaned


def load_characters() -> list[dict]:
    if not CHARACTERS_PATH.exists():
        return []
    try:
        items = json.loads(CHARACTERS_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(items, list):
        return []
    return [item for item in (_clean_item(i) for i in items) if item]


def save_characters(items: list) -> bool:
    if not isinstance(items, list) or len(items) > MAX_CHARACTERS:
        return False
    cleaned = []
    seen_ids = set()
    for item in items:
        entry = _clean_item(item)
        if entry is None or entry["id"] in seen_ids:
            return False
        seen_ids.add(entry["id"])
        cleaned.append(entry)
    try:
        atomic_write_json(CHARACTERS_PATH, cleaned)
        return True
    except (OSError, TypeError, ValueError) as e:
        logger.warning(f"Failed to save characters: {e}")
        return False
