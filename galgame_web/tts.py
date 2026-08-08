import asyncio
import base64
import contextvars
import json
import os
import pathlib
import re
import subprocess
import time
import uuid

from astrbot.api import logger

from . import session_helpers
from .async_utils import run_in_thread_to_completion
from .audio_utils import convert_audio, detect_audio_mime, ext_for_mime
from .session_helpers import concatenate_wav_files
from .utils import EMOTION_PATTERN, extract_all_emotions, get_emotion_tags

_TTS_TEMP_OUTPUTS: contextvars.ContextVar[list[pathlib.Path] | None] = (
    contextvars.ContextVar("galgame_tts_temp_outputs", default=None)
)


def _get_astrbot_temp_dir() -> pathlib.Path:
    from astrbot.core.utils.astrbot_path import get_astrbot_data_path

    return pathlib.Path(get_astrbot_data_path()) / "temp"


def _cleanup_tts_temp_path(path: pathlib.Path | str | None) -> bool:
    """Delete only TTS scratch files owned by AstrBot's temp directory."""
    if not path:
        return False
    try:
        candidate_path = pathlib.Path(path)
        if candidate_path.is_symlink():
            return False
        candidate = candidate_path.resolve()
        temp_root = _get_astrbot_temp_dir().resolve()
        audio_root = session_helpers.AUDIO_DIR.resolve()
        candidate.relative_to(temp_root)
        try:
            candidate.relative_to(audio_root)
            return False
        except ValueError:
            pass
        if not candidate.is_file():
            return False
        candidate.unlink()
        return True
    except (OSError, RuntimeError, TypeError, ValueError):
        return False


def _register_tts_temp_output(path: pathlib.Path | str | None):
    if not path:
        return path
    output = pathlib.Path(path)
    tracked = _TTS_TEMP_OUTPUTS.get()
    if tracked is not None:
        tracked.append(output)
    return output


def _cleanup_tts_paths(
    paths: list[pathlib.Path], keep: pathlib.Path | None = None
) -> None:
    try:
        keep_resolved = keep.resolve() if keep and keep.exists() else None
    except (OSError, RuntimeError):
        keep_resolved = None
    for path in paths:
        try:
            if keep_resolved is not None and path.resolve() == keep_resolved:
                continue
        except (OSError, RuntimeError):
            continue
        _cleanup_tts_temp_path(path)


def split_sentences(text: str):
    parts = re.split(r"(?<=[。！？…~])\s*|(?<=[\.!\?])\s+", text)
    return [p for p in parts if p.strip()]


def build_tagged_text(text: str, emotions: list, emotion_map: dict) -> str:
    groups: dict[int, list[str]] = {}
    for emo_label, char_pos in emotions:
        groups.setdefault(char_pos, []).append(emo_label)
    sorted_positions = sorted(groups)
    if not sorted_positions:
        return f"[neutral]{text.strip()}" if text.strip() else text

    result_parts: list[str] = []
    cursor = 0
    current_emotions = groups[sorted_positions[0]]

    for pos in sorted_positions:
        tags = groups[pos]
        seg_text = text[cursor:pos].strip()
        if seg_text and current_emotions:
            for emo in current_emotions:
                fish_emo = emotion_map.get(emo, emo)
                result_parts.append(f"[{fish_emo}]")
            result_parts.append(seg_text)
        cursor = pos
        current_emotions = tags

    tail = text[cursor:].strip()
    if tail or not result_parts:
        for emo in current_emotions:
            fish_emo = emotion_map.get(emo, emo)
            result_parts.append(f"[{fish_emo}]")
        result_parts.append(tail or text.strip())

    return "".join(result_parts)


