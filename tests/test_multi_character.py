import json
import uuid

from galgame_web.session_helpers import SESSIONS_DIR, load_session, save_session


def _make_session(history=None, mode=None, characters=None):
    sid = uuid.uuid4().hex
    session = {
        "umo": "",
        "conv_id": "",
        "history": history if history is not None else [],
        "current_emotion": "neutral",
        "created_at": 1,
        "mode": mode,
        "characters": characters or [],
        "next_char_idx": 0,
    }
    return sid, session


def test_save_load_roundtrip_preserves_multi_fields():
    sid, session = _make_session(
        history=[{"id": "h1", "role": "user", "content": "hi"}],
        mode="multi",
        characters=["alice", "bob"],
    )
    session["next_char_idx"] = 1
    assert save_session({sid: session}, sid)
    loaded = load_session(sid)
    assert loaded["mode"] == "multi"
    assert loaded["characters"] == ["alice", "bob"]
    assert loaded["next_char_idx"] == 1


def test_load_legacy_session_gets_defaults_and_ids():
    sid = uuid.uuid4().hex
    path = SESSIONS_DIR / f"{sid}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "umo": "",
                "conv_id": "",
                "history": [{"role": "user", "content": "hi"}],
                "current_emotion": "neutral",
                "created_at": 1,
            }
        ),
        encoding="utf-8",
    )
    loaded = load_session(sid)
    assert loaded["mode"] == "single"
    assert loaded["characters"] == []
    assert loaded["next_char_idx"] == 0
    assert loaded["history"][0]["id"]


def test_save_load_keeps_history_character_field():
    sid, session = _make_session(
        history=[
            {"id": "h2", "role": "assistant", "character": "alice", "content": "hi"}
        ]
    )
    save_session({sid: session}, sid)
    loaded = load_session(sid)
    assert loaded["history"][0]["character"] == "alice"
