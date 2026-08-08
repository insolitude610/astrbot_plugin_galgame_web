import asyncio
import importlib
import json
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


def test_repeated_force_new_creates_at_most_one_blank_session(tmp_path, monkeypatch):
    monkeypatch.setattr(session_helpers, "SESSIONS_DIR", tmp_path)
    api = object.__new__(session_module.SessionAPI)
    api._sessions = {}
    api._webchat_username = "tester"
    monkeypatch.setattr(session_module, "request", _Request({"force_new": True}))

    first = asyncio.run(api._api_session_init())
    second = asyncio.run(api._api_session_init())

    assert first["session_id"] == second["session_id"]
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_force_new_does_not_reuse_session_while_send_is_in_progress(
    tmp_path, monkeypatch
):
    async def scenario():
        sid = "c" * 32
        _write_session(tmp_path, sid, [], 1)
        monkeypatch.setattr(session_helpers, "SESSIONS_DIR", tmp_path)

        original = session_helpers.load_session(sid)
        api = object.__new__(session_module.SessionAPI)
        api._sessions = {sid: original}
        api._webchat_username = "tester"
        started = asyncio.Event()
        release = asyncio.Event()

        async def blocked_send(sent_sid, _text, _audio_raw):
            active_session = api._sessions[sent_sid]
            started.set()
            await release.wait()
            async with active_session["_lock"]:
                active_session["history"].append(
                    {"role": "assistant", "content": "completed"}
                )
            session_helpers.save_session(api._sessions, sent_sid)
            return {"reply": "completed"}

        api._do_send = blocked_send
        monkeypatch.setattr(
            session_module,
            "request",
            _Request({"session_id": sid, "text": "hello", "audio_data": ""}),
        )
        send_task = asyncio.create_task(api._api_send())
        await started.wait()
        assert original["_send_lock"].locked()

        monkeypatch.setattr(
            session_module, "request", _Request({"force_new": True})
        )
        initialized = await api._api_session_init()
        original_was_preserved = api._sessions.get(sid) is original

        release.set()
        assert await send_task == {"reply": "completed"}
        assert initialized["session_id"] != sid
        assert original_was_preserved
        assert api._sessions[sid] is original
        assert original["history"][-1]["content"] == "completed"
        persisted = json.loads((tmp_path / f"{sid}.json").read_text(encoding="utf-8"))
        assert persisted["history"][-1]["content"] == "completed"

    asyncio.run(scenario())


def test_force_new_reuses_idle_in_memory_blank_session_without_replacing_it(
    tmp_path, monkeypatch
):
    async def scenario():
        sid = "d" * 32
        _write_session(tmp_path, sid, [], 1)
        monkeypatch.setattr(session_helpers, "SESSIONS_DIR", tmp_path)

        original = session_helpers.load_session(sid)
        original_send_lock = original["_send_lock"]
        api = object.__new__(session_module.SessionAPI)
        api._sessions = {sid: original}
        api._webchat_username = "tester"
        monkeypatch.setattr(
            session_module, "request", _Request({"force_new": True})
        )

        initialized = await api._api_session_init()

        assert initialized["session_id"] == sid
        assert api._sessions[sid] is original
        assert api._sessions[sid]["_send_lock"] is original_send_lock

    asyncio.run(scenario())


def test_auto_resume_uses_live_in_memory_session_without_replacing_it(
    tmp_path, monkeypatch
):
    async def scenario():
        sid = "e" * 32
        _write_session(tmp_path, sid, [], 1)
        monkeypatch.setattr(session_helpers, "SESSIONS_DIR", tmp_path)

        original = session_helpers.load_session(sid)
        original["history"].append({"role": "user", "content": "in flight"})
        api = object.__new__(session_module.SessionAPI)
        api._sessions = {sid: original}
        api._webchat_username = "tester"
        monkeypatch.setattr(session_module, "request", _Request({}))

        initialized = await api._api_session_init()

        assert initialized["session_id"] == sid
        assert api._sessions[sid] is original
        assert api._sessions[sid]["history"][-1]["content"] == "in flight"

    asyncio.run(scenario())


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

    monkeypatch.setattr(session_helpers, "AUDIO_DIR", audio_dir)
    monkeypatch.setattr(session_helpers, "FAVORITES_PATH", favorites_path)

    api = object.__new__(favorites_module.FavoritesAPI)
    loaded = api._load_favorites()
    assert len(loaded) == favorites_module.MAX_FAVORITES + 1
    assert len(json.loads(favorites_path.read_text(encoding="utf-8"))) == len(loaded)
