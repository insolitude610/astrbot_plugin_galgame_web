import base64
import binascii
import pathlib
import subprocess
import uuid

from astrbot.api import logger
from astrbot.core.utils.astrbot_path import get_astrbot_data_path

_MIME_EXT = {
    "audio/wav": ".wav",
    "audio/mpeg": ".mp3",
    "audio/ogg": ".ogg",
    "audio/flac": ".flac",
    "audio/mp4": ".m4a",
    "audio/aac": ".aac",
}
MAX_VOICE_BYTES = 15 * 1024 * 1024
MAX_VOICE_BASE64_CHARS = ((MAX_VOICE_BYTES + 2) // 3) * 4


def decode_audio_data(audio_data: str) -> bytes:
    if not isinstance(audio_data, str):
        raise ValueError("audio_data must be a base64 string")
    payload = audio_data.split(",", 1)[1] if "," in audio_data else audio_data
    if not payload:
        return b""
    if len(payload) > MAX_VOICE_BASE64_CHARS:
        raise ValueError("voice message too large")
    try:
        raw = base64.b64decode(payload, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("invalid audio_data") from exc
    if len(raw) > MAX_VOICE_BYTES:
        raise ValueError("voice message too large")
    return raw


def ext_for_mime(mime: str) -> str:
    return _MIME_EXT.get(mime, ".wav")


def detect_audio_mime(raw: bytes) -> str:
    if len(raw) < 4:
        return "audio/wav"
    head = raw[:4]
    if head == b"RIFF":
        return "audio/wav"
    if head == b"OggS":
        return "audio/ogg"
    if head == b"fLaC":
        return "audio/flac"
    if head[:2] == b"\xff\xfb" or head[:2] == b"\xff\xf3" or head[:2] == b"\xff\xf2":
        return "audio/mpeg"
    if head == b"ID3\x03" or head == b"ID3\x02" or head == b"ID3\x04":
        return "audio/mpeg"
    if raw[0] == 0xFF and raw[1] & 0xF6 == 0xF0:
        return "audio/aac"
    if len(raw) >= 12 and raw[4:8] == b"ftyp":
        return "audio/mp4"
    return "audio/wav"


def save_audio(raw: bytes) -> str:
    audio_dir = pathlib.Path(get_astrbot_data_path()) / "temp"
    audio_dir.mkdir(parents=True, exist_ok=True)
    audio_path = audio_dir / f"galgame_audio_{uuid.uuid4().hex}.wav"
    with open(audio_path, "wb") as f:
        f.write(raw)
    logger.info(f"Saved voice audio: {audio_path} ({len(raw)} bytes)")
    return str(audio_path.resolve())


def convert_audio(wav_path: pathlib.Path) -> pathlib.Path | None:
    mp3_path = wav_path.with_suffix(".mp3")
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_path), "-b:a", "128k", str(mp3_path)],
            capture_output=True,
            timeout=10,
        )
        if result.returncode == 0 and mp3_path.exists():
            wav_path.unlink()
            return mp3_path
    except Exception:
        pass
    logger.warning("[audio] ffmpeg conversion failed, keeping wav")
    return None
