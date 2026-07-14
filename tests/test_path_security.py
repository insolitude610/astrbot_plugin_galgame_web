import json
import os
import time

import pytest

from galgame_web import assets_helpers, session_helpers


@pytest.mark.parametrize(
    "name",
    [
        "../outside.png",
        "..\\outside.png",
        "/tmp/outside.png",
        "C:\\outside.png",
        "folder/file.png",
        "folder\\file.png",
    ],
)
def test_asset_safe_path_rejects_non_basename(tmp_path, name):
    assert assets_helpers.safe_path(name, tmp_path) is None


def test_asset_key_rejects_paths_and_accepts_named_slots():
    assert assets_helpers.parse_asset_key("single_happy") == ("single", "happy")
    assert assets_helpers.parse_asset_key("single_开心") == ("single", "开心")
    assert assets_helpers.parse_asset_key("single_../victim") is None
    assert assets_helpers.parse_asset_key("x_victim") is None
    assert assets_helpers.parse_asset_key("single_C:\\victim") is None


def test_register_asset_cannot_delete_outside_asset_directory(tmp_path):
    assets_dir = tmp_path / "assets"
    assets_dir.mkdir()
    outside = tmp_path / "victim.png"
    outside.write_bytes(b"keep")
    uploaded = assets_dir / "victim.jpg"
    uploaded.write_bytes(b"new")

    with pytest.raises(ValueError):
        assets_helpers.register_asset({}, "single_../victim", uploaded.name, assets_dir)

    assert outside.read_bytes() == b"keep"


def test_session_path_accepts_only_generated_ids(tmp_path, monkeypatch):
    monkeypatch.setattr(session_helpers, "SESSIONS_DIR", tmp_path)
    valid_id = "a" * 32
    assert session_helpers.session_path(valid_id) == tmp_path / f"{valid_id}.json"

    for invalid in ("../config", "C:\\config", "short", "g" * 32):
        with pytest.raises(ValueError):
            session_helpers.session_path(invalid)


def test_session_audio_cleanup_cannot_escape_audio_directory(tmp_path, monkeypatch):
    audio_dir = tmp_path / "audio"
    audio_dir.mkdir()
    outside = tmp_path / "outside.wav"
    outside.write_bytes(b"keep")
    inside = audio_dir / "inside.wav"
    inside.write_bytes(b"delete")
    monkeypatch.setattr(session_helpers, "AUDIO_DIR", audio_dir)

    session_helpers.cleanup_session_audio(
        [{"audio_file": "../outside.wav"}, {"audio_file": "inside.wav"}]
    )

    assert outside.exists()
    assert not inside.exists()


def test_malformed_session_is_ignored_without_crashing(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    session_id = "b" * 32
    (sessions_dir / f"{session_id}.json").write_text("[]", encoding="utf-8")
    monkeypatch.setattr(session_helpers, "SESSIONS_DIR", sessions_dir)

    assert session_helpers.load_session(session_id) is None


def test_invalid_session_filename_is_not_garbage_collected(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    sessions_dir.mkdir()
    invalid = sessions_dir / "..evil.json"
    invalid.write_text(json.dumps({"created_at": 0}), encoding="utf-8")
    monkeypatch.setattr(session_helpers, "SESSIONS_DIR", sessions_dir)

    async def delete_callback(_sid):
        raise AssertionError("invalid session must not reach the callback")

    session_helpers.gc_sessions({}, {"session_retain_days": 1}, delete_callback)
    assert invalid.exists()


def test_saved_session_uses_atomic_replacement(tmp_path, monkeypatch):
    sessions_dir = tmp_path / "sessions"
    monkeypatch.setattr(session_helpers, "SESSIONS_DIR", sessions_dir)
    session_id = "c" * 32
    sessions = {
        session_id: {
            "umo": "umo",
            "conv_id": "conv",
            "history": [],
            "current_emotion": "neutral",
            "created_at": 1,
        }
    }

    session_helpers.save_session(sessions, session_id)

    saved = json.loads((sessions_dir / f"{session_id}.json").read_text("utf-8"))
    assert saved["conv_id"] == "conv"
    assert list(sessions_dir.glob("*.tmp")) == []


def test_stale_voice_staging_files_are_collected(tmp_path, monkeypatch):
    from astrbot.core.utils import astrbot_path

    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    stale = temp_dir / "galgame_audio_stale.wav"
    recent = temp_dir / "galgame_audio_recent.wav"
    unrelated = temp_dir / "other.wav"
    for path in (stale, recent, unrelated):
        path.write_bytes(b"audio")
    old = time.time() - 3600
    os.utime(stale, (old, old))
    monkeypatch.setattr(astrbot_path, "get_astrbot_data_path", lambda: str(tmp_path))

    session_helpers.gc_temp_voice_files()

    assert not stale.exists()
    assert recent.exists()
    assert unrelated.exists()
