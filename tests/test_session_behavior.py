import asyncio
import importlib
import json
import sys
import types
from pathlib import Path

PACKAGE_NAME = Path(__file__).resolve().parents[1].name
favorites_module = importlib.import_module(f"{PACKAGE_NAME}.api.favorites")
session_module = importlib.import_module(f"{PACKAGE_NAME}.api.session")
session_helpers = importlib.import_module(
    f"{PACKAGE_NAME}.galgame_web.session_helpers"
)


class _Request:
    def __init__(self, data):
        self.data = data

    async def get_json(self):
        return self.data


def _write_session(path, session_id, history, created_at):
    (path / f"{session_id}.json").write_text(
        json.dumps(
            {
                "umo": "umo",
                "conv_id": "conv",
                "history": history,
                "current_emotion": "neutral",
                "created_at": created_at,
            }
        ),
        encoding="utf-8",
    )


def test_session_init_resumes_latest_but_force_new_reuses_blank(tmp_path, monkeypatch):
    latest_id = "a" * 32
    blank_id = "b" * 32
    _write_session(tmp_path, blank_id, [], 1)
    _write_session(tmp_path, latest_id, [{"role": "assistant", "content": "hi"}], 2)
    monkeypatch.setattr(session_helpers, "SESSIONS_DIR", tmp_path)

    api = object.__new__(session_module.SessionAPI)
    api._sessions = {}
    monkeypatch.setattr(session_module, "request", _Request({}))
    resumed = asyncio.run(api._api_session_init())
    assert resumed["session_id"] == latest_id

    api._sessions = {}
    monkeypatch.setattr(session_module, "request", _Request({"force_new": True}))
    fresh = asyncio.run(api._api_session_init())
    assert fresh["session_id"] == blank_id


def test_loading_favorites_does_not_truncate_legacy_data(tmp_path, monkeypatch):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    (audio_dir / "voice.wav").write_bytes(b"RIFF")
    favorites_path = tmp_path / "favorites.json"
    favorites = [
        {
            "id": str(index),
            "text": "saved",
            "audio_file": "voice.wav",
            "audio_mime": "audio/wav",
        }
        for index in range(favorites_module.MAX_FAVORITES + 1)
    ]
    favorites_path.write_text(json.dumps(favorites), encoding="utf-8")

    main_module_name = f"{PACKAGE_NAME}.main"
    main_stub = types.ModuleType(main_module_name)
    main_stub.AUDIO_DIR = audio_dir
    main_stub.FAVORITES_PATH = favorites_path
    monkeypatch.setitem(sys.modules, main_module_name, main_stub)

    api = object.__new__(favorites_module.FavoritesAPI)
    loaded = api._load_favorites()
    assert len(loaded) == favorites_module.MAX_FAVORITES + 1
    assert len(json.loads(favorites_path.read_text(encoding="utf-8"))) == len(loaded)
