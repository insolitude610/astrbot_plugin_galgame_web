import base64

import pytest

from galgame_web import audio_utils


def test_audio_decoder_accepts_valid_base64():
    encoded = base64.b64encode(b"RIFFdata").decode("ascii")
    assert audio_utils.decode_audio_data(encoded) == b"RIFFdata"
    assert (
        audio_utils.decode_audio_data(f"data:audio/wav;base64,{encoded}") == b"RIFFdata"
    )


def test_audio_decoder_rejects_invalid_base64():
    with pytest.raises(ValueError, match="invalid audio_data"):
        audio_utils.decode_audio_data("not-valid***")


def test_audio_decoder_checks_encoded_and_decoded_limits(monkeypatch):
    monkeypatch.setattr(audio_utils, "MAX_VOICE_BASE64_CHARS", 4)
    with pytest.raises(ValueError, match="too large"):
        audio_utils.decode_audio_data("AAAAA")

    monkeypatch.setattr(audio_utils, "MAX_VOICE_BASE64_CHARS", 100)
    monkeypatch.setattr(audio_utils, "MAX_VOICE_BYTES", 2)
    encoded = base64.b64encode(b"abc").decode("ascii")
    with pytest.raises(ValueError, match="too large"):
        audio_utils.decode_audio_data(encoded)
