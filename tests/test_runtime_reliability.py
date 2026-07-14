import asyncio
import importlib
import json
import threading
import wave
from pathlib import Path

import pytest


PACKAGE_NAME = Path(__file__).resolve().parents[1].name
main_module = importlib.import_module(f"{PACKAGE_NAME}.main")
session_module = importlib.import_module(f"{PACKAGE_NAME}.api.session")
session_helpers = importlib.import_module(
    f"{PACKAGE_NAME}.galgame_web.session_helpers"
)


class _Request:
    def __init__(self, data):
        self.data = data

    async def get_json(self):
        return self.data


def _session(history=None):
    return {
        "umo": "",
        "conv_id": "",
        "history": history or [],
        "current_emotion": "neutral",
        "pending_rapid_clicks": 0,
        "created_at": 1,
        "_lock": asyncio.Lock(),
        "_send_lock": asyncio.Lock(),
    }


def _configure_audio_gc(tmp_path, monkeypatch):
    audio_dir = tmp_path / "audio"
    sessions_dir = tmp_path / "sessions"
    favorites_path = tmp_path / "favorites.json"
    audio_dir.mkdir()
    sessions_dir.mkdir()
    monkeypatch.setattr(session_helpers, "AUDIO_DIR", audio_dir)
    monkeypatch.setattr(session_helpers, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(session_helpers, "FAVORITES_PATH", favorites_path)
    return audio_dir, sessions_dir, favorites_path


def _write_wav(path, frame_count=4):
    with wave.open(str(path), "wb") as target:
        target.setnchannels(1)
        target.setsampwidth(2)
        target.setframerate(8000)
        target.writeframes(b"\x00\x00" * frame_count)


def test_rapid_click_is_consumed_once_as_poke(monkeypatch):
    async def scenario():
        sid = "a" * 32
        api = object.__new__(session_module.SessionAPI)
        api.config = {
            "rapid_click_enabled": True,
            "rapid_click_threshold": 5,
        }
        api._sessions = {sid: _session()}
        captured = []

        async def fake_send(sent_sid, text, audio_raw):
            captured.append((sent_sid, text, audio_raw))
            return {"reply": "ok"}

        api._do_send = fake_send
        monkeypatch.setattr(
            session_module, "request", _Request({"session_id": sid, "count": 5})
        )
        assert await api._api_rapid_action() == {"status": "ok"}

        monkeypatch.setattr(
            session_module,
            "request",
            _Request({"session_id": sid, "text": "", "audio_data": ""}),
        )
        assert await api._api_send() == {"reply": "ok"}
        assert captured == [(sid, "(戳了戳)", b"")]
        assert api._sessions[sid]["pending_rapid_clicks"] == 0

        response, status = await api._api_send()
        assert status == 400
        assert response["error"] == "text or audio required"
        assert len(captured) == 1

    asyncio.run(scenario())


def test_aac_audio_is_detected_and_uses_matching_extension():
    api = object.__new__(session_module.SessionAPI)
    raw = b"\xff\xf1\x50\x80" + b"\x00" * 16

    assert api._detect_audio_mime(raw) == "audio/aac"
    assert api._ext_for_mime("audio/aac") == ".aac"


def test_audio_gc_fails_closed_for_corrupt_or_incomplete_session_metadata(
    tmp_path, monkeypatch
):
    audio_dir, sessions_dir, favorites_path = _configure_audio_gc(
        tmp_path, monkeypatch
    )
    audio = audio_dir / "possibly-referenced.wav"
    audio.write_bytes(b"RIFF")
    session_path = sessions_dir / f"{'d' * 32}.json"
    favorites_path.write_text("[]", encoding="utf-8")

    session_path.write_text("{broken", encoding="utf-8")
    session_helpers.gc_audio_files({})
    assert audio.exists()

    session_path.write_text(json.dumps({"history": [None]}), encoding="utf-8")
    session_helpers.gc_audio_files({})
    assert audio.exists()


def test_audio_gc_fails_closed_for_corrupt_favorites(tmp_path, monkeypatch):
    audio_dir, _sessions_dir, favorites_path = _configure_audio_gc(
        tmp_path, monkeypatch
    )
    audio = audio_dir / "favorite.wav"
    audio.write_bytes(b"RIFF")
    favorites_path.write_text("not-json", encoding="utf-8")

    session_helpers.gc_audio_files({})

    assert audio.exists()


def test_audio_gc_fails_closed_when_session_directory_is_unreadable(
    tmp_path, monkeypatch
):
    audio_dir, sessions_dir, _favorites_path = _configure_audio_gc(
        tmp_path, monkeypatch
    )
    audio = audio_dir / "unknown-owner.wav"
    audio.write_bytes(b"RIFF")
    original_iterdir = Path.iterdir

    def unreadable_iterdir(path):
        if path == sessions_dir:
            raise PermissionError("sessions unavailable")
        return original_iterdir(path)

    monkeypatch.setattr(Path, "iterdir", unreadable_iterdir)

    session_helpers.gc_audio_files({})

    assert audio.exists()


def test_audio_gc_includes_sessions_present_only_on_disk(tmp_path, monkeypatch):
    audio_dir, sessions_dir, favorites_path = _configure_audio_gc(
        tmp_path, monkeypatch
    )
    audio = audio_dir / "persisted.wav"
    audio.write_bytes(b"RIFF")
    favorites_path.write_text("[]", encoding="utf-8")
    (sessions_dir / f"{'e' * 32}.json").write_text(
        json.dumps({"history": [{"audio_file": audio.name}]}), encoding="utf-8"
    )

    session_helpers.gc_audio_files({})

    assert audio.exists()


def test_audio_gc_removes_true_orphan_with_complete_metadata(tmp_path, monkeypatch):
    audio_dir, _sessions_dir, _favorites_path = _configure_audio_gc(
        tmp_path, monkeypatch
    )
    orphan = audio_dir / "orphan.wav"
    orphan.write_bytes(b"RIFF")

    session_helpers.gc_audio_files({})

    assert not orphan.exists()


def test_audio_gc_tolerates_legacy_entries_without_audio(tmp_path, monkeypatch):
    audio_dir, _sessions_dir, favorites_path = _configure_audio_gc(
        tmp_path, monkeypatch
    )
    orphan = audio_dir / "orphan.wav"
    orphan.write_bytes(b"RIFF")
    favorites_path.write_text('[{"text": "legacy"}, null]', encoding="utf-8")

    session_helpers.gc_audio_files({})

    assert not orphan.exists()


def test_save_session_reports_atomic_write_failure(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    sid = "f" * 32
    sessions = {sid: _session([{"audio_file": "voice.wav"}])}
    monkeypatch.setattr(session_helpers, "SESSIONS_DIR", sessions_dir)
    monkeypatch.setattr(
        session_helpers,
        "atomic_write_json",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    assert session_helpers.save_session(sessions, sid) is False


def test_atomic_json_failure_preserves_previous_file(tmp_path):
    target = tmp_path / "prefs.json"
    target.write_text('{"volume": 0.5}', encoding="utf-8")

    with pytest.raises(TypeError):
        session_helpers.atomic_write_json(target, {"bad": object()})

    assert json.loads(target.read_text(encoding="utf-8")) == {"volume": 0.5}
    assert list(tmp_path.glob("*.tmp")) == []


def test_command_audio_cleanup_waits_for_successful_session_save(monkeypatch):
    async def scenario():
        sid = "9" * 32
        session = _session([{"audio_file": "voice.wav"}])
        api = object.__new__(session_module.SessionAPI)
        api._sessions = {sid: session}

        class Context:
            @staticmethod
            def get_config():
                return {"wake_prefix": ["/"]}

        api.context = Context()
        cleaned = []
        monkeypatch.setattr(session_helpers, "save_session", lambda *_args: False)
        monkeypatch.setattr(
            session_helpers,
            "cleanup_unreferenced_audio",
            lambda history, _sessions: cleaned.extend(history),
        )

        matched_prefix, command = await api._send_handle_command(
            "/reset", session, sid
        )

        assert (matched_prefix, command) == ("/", "reset")
        assert session["history"] == []
        assert cleaned == []

    asyncio.run(scenario())


def test_trimmed_audio_is_deleted_only_after_all_references_are_gone(
    tmp_path, monkeypatch
):
    async def scenario():
        sid = "b" * 32
        audio_dir = tmp_path / "audio"
        sessions_dir = tmp_path / "sessions"
        audio_dir.mkdir()
        sessions_dir.mkdir()
        kept = audio_dir / "kept.wav"
        orphan = audio_dir / "orphan.wav"
        kept.write_bytes(b"RIFF-kept")
        orphan.write_bytes(b"RIFF-orphan")
        favorites_path = tmp_path / "favorites.json"
        favorites_path.write_text(
            json.dumps([{"audio_file": kept.name}]), encoding="utf-8"
        )
        monkeypatch.setattr(session_helpers, "AUDIO_DIR", audio_dir)
        monkeypatch.setattr(session_helpers, "FAVORITES_PATH", favorites_path)
        monkeypatch.setattr(session_helpers, "SESSIONS_DIR", sessions_dir)

        history = [
            {"role": "assistant", "content": "old", "audio_file": kept.name},
            {"role": "assistant", "content": "old", "audio_file": orphan.name},
        ]
        session = _session(history)
        api = object.__new__(session_module.SessionAPI)
        api._sessions = {sid: session}
        api.config = {"character_name": "角色"}
        api._get_history_limit = lambda: 2

        inserts = []
        tasks = []

        class HistoryManager:
            async def insert(self, **kwargs):
                inserts.append(kwargs)

        class Context:
            message_history_manager = HistoryManager()

        api.context = Context()
        api._track_task = lambda coro: tasks.append(asyncio.create_task(coro)) or tasks[-1]

        await api._send_save_and_return(
            session,
            "hello",
            "world",
            [],
            [],
            "",
            "",
            "",
            sid,
        )
        await asyncio.gather(*tasks)

        assert kept.exists()
        assert not orphan.exists()
        assert [entry["user_id"] for entry in inserts] == [sid, sid]
        assert inserts[0]["content"]["message"] == [
            {"type": "plain", "text": "hello"}
        ]
        assert inserts[1]["content"]["message"] == [
            {"type": "plain", "text": "world"}
        ]

        favorites_path.write_text("[]", encoding="utf-8")
        session_helpers.cleanup_unreferenced_audio(
            [{"audio_file": kept.name}], api._sessions
        )
        assert not kept.exists()

    asyncio.run(scenario())


def test_wav_merge_works_without_ffmpeg(tmp_path, monkeypatch):
    persistent_audio = tmp_path / "persistent-audio"
    persistent_audio.mkdir()
    monkeypatch.setattr(main_module, "AUDIO_DIR", persistent_audio)
    monkeypatch.setattr(main_module, "_get_astrbot_temp_dir", lambda: tmp_path)
    paths = []
    for index, frame_count in enumerate((4, 6)):
        path = tmp_path / f"part-{index}.wav"
        _write_wav(path, frame_count)
        paths.append(path)

    monkeypatch.setattr(
        main_module.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("ffmpeg should not be used for compatible WAV files")
        ),
    )
    plugin = object.__new__(main_module.GalgamePlugin)
    output = plugin._concat_audio(paths)
    assert output and output.exists()
    with wave.open(str(output), "rb") as merged:
        assert merged.getnframes() == 10
    assert all(not path.exists() for path in paths)


def test_partial_parallel_tts_retries_the_full_text(tmp_path, monkeypatch):
    async def scenario():
        temp_dir = tmp_path / "temp"
        audio_dir = tmp_path / "audio"
        temp_dir.mkdir()
        audio_dir.mkdir()
        monkeypatch.setattr(main_module, "AUDIO_DIR", audio_dir)
        monkeypatch.setattr(main_module, "_get_astrbot_temp_dir", lambda: temp_dir)

        partial = temp_dir / "partial.wav"
        fallback = temp_dir / "fallback.wav"
        calls = []

        class Provider:
            async def get_audio(self, text):
                calls.append(text)
                if text == "[neutral]第一句。":
                    partial.write_bytes(b"RIFF-partial")
                    return str(partial)
                if text == "[neutral]第二句。":
                    raise RuntimeError("sentence failed")
                if text == "[neutral]第一句。第二句。":
                    fallback.write_bytes(b"RIFF-fallback")
                    return str(fallback)
                raise AssertionError(f"unexpected TTS text: {text}")

        plugin = object.__new__(main_module.GalgamePlugin)
        output = await plugin._parallel_tts(
            "第一句。第二句。", [], {}, Provider()
        )

        assert output == fallback
        assert calls[-1] == "[neutral]第一句。第二句。"
        assert not partial.exists()
        assert fallback.exists()

    asyncio.run(scenario())


def test_partial_parallel_tts_returns_none_when_full_retry_fails(
    tmp_path, monkeypatch
):
    async def scenario():
        temp_dir = tmp_path / "temp"
        audio_dir = tmp_path / "audio"
        temp_dir.mkdir()
        audio_dir.mkdir()
        monkeypatch.setattr(main_module, "AUDIO_DIR", audio_dir)
        monkeypatch.setattr(main_module, "_get_astrbot_temp_dir", lambda: temp_dir)

        partial = temp_dir / "partial.wav"
        calls = []

        class Provider:
            async def get_audio(self, text):
                calls.append(text)
                if text == "[neutral]第一句。":
                    partial.write_bytes(b"RIFF-partial")
                    return str(partial)
                raise RuntimeError("TTS failed")

        plugin = object.__new__(main_module.GalgamePlugin)
        output = await plugin._parallel_tts(
            "第一句。第二句。", [], {}, Provider()
        )

        assert output is None
        assert calls[-1] == "[neutral]第一句。第二句。"
        assert not partial.exists()

    asyncio.run(scenario())


def test_tts_consumers_cleanup_temp_outputs_after_persisting(
    tmp_path, monkeypatch
):
    async def scenario():
        temp_dir = tmp_path / "temp"
        audio_dir = tmp_path / "audio"
        temp_dir.mkdir()
        audio_dir.mkdir()
        monkeypatch.setattr(main_module, "AUDIO_DIR", audio_dir)
        monkeypatch.setattr(main_module, "_get_astrbot_temp_dir", lambda: temp_dir)

        queued_paths = []

        class Provider:
            async def get_audio(self, _text):
                return str(queued_paths.pop(0))

        provider = Provider()

        class Context:
            provider_manager = type("ProviderManager", (), {"inst_map": {}})()

            def get_using_tts_provider(self):
                return provider

        plugin = object.__new__(main_module.GalgamePlugin)
        plugin.context = Context()
        plugin.config = {
            "tts_enabled": True,
            "tts_provider": "",
            "tts_emotion_map": "{}",
            "audio_format": "wav",
        }

        first = temp_dir / "first.wav"
        second = temp_dir / "second.wav"
        _write_wav(first)
        _write_wav(second)
        queued_paths.extend([first, second])
        session = {}

        await plugin._do_bg_tts("First. Second.", session)

        background_file = audio_dir / session["_bg_tts_result"][2]
        assert background_file.is_file()
        assert list(temp_dir.iterdir()) == []

        single = temp_dir / "single.wav"
        _write_wav(single)
        queued_paths.append(single)
        _audio, _mime, sync_filename = await plugin._send_synthesize_tts(
            "Single.", [], "input", None, ""
        )

        assert (audio_dir / sync_filename).is_file()
        assert list(temp_dir.iterdir()) == []

    asyncio.run(scenario())


def test_tts_temp_cleanup_never_deletes_persistent_audio(tmp_path, monkeypatch):
    temp_dir = tmp_path / "temp"
    audio_dir = temp_dir / "persistent-audio"
    audio_dir.mkdir(parents=True)
    persistent = audio_dir / "voice.wav"
    persistent.write_bytes(b"RIFF-persistent")
    monkeypatch.setattr(main_module, "AUDIO_DIR", audio_dir)
    monkeypatch.setattr(main_module, "_get_astrbot_temp_dir", lambda: temp_dir)

    assert not main_module._cleanup_tts_temp_path(persistent)
    assert persistent.exists()


def test_command_conversation_id_is_saved_after_sync(tmp_path, monkeypatch):
    async def scenario():
        sid = "c" * 32
        monkeypatch.setattr(session_helpers, "SESSIONS_DIR", tmp_path)
        session = _session()
        session["umo"] = "webchat:FriendMessage:webchat!tester!" + sid
        api = object.__new__(session_module.SessionAPI)
        api._sessions = {sid: session}

        class ConversationManager:
            async def get_curr_conversation_id(self, _umo):
                return "new-conversation-id"

        class Context:
            conversation_manager = ConversationManager()

        api.context = Context()
        await api._send_handle_command_result("new", session, sid, "", {})

        saved = json.loads((tmp_path / f"{sid}.json").read_text(encoding="utf-8"))
        assert saved["conv_id"] == "new-conversation-id"

    asyncio.run(scenario())


def test_terminate_cancels_managed_tasks():
    async def scenario():
        plugin = object.__new__(main_module.GalgamePlugin)
        plugin._background_tasks = set()
        plugin._active_send_tasks = set()
        plugin._terminating = False
        plugin._web_server = None
        plugin._web_thread = None
        plugin._sessions = {}

        class Context:
            registered_web_apis = []

        plugin.context = Context()
        background_started = asyncio.Event()
        active_started = asyncio.Event()

        async def blocked(started):
            started.set()
            await asyncio.Event().wait()

        task = plugin._track_task(blocked(background_started))
        active_task = asyncio.create_task(blocked(active_started))
        plugin._active_send_tasks.add(active_task)
        await asyncio.gather(background_started.wait(), active_started.wait())
        await plugin.terminate()
        assert task.cancelled()
        assert active_task.cancelled()
        assert plugin._background_tasks == set()
        assert plugin._active_send_tasks == set()

        late_started = False

        async def late_task():
            nonlocal late_started
            late_started = True

        late = plugin._track_task(late_task())
        await asyncio.sleep(0)
        assert late.cancelled()
        assert not late_started

    asyncio.run(scenario())


def test_thread_worker_finishes_cleanup_before_cancellation_returns(tmp_path):
    async def scenario():
        api = object.__new__(session_module.SessionAPI)
        started = threading.Event()
        release = threading.Event()
        marker = tmp_path / "worker-finished"

        def worker():
            started.set()
            release.wait(timeout=2)
            marker.write_text("done", encoding="utf-8")

        task = asyncio.create_task(api._run_in_thread_to_completion(worker))
        while not started.is_set():
            await asyncio.sleep(0.001)
        task.cancel()
        await asyncio.sleep(0)
        assert not task.done()
        release.set()
        try:
            await task
        except asyncio.CancelledError:
            pass
        else:
            raise AssertionError("cancellation must propagate after the worker exits")
        assert marker.read_text(encoding="utf-8") == "done"

    asyncio.run(scenario())
