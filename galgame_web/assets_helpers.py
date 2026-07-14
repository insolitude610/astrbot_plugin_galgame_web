import pathlib
import re

from astrbot.api import logger

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
VALID_ASSET_PREFIXES = {"single", "expr", "bg", "avatar", "vrm"}
ASSET_KEY_PART_PATTERN = re.compile(r"^[\w-]{1,64}$", re.UNICODE)

from .utils import EXPRESSION_KEYS  # noqa: E402


def list_asset_files(assets_dir: pathlib.Path) -> list[str]:
    if not assets_dir.is_dir():
        return []
    return sorted(
        f.name
        for f in assets_dir.iterdir()
        if f.is_file() and f.suffix.lower() in IMAGE_EXTS
    )


def find_asset_for(label: str, files: list[str], prefix: str = "") -> str:
    label_lower = label.lower()
    if prefix:
        prefixed = f"{prefix}_{label_lower}"
        for fname in files:
            stem = pathlib.Path(fname).stem.lower()
            if stem == prefixed:
                return fname
    for fname in files:
        stem = pathlib.Path(fname).stem.lower()
        if stem == label_lower:
            return fname
    if prefix:
        prefix_lower = prefix.lower()
        for fname in files:
            stem = pathlib.Path(fname).stem.lower()
            parts = stem.split("_")
            if prefix_lower in parts and label_lower in parts:
                return fname
    for fname in files:
        stem = pathlib.Path(fname).stem.lower()
        if label_lower in stem or stem in label_lower:
            return fname
    return ""


def resolve_assets(config: dict, files: list[str]) -> dict:
    sprite_mode = config.get("sprite_mode", "single")

    background = config.get("background", "")
    if not background:
        background = find_asset_for("background", files) or find_asset_for("bg", files)

    expr_prefix = "single" if sprite_mode == "single" else "expr"
    main_files = [f for f in files if "_blink" not in pathlib.Path(f).stem.lower()]
    expressions = {}
    raw_expr = config.get("expressions", {}) or {}
    for key in EXPRESSION_KEYS:
        val = raw_expr.get(key, "")
        if not val:
            val = find_asset_for(key, main_files, expr_prefix)
        elif sprite_mode == "layered":
            auto = find_asset_for(key, main_files, "expr")
            if auto:
                val = auto
        expressions[key] = val

    expressions_blink = {}
    if sprite_mode == "layered":
        for key in EXPRESSION_KEYS:
            blink_val = find_asset_for(f"{key}_blink", files, "expr")
            if blink_val:
                expressions_blink[key] = blink_val

    vrm_model = config.get("vrm_model", "")
    if not vrm_model and sprite_mode == "vrm":
        vrm_model = find_asset_for("model", files) or find_asset_for("vrm", files)
        for fname in files:
            if fname.lower().endswith(".vrm"):
                vrm_model = fname
                break

    layers = {}
    if sprite_mode == "layered":
        layers = {
            "body": "",
            "hair_back": "",
            "head": "",
            "hair_front": "",
            "mouth_open": "",
            "mouth_closed": "",
            "eyes_open": "",
            "eyes_closed": "",
        }

    return {
        "background": background,
        "expressions": expressions,
        "expressions_blink": expressions_blink,
        "layers": layers,
        "vrm_model": vrm_model,
    }


def safe_path(name: str, base_dir: pathlib.Path) -> pathlib.Path | None:
    if (
        not isinstance(name, str)
        or not name
        or "\x00" in name
        or "/" in name
        or "\\" in name
    ):
        return None
    candidate = pathlib.Path(name)
    if candidate.is_absolute() or candidate.name != name:
        return None
    base = base_dir.resolve()
    resolved = (base / candidate).resolve()
    try:
        resolved.relative_to(base)
    except ValueError:
        return None
    return resolved


def parse_asset_key(key: str) -> tuple[str, str] | None:
    if not isinstance(key, str) or "_" not in key:
        return None
    prefix, base = key.split("_", 1)
    if prefix not in VALID_ASSET_PREFIXES:
        return None
    if not ASSET_KEY_PART_PATTERN.fullmatch(base):
        return None
    return prefix, base


def register_asset(
    plugin_config: dict, key: str, filename: str, assets_dir: pathlib.Path
):
    parsed = parse_asset_key(key)
    if not parsed:
        raise ValueError("invalid asset key")
    prefix, base = parsed
    current_path = safe_path(filename, assets_dir)
    if not current_path or current_path.suffix.lower() not in IMAGE_EXTS:
        raise ValueError("invalid asset filename")
    sprite_mode = plugin_config.get("sprite_mode", "single")
    try:
        if prefix == "single" and sprite_mode == "single" and base in EXPRESSION_KEYS:
            if (
                isinstance(plugin_config.get("expressions"), dict)
                and base in plugin_config["expressions"]
            ):
                plugin_config["expressions"][base] = filename
        elif prefix == "expr" and sprite_mode == "layered" and base in EXPRESSION_KEYS:
            if (
                isinstance(plugin_config.get("expressions"), dict)
                and base in plugin_config["expressions"]
            ):
                plugin_config["expressions"][base] = filename
        elif prefix == "bg" and "background" in plugin_config:
            plugin_config["background"] = filename
        elif prefix == "avatar" and "history_avatar" in plugin_config:
            plugin_config["history_avatar"] = filename
    except Exception:
        logger.exception(f"_register_asset failed for key={key}")
    for ext in IMAGE_EXTS:
        old_path = safe_path(f"{base}{ext}", assets_dir)
        if (
            old_path
            and old_path.exists()
            and old_path.is_file()
            and old_path.name != current_path.name
        ):
            try:
                old_path.unlink()
                logger.info(f"Removed old non-prefixed file: {old_path.name}")
            except OSError:
                pass
