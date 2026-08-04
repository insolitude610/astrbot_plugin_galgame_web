import base64
import shutil

from quart import Response, request

from astrbot.api import logger

MAX_UPLOAD_ITEMS = 32
MAX_UPLOAD_TOTAL_BYTES = 40 * 1024 * 1024
MAX_BATCH_ITEMS = 64
MAX_BATCH_RESPONSE_BYTES = 30 * 1024 * 1024


class AssetAPI:
    def _register_asset_apis(self):
        pn = self._plugin_name
        self.context.register_web_api(
            f"/{pn}/assets/list", self._api_assets_list, ["GET"], "List asset files"
        )
        self.context.register_web_api(
            f"/{pn}/assets/upload",
            self._api_assets_upload,
            ["POST"],
            "Upload image files",
        )
        self.context.register_web_api(
            f"/{pn}/assets/upload-key",
            self._api_assets_upload_key,
            ["POST"],
            "Upload image by key",
        )
        self.context.register_web_api(
            f"/{pn}/assets/delete", self._api_assets_delete, ["POST"], "Delete an asset"
        )
        self.context.register_web_api(
            f"/{pn}/assets/file", self._api_assets_file, ["GET"], "Serve an asset file"
        )
        self.context.register_web_api(
            f"/{pn}/assets/batch",
            self._api_assets_batch,
            ["POST"],
            "Get base64 data for multiple assets",
        )
        self.context.register_web_api(
            f"/{pn}/assets/copy", self._api_assets_copy, ["POST"], "Copy an asset"
        )
        self.context.register_web_api(
            f"/{pn}/assets/batch-delete",
            self._api_assets_batch_delete,
            ["POST"],
            "Batch delete assets",
        )

    async def _api_assets_list(self):
        from ..galgame_web.assets_helpers import IMAGE_EXTS
        from ..main import ASSETS_DIR

        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        entries = [
            {"name": f.name}
            for f in sorted(ASSETS_DIR.iterdir())
            if f.is_file() and f.suffix.lower() in IMAGE_EXTS
        ]
        return {"files": entries}

    async def _api_assets_upload(self):
        from ..galgame_web.assets_helpers import IMAGE_EXTS, MAX_UPLOAD_BYTES, safe_path
        from ..main import ASSETS_DIR

        data = await request.get_json() or {}
        if not isinstance(data, dict):
            return {"error": "invalid request"}, 400
        files_data = data.get("files", [])
        if not isinstance(files_data, list) or len(files_data) > MAX_UPLOAD_ITEMS:
            return {
                "error": f"files must contain at most {MAX_UPLOAD_ITEMS} items"
            }, 400
        logger.info(f"[assets] upload received {len(files_data)} items")
        if not files_data:
            return {"error": "no files"}, 400
        uploaded = []
        total_bytes = 0
        ASSETS_DIR.mkdir(parents=True, exist_ok=True)
        for f in files_data:
            if not isinstance(f, dict):
                continue
            name, b64 = f.get("name", ""), f.get("data", "")
            if (
                not isinstance(name, str)
                or not isinstance(b64, str)
                or not name
                or not b64
            ):
                continue
            if "," in b64:
                b64 = b64.split(",", 1)[1]
            if len(b64) > MAX_UPLOAD_BYTES * 2:
                continue
            sp = safe_path(name, ASSETS_DIR)
            if not sp or sp.suffix.lower() not in IMAGE_EXTS:
                continue
            try:
                raw = base64.b64decode(b64, validate=True)
                if len(raw) > MAX_UPLOAD_BYTES:
                    continue
                total_bytes += len(raw)
                if total_bytes > MAX_UPLOAD_TOTAL_BYTES:
                    return {"error": "total upload size too large"}, 413
                sp.write_bytes(raw)
                uploaded.append(sp.name)
                logger.info(f"Uploaded asset: {sp.name}")
            except Exception as e:
                logger.warning(f"Failed to save {name}: {e}")
        if not uploaded:
            return {"error": "no valid image files uploaded"}, 400
        return {"uploaded": uploaded}

    async def _api_assets_upload_key(self):
        from ..galgame_web.assets_helpers import (
            IMAGE_EXTS,
            MAX_UPLOAD_BYTES,
            parse_asset_key,
            register_asset,
            safe_path,
        )
        from ..main import ASSETS_DIR

        data = await request.get_json() or {}
        if not isinstance(data, dict):
            return {"error": "invalid request"}, 400
        raw_key = data.get("key", "")
        key = raw_key.strip() if isinstance(raw_key, str) else ""
        b64 = data.get("data", "")
        if not key or not isinstance(b64, str) or not b64:
            return {"error": "key and data required"}, 400
        if not parse_asset_key(key):
            return {"error": "invalid asset key"}, 400
        if "," in b64:
            prefix, b64 = b64.split(",", 1)
            ext_map = {
                "jpeg": ".jpg",
                "jpg": ".jpg",
                "webp": ".webp",
                "bmp": ".bmp",
                "gif": ".gif",
            }
            mime_ext = ".png"
            for tag, ext in ext_map.items():
                if tag in prefix:
                    mime_ext = ext
                    break
            name = f"{key}{mime_ext}"
        else:
            name = f"{key}.png"
        if len(b64) > MAX_UPLOAD_BYTES * 2:
            return {"error": "file too large"}, 400
        sp = safe_path(name, ASSETS_DIR)
        if not sp or sp.suffix.lower() not in IMAGE_EXTS:
            return {"error": "unsupported extension"}, 400
        try:
            raw = base64.b64decode(b64, validate=True)
            if len(raw) > MAX_UPLOAD_BYTES:
                return {"error": "file too large"}, 400
            ASSETS_DIR.mkdir(parents=True, exist_ok=True)
            sp.write_bytes(raw)
            logger.info(f"Uploaded key asset: {sp.name}")
            register_asset(self.config, key, sp.name, ASSETS_DIR)
            return {"uploaded": sp.name}
        except (ValueError, TypeError) as e:
            return {"error": str(e)}, 400
        except Exception as e:
            return {"error": str(e)}, 500

    async def _api_assets_delete(self):
        from ..galgame_web.assets_helpers import safe_path
        from ..main import ASSETS_DIR

        data = await request.get_json() or {}
        if not isinstance(data, dict):
            return {"error": "invalid request"}, 400
        filename = data.get("filename", "")
        if not filename:
            return {"error": "no filename"}, 400
        sp = safe_path(filename, ASSETS_DIR)
        if not sp or not sp.exists() or not sp.is_file():
            return {"error": "file not found"}, 404
        sp.unlink()
        logger.info(f"Deleted asset: {sp.name}")
        return {"deleted": sp.name}

    async def _api_assets_file(self):
        from ..galgame_web.assets_helpers import safe_path
        from ..main import ASSETS_DIR, AUDIO_DIR

        filename = request.args.get("name", "")
        sp = safe_path(filename, ASSETS_DIR)
        if not sp or not sp.exists() or not sp.is_file():
            sp = safe_path(filename, AUDIO_DIR)
        if not sp or not sp.exists() or not sp.is_file():
            return {"error": "file not found"}, 404
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".gif": "image/gif",
            ".wav": "audio/wav",
            ".mp3": "audio/mpeg",
            ".ogg": "audio/ogg",
            ".flac": "audio/flac",
            ".m4a": "audio/mp4",
        }
        resp = Response(
            sp.read_bytes(),
            content_type=mime_map.get(sp.suffix.lower(), "application/octet-stream"),
        )
        resp.headers["X-Content-Type-Options"] = "nosniff"
        return resp

    async def _api_assets_batch(self):
        from ..galgame_web.assets_helpers import MAX_UPLOAD_BYTES, safe_path
        from ..main import ASSETS_DIR

        data = await request.get_json() or {}
        if not isinstance(data, dict):
            return {"error": "invalid request"}, 400
        names = data.get("names", [])
        if not isinstance(names, list) or not names:
            return {"error": "no names"}, 400
        names = list(dict.fromkeys(name for name in names if isinstance(name, str)))
        if len(names) > MAX_BATCH_ITEMS:
            return {"error": f"too many names (max {MAX_BATCH_ITEMS})"}, 400
        mime_map = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".bmp": "image/bmp",
            ".gif": "image/gif",
        }
        result = []
        total_bytes = 0
        for name in names:
            sp = safe_path(name, ASSETS_DIR)
            if not sp or not sp.exists() or not sp.is_file():
                continue
            try:
                if sp.stat().st_size > MAX_UPLOAD_BYTES:
                    continue
                raw = sp.read_bytes()
                total_bytes += len(raw)
                if total_bytes > MAX_BATCH_RESPONSE_BYTES:
                    return {"error": "asset batch response too large"}, 413
                b64 = base64.b64encode(raw).decode()
                mt = mime_map.get(sp.suffix.lower(), "image/png")
                result.append({"name": sp.name, "data": f"data:{mt};base64,{b64}"})
            except Exception as e:
                logger.warning(f"[assets] batch read failed {name}: {e}")
        return {"files": result}

    async def _api_assets_copy(self):
        from ..galgame_web.assets_helpers import (
            IMAGE_EXTS,
            parse_asset_key,
            register_asset,
            safe_path,
        )
        from ..main import ASSETS_DIR

        data = await request.get_json() or {}
        if not isinstance(data, dict):
            return {"error": "invalid request"}, 400
        raw_source = data.get("source", "")
        raw_dest_key = data.get("key", "")
        source = raw_source.strip() if isinstance(raw_source, str) else ""
        dest_key = raw_dest_key.strip() if isinstance(raw_dest_key, str) else ""
        if not source or not dest_key:
            return {"error": "source and key required"}, 400
        if not parse_asset_key(dest_key):
            return {"error": "invalid asset key"}, 400
        sp = safe_path(source, ASSETS_DIR)
        if not sp or not sp.is_file():
            return {"error": "source not found"}, 404
        if sp.suffix.lower() not in IMAGE_EXTS:
            return {"error": "unsupported extension"}, 400
        dest_name = f"{dest_key}{sp.suffix.lower()}"
        dp = safe_path(dest_name, ASSETS_DIR)
        if not dp or dp.suffix.lower() not in IMAGE_EXTS:
            return {"error": "invalid destination"}, 400
        try:
            ASSETS_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(sp, dp)
            logger.info(f"Copied asset: {source} -> {dp.name}")
            register_asset(self.config, dest_key, dp.name, ASSETS_DIR)
            return {"copied": dp.name, "source": source}
        except OSError as e:
            return {"error": str(e)}, 500

    async def _api_assets_batch_delete(self):
        from ..galgame_web.assets_helpers import safe_path
        from ..main import ASSETS_DIR

        data = await request.get_json() or {}
        if not isinstance(data, dict):
            return {"error": "invalid request"}, 400
        filenames = data.get("filenames", [])
        if not isinstance(filenames, list) or not filenames:
            return {"error": "no filenames"}, 400
        if len(filenames) > MAX_BATCH_ITEMS:
            return {"error": f"too many filenames (max {MAX_BATCH_ITEMS})"}, 400
        deleted = []
        for name in filenames:
            sp = safe_path(name, ASSETS_DIR)
            if sp and sp.is_file():
                sp.unlink()
                deleted.append(name)
        logger.info(f"Batch deleted {len(deleted)} assets")
        return {"deleted": deleted}
