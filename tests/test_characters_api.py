import pathlib

import pytest

from galgame_web.characters_helpers import (
    CHARACTERS_PATH,
    VALID_CHARACTER_KEYS,
    is_valid_character_id,
    load_characters,
    save_characters,
)


@pytest.fixture(autouse=True)
def _clean_characters_file():
    CHARACTERS_PATH.unlink(missing_ok=True)
    yield
    CHARACTERS_PATH.unlink(missing_ok=True)


def test_character_id_validation():
    assert is_valid_character_id("alice")
    assert is_valid_character_id("a1-b2-c3")
    assert not is_valid_character_id("")
    assert not is_valid_character_id("Alice")
    assert not is_valid_character_id("a b")
    assert not is_valid_character_id("../../etc")
    assert not is_valid_character_id("a" * 65)


def test_save_and_load_roundtrip():
    items = [
        {
            "id": "alice",
            "name": "爱丽丝",
            "persona_id": "",
            "custom_prompt": "",
            "expressions": {"neutral": "alice_neutral.png"},
            "background": "",
            "bgm": "",
            "opening": "你好呀~",
            "tts_provider": "",
        }
    ]
    assert save_characters(items) is True
    loaded = load_characters()
    assert loaded == items


def test_save_rejects_invalid_items():
    assert save_characters([{"id": "../evil", "name": "x"}]) is False
    assert not CHARACTERS_PATH.exists()
    assert save_characters([]) is True
    assert load_characters() == []


def test_load_missing_file_returns_empty():
    assert load_characters() == []


def test_load_corrupt_file_returns_empty():
    CHARACTERS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CHARACTERS_PATH.write_text("{bad json", encoding="utf-8")
    assert load_characters() == []


def test_load_unknown_keys_dropped():
    assert save_characters(
        [{"id": "alice", "name": "A", "unknown_key": "x", "custom_prompt": ""}]
    )
    loaded = load_characters()[0]
    assert "unknown_key" not in loaded
    assert set(loaded.keys()) == set(VALID_CHARACTER_KEYS)
