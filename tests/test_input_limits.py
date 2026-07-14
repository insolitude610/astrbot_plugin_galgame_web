import base64

import pytest

from api import session


def test_audio_decoder_accepts_valid_base64():
    encoded = base64.b64encode(b"RIFFdata").decode("ascii")
    assert session._decode_audio_data(encoded) == b"RIFFdata"
    assert session._decode_audio_data(f"data:audio/wav;base64,{encoded}") == b"RIFFdata"


def test_audio_decoder_rejects_invalid_base64():
    with pytest.raises(ValueError, match="invalid audio_data"):
        session._decode_audio_data("not-valid***")


def test_audio_decoder_checks_encoded_and_decoded_limits(monkeypatch):
    monkeypatch.setattr(session, "MAX_VOICE_BASE64_CHARS", 4)
    with pytest.raises(ValueError, match="too large"):
        session._decode_audio_data("AAAAA")

    monkeypatch.setattr(session, "MAX_VOICE_BASE64_CHARS", 100)
    monkeypatch.setattr(session, "MAX_VOICE_BYTES", 2)
    encoded = base64.b64encode(b"abc").decode("ascii")
    with pytest.raises(ValueError, match="too large"):
        session._decode_audio_data(encoded)