def build_sentence_tagged_texts(clean_text, emotions_all, emotion_map):
    sentences = split_sentences(clean_text)
    if len(sentences) <= 1:
        if emotions_all:
            return [build_tagged_text(clean_text, emotions_all, emotion_map)]
        return [f"[neutral]{clean_text}"]
    cursor = 0
    result = []
    for sent in sentences:
        sent_start = clean_text.index(sent, cursor)
        if emotions_all:
            sent_end_field = sent_start + len(sent)
            sent_emotions = [
                (tag, pos)
                for tag, pos in emotions_all
                if sent_start <= pos < sent_end_field
            ]
        else:
            sent_emotions = []
        if sent_emotions:
            forced = [(tag, 0) for tag, _ in sent_emotions]
            tagged = build_tagged_text(sent, forced, emotion_map)
        else:
            tagged = f"[neutral]{sent}"
        result.append(tagged)
        cursor = sent_start + len(sent)
    return result


async def parallel_tts(clean_text, emotions_all, emotion_map, tts_provider):
    tagged_sentences = build_sentence_tagged_texts(
        clean_text, emotions_all, emotion_map
    )
    logger.debug(f"[bg-tts] parallel sentence_count={len(tagged_sentences)}")
    if len(tagged_sentences) <= 1:
        path = await tts_provider.get_audio(tagged_sentences[0])
        output = pathlib.Path(path) if path else None
        return (
            _register_tts_temp_output(output) if output and output.is_file() else None
        )

    sem = asyncio.Semaphore(5)

    async def _do_one(ts):
        async with sem:
            return await tts_provider.get_audio(ts)

    tasks = [_do_one(ts) for ts in tagged_sentences]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    paths: list[pathlib.Path] = []
    for r in results:
        if isinstance(r, (str, os.PathLike)) and pathlib.Path(r).is_file():
            paths.append(_register_tts_temp_output(pathlib.Path(r)))
        elif isinstance(r, Exception):
            logger.warning(f"[bg-tts] parallel TTS sentence failed: {r}")

    all_sentences_succeeded = len(paths) == len(tagged_sentences)
    if all_sentences_succeeded:
        try:
            combined = await run_in_thread_to_completion(concat_audio, paths)
        except Exception as exc:
            logger.warning(f"[bg-tts] sentence audio merge failed: {exc}")
            combined = None
        if combined:
            return _register_tts_temp_output(combined)
    else:
        logger.warning(
            "[bg-tts] one or more sentence TTS calls failed; retrying full text"
        )

    if emotions_all:
        fallback_text = build_tagged_text(clean_text, emotions_all, emotion_map)
    else:
        fallback_text = f"[neutral]{clean_text}"
    fallback_path = None
    try:
        fallback_result = await tts_provider.get_audio(fallback_text)
        fallback_path = pathlib.Path(fallback_result) if fallback_result else None
    except Exception as exc:
        logger.warning(f"[bg-tts] full-text fallback failed: {exc}")
    finally:
        used_fallback = bool(fallback_path and fallback_path.is_file())
        _cleanup_tts_paths(paths, fallback_path if used_fallback else None)

    if used_fallback:
        return _register_tts_temp_output(fallback_path)
    logger.warning("[bg-tts] full-text fallback returned no usable audio")
    return None


def concat_audio(paths):
    wav_output = _register_tts_temp_output(paths[0].parent / f"{uuid.uuid4().hex}.wav")
    if concatenate_wav_files(paths, wav_output):
        for path in paths:
            _cleanup_tts_temp_path(path)
        return wav_output

    concat_file = paths[0].parent / f"_concat_{uuid.uuid4().hex}.txt"
    suffix = paths[0].suffix.lower() or ".wav"
    output = _register_tts_temp_output(paths[0].parent / f"{uuid.uuid4().hex}{suffix}")
    with open(concat_file, "w", encoding="utf-8") as f:
        for p in paths:
            f.write(f"file '{p}'\n")
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(concat_file),
                "-c",
                "copy",
                str(output),
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0 and output.exists():
            for p in paths:
                _cleanup_tts_temp_path(p)
            return output
    except Exception:
        pass
    finally:
        try:
            concat_file.unlink()
        except OSError:
            pass
    _cleanup_tts_temp_path(output)
    return None


