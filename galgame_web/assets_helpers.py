import base64
import pathlib
import shutil

from astrbot.api import logger

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}
MAX_UPLOAD_BYTES = 10 * 1024 * 1024

from .utils import EXPRESSION_KEYS


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
    expressions = {}
    raw_expr = config.get("expressions", {}) or {}
    for key in EXPRESSION_KEYS:
        val = raw_expr.get(key, "")
        if not val:
            val = find_asset_for(key, files, expr_prefix)
        elif sprite_mode == "layered":
            auto = find_asset_for(key, files, "expr")
            if auto:
                val = auto
        expressions[key] = val

    expressions_blink = {}
    if sprite_mode == "layered":
        for key in EXPRESSION_KEYS:
            blink_val = find_asset_for(f"{key}_blink", files, "expr")
            if blink_val:
                expressions_blink[key] = blink_val

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
    }


def safe_path(name: str, base_dir: pathlib.Path) -> pathlib.Path | None:
    stem = pathlib.Path(name).name
    if not stem or stem != name.split("/")[-1].split("\\")[-1]:
        return None
    resolved = (base_dir / stem).resolve()
    if not str(resolved).startswith(str(base_dir.resolve())):
        return None
    return resolved


def register_asset(plugin_config: dict, key: str, filename: str, assets_dir: pathlib.Path):
    if "_" not in key:
        return
    parts = key.split("_", 1)
    prefix, base = parts[0], parts[1]
    sprite_mode = plugin_config.get("sprite_mode", "single")
    try:
        if prefix == "single" and sprite_mode == "single" and base in EXPRESSION_KEYS:
            if isinstance(plugin_config.get("expressions"), dict) and base in plugin_config["expressions"]:
                plugin_config["expressions"][base] = filename
        elif prefix == "expr" and sprite_mode == "layered" and base in EXPRESSION_KEYS:
            if isinstance(plugin_config.get("expressions"), dict) and base in plugin_config["expressions"]:
                plugin_config["expressions"][base] = filename
        elif prefix == "bg" and "background" in plugin_config:
            plugin_config["background"] = filename
    except Exception:
        logger.exception(f"_register_asset failed for key={key}")
    for ext in IMAGE_EXTS:
        old_path = assets_dir / f"{base}{ext}"
        if old_path.exists() and old_path.is_file() and old_path.name != filename:
            try:
                old_path.unlink()
                logger.info(f"Removed old non-prefixed file: {old_path.name}")
            except OSError:
                pass