def select_tts_provider(config, context):
    tts_provider_id = config.get("tts_provider", "").strip()
    if tts_provider_id:
        return context.provider_manager.inst_map.get(tts_provider_id)
    return context.get_using_tts_provider()


def parse_tts_emotion_map(config) -> dict:
    try:
        return json.loads(config.get("tts_emotion_map", "{}") or "{}")
    except (json.JSONDecodeError, TypeError):
        return {}


async def synthesize_audio(clean_text, emotions_all, tts_provider, config):
    """Pure TTS engine: parallel synthesis + persist to AUDIO_DIR + optional
    mp3 conversion. Callers own all short-circuit decisions (tts_enabled,
    empty text, command, provider availability) because they must preserve
    the pipeline audio fallback. Temp outputs are tracked and cleaned here.
    """
    tracked: list[pathlib.Path] = []
    token = _TTS_TEMP_OUTPUTS.set(tracked)
    try:
        if not tts_provider:
            return "", "", ""

        tts_emotion_map = parse_tts_emotion_map(config)

        t0 = time.time()
        audio_path = await parallel_tts(
            clean_text, emotions_all, tts_emotion_map, tts_provider
        )
        if not audio_path:
            logger.warning("[tts] TTS returned no audio")
            return "", "", ""

        raw = pathlib.Path(audio_path).read_bytes()
        mime = detect_audio_mime(raw)
        audio_b64 = base64.b64encode(raw).decode()
        audio_mime_val = mime
        session_helpers.AUDIO_DIR.mkdir(parents=True, exist_ok=True)
        audio_file = f"{uuid.uuid4().hex}{ext_for_mime(mime)}"
        (session_helpers.AUDIO_DIR / audio_file).write_bytes(raw)
        if config.get("audio_format", "wav") == "mp3":
            converted = await run_in_thread_to_completion(
                convert_audio, session_helpers.AUDIO_DIR / audio_file
            )
            if converted:
                audio_file = converted.name
                raw = converted.read_bytes()
                mime = "audio/mpeg"
                audio_b64 = base64.b64encode(raw).decode()
                audio_mime_val = mime
        logger.info(
            f"[tts] synthesized {len(raw)} bytes, {mime} in {time.time() - t0:.1f}s"
        )
        return audio_b64, audio_mime_val, audio_file
    finally:
        for path in tracked:
            _cleanup_tts_temp_path(path)
        _TTS_TEMP_OUTPUTS.reset(token)


async def bg_tts(raw_text: str, session: dict, config: dict, context) -> None:
    """Background TTS: clean raw_text, resolve provider, then synthesize and
    store the result in session["_bg_tts_result"]. Temp output cleanup is
    handled inside synthesize_audio."""
    try:
        emotion_tags = get_emotion_tags(config)

        clean_text = re.sub(EMOTION_PATTERN, "", raw_text)
        clean_text = re.sub(r"\([a-z-]+\)", "", clean_text)
        clean_text = re.sub(r"<#\d+\.?\d*#>", "", clean_text).strip()

        if not clean_text:
            session["_bg_tts_result"] = ("", "", "")
            return

        _, _, emotions_all = extract_all_emotions(raw_text, emotion_tags)

        tts_provider = select_tts_provider(config, context)
        if not tts_provider:
            session["_bg_tts_result"] = ("", "", "")
            return

        logger.debug(
            f"[bg-tts] calling parallel TTS clean_len={len(clean_text)} "
            f"emotion_count={len(emotions_all)}"
        )
        audio_b64, audio_mime_val, audio_file = await synthesize_audio(
            clean_text, emotions_all, tts_provider, config
        )
        session["_bg_tts_result"] = (audio_b64, audio_mime_val, audio_file)
    except Exception as e:
        logger.warning(f"[bg-tts] synthesis failed: {e}")
        session["_bg_tts_result"] = ("", "", "")
