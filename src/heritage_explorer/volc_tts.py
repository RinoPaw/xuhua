"""Server-side TTS: Volcengine + OpenAI-compatible fallback."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import re
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from urllib import request

from . import config

LOGGER = logging.getLogger(__name__)


class VolcTTSError(RuntimeError):
    """Raised when server-side TTS synthesis fails."""


@dataclass(frozen=True)
class TTSAudio:
    path: Path
    mime_type: str
    engine: str = "volcengine"


def openai_tts_available() -> bool:
    """True when explicitly enabled and AI API key is configured."""
    return config.OPENAI_TTS_ENABLED and bool(config.AI_API_KEY) and bool(config.AI_BASE_URL)


def server_tts_available() -> bool:
    """True when any server-side TTS engine is available."""
    return volc_tts_available() or openai_tts_available()


def server_tts_engine() -> str:
    if volc_tts_available():
        return "volcengine"
    if openai_tts_available():
        return "openai"
    return "browser"


def volc_tts_available() -> bool:
    if not config.VOLC_TTS_ENABLED:
        return False
    if _use_v3_api():
        return bool(config.VOLC_TTS_API_KEY or (config.VOLC_TTS_APP_ID and config.VOLC_TTS_ACCESS_TOKEN))
    return bool(config.VOLC_TTS_APP_ID and config.VOLC_TTS_ACCESS_TOKEN and config.VOLC_TTS_CLUSTER)


def synthesize_speech_to_file(text: str) -> TTSAudio | None:
    text = _clean_text(text)
    if not text:
        return None

    cache_dir = config.TTS_CACHE_DIR
    cache_dir.mkdir(parents=True, exist_ok=True)
    encoding = "mp3"  # OpenAI TTS uses mp3; Volcengine configured encoding
    if volc_tts_available():
        encoding = config.VOLC_TTS_ENCODING
    path = cache_dir / f"{_cache_key(text)}.{encoding}"
    if path.is_file() and path.stat().st_size > 0:
        engine = "volcengine" if volc_tts_available() else "openai"
        return TTSAudio(path=path, mime_type=_mime_type(encoding), engine=engine)

    if volc_tts_available():
        audio = b"".join(_synthesize_chunk(chunk) for chunk in _text_chunks(text))
        if not audio:
            raise VolcTTSError("Volcengine TTS returned empty audio")
        path.write_bytes(audio)
        return TTSAudio(path=path, mime_type=_mime_type(encoding), engine="volcengine")

    if openai_tts_available():
        return _openai_synthesize(text, path)

    return None


def stream_speech_audio(text: str) -> Iterator[bytes] | None:
    text = _clean_text(text)
    if not text:
        return None
    if volc_tts_available():
        return _stream_chunks(text)
    if openai_tts_available():
        audio = _openai_tts_bytes(text)
        if audio:
            return _chunk_bytes(audio)
    return None


def _openai_synthesize(text: str, path: Path) -> TTSAudio | None:
    audio = _openai_tts_bytes(text)
    if not audio:
        return None
    path.write_bytes(audio)
    return TTSAudio(path=path, mime_type="audio/mpeg", engine="openai")


def _openai_tts_bytes(text: str) -> bytes | None:
    """Call OpenAI-compatible /v1/audio/speech endpoint."""
    import httpx

    url = config.AI_BASE_URL.rstrip("/") + "/v1/audio/speech"
    payload = {
        "model": "tts-1",
        "input": text,
        "voice": "nova",
        "response_format": "mp3",
        "speed": 1.0,
    }
    headers = {
        "Authorization": f"Bearer {config.AI_API_KEY}",
        "Content-Type": "application/json",
    }
    try:
        client = httpx.Client(timeout=httpx.Timeout(30.0))
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        return response.content
    except Exception as exc:
        LOGGER.warning("OpenAI TTS failed: %s", exc)
        return None


def _chunk_bytes(data: bytes, size: int = 32768) -> Iterator[bytes]:
    for i in range(0, len(data), size):
        yield data[i : i + size]


def valid_tts_filename(filename: str) -> bool:
    suffix = re.escape(config.VOLC_TTS_ENCODING)
    return bool(re.fullmatch(rf"[a-f0-9]{{64}}\.{suffix}", filename))


def _synthesize_chunk(text: str) -> bytes:
    if _use_v3_api():
        return _synthesize_v3_chunk(text)
    return _synthesize_v1_chunk(text)


def _stream_chunks(text: str) -> Iterator[bytes]:
    for chunk in _text_chunks(text):
        yield from _stream_synthesize_chunk(chunk)


def _stream_synthesize_chunk(text: str) -> Iterator[bytes]:
    if _use_v3_api():
        yield from _stream_v3_chunk(text)
    else:
        yield _synthesize_v1_chunk(text)


def _synthesize_v1_chunk(text: str) -> bytes:
    payload = _v1_request_payload(text)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer;{config.VOLC_TTS_ACCESS_TOKEN}",
    }
    req = request.Request(config.VOLC_TTS_ENDPOINT, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=config.VOLC_TTS_TIMEOUT) as response:
            response_body = response.read()
    except Exception as exc:  # noqa: BLE001 - TTS must not leak vendor/client internals upward.
        raise VolcTTSError("Volcengine TTS request failed") from exc

    try:
        data = json.loads(response_body.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise VolcTTSError("Volcengine TTS returned invalid JSON") from exc

    if data.get("code") != 3000:
        message = str(data.get("message") or data.get("Message") or "unknown error")
        raise VolcTTSError(f"Volcengine TTS failed: {message}")
    audio_base64 = str(data.get("data") or "")
    if audio_base64.startswith("data:"):
        audio_base64 = audio_base64.split(",", 1)[1]
    try:
        return base64.b64decode(audio_base64)
    except ValueError as exc:
        raise VolcTTSError("Volcengine TTS returned invalid audio") from exc


def _synthesize_v3_chunk(text: str) -> bytes:
    payload = _v3_request_payload(text)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = _v3_headers()
    req = request.Request(config.VOLC_TTS_V3_ENDPOINT, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=config.VOLC_TTS_TIMEOUT) as response:
            response_body = response.read()
    except Exception as exc:  # noqa: BLE001 - TTS must not leak vendor/client internals upward.
        raise VolcTTSError("Volcengine TTS v3 request failed") from exc
    return _decode_v3_audio(response_body)


def _stream_v3_chunk(text: str) -> Iterator[bytes]:
    payload = _v3_request_payload(text)
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = _v3_headers()
    req = request.Request(config.VOLC_TTS_V3_ENDPOINT, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=config.VOLC_TTS_TIMEOUT) as response:
            yielded = False
            for data in _iter_v3_response_events(response):
                audio = _audio_from_v3_event(data)
                if audio:
                    yielded = True
                    yield audio
    except Exception as exc:  # noqa: BLE001 - TTS must not leak vendor/client internals upward.
        raise VolcTTSError("Volcengine TTS v3 stream failed") from exc
    if not yielded:
        raise VolcTTSError("Volcengine TTS v3 stream returned empty audio")


def _v3_headers() -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "Connection": "keep-alive",
        "X-Api-Resource-Id": config.VOLC_TTS_RESOURCE_ID,
        "X-Api-Request-Id": str(uuid.uuid4()),
    }
    if config.VOLC_TTS_API_KEY:
        headers["X-Api-Key"] = config.VOLC_TTS_API_KEY
    else:
        headers["X-Api-App-Key"] = config.VOLC_TTS_APP_ID
        headers["X-Api-Access-Key"] = config.VOLC_TTS_ACCESS_TOKEN
    return headers


def _decode_v3_audio(response_body: bytes) -> bytes:
    audio = bytearray()
    for data in _v3_response_events(response_body):
        audio.extend(_audio_from_v3_event(data))
    if not audio:
        raise VolcTTSError("Volcengine TTS v3 returned empty audio")
    return bytes(audio)


def _v3_response_events(response_body: bytes) -> list[dict]:
    text = response_body.decode("utf-8", errors="replace").strip()
    if not text:
        return []
    try:
        return [json.loads(text)]
    except json.JSONDecodeError:
        pass

    events: list[dict] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line == "[DONE]":
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _iter_v3_response_events(response) -> Iterator[dict]:
    buffer = ""
    for raw_line in response:
        line = raw_line.decode("utf-8", errors="replace").strip()
        if not line or line.startswith(":"):
            continue
        if line.startswith("data:"):
            line = line[5:].strip()
        if not line or line == "[DONE]":
            continue
        candidate = buffer + line
        try:
            yield json.loads(candidate)
            buffer = ""
        except json.JSONDecodeError:
            buffer = candidate
    if buffer:
        try:
            yield json.loads(buffer)
        except json.JSONDecodeError:
            return


def _audio_from_v3_event(data: dict) -> bytes:
    code = data.get("code", 0)
    if code and code != 20000000:
        message = str(data.get("message") or data.get("msg") or "unknown error")
        raise VolcTTSError(f"Volcengine TTS v3 failed: {message}")
    audio_base64 = str(data.get("data") or data.get("audio") or "")
    if not audio_base64:
        return b""
    try:
        return base64.b64decode(audio_base64)
    except ValueError as exc:
        raise VolcTTSError("Volcengine TTS v3 returned invalid audio") from exc


def _v1_request_payload(text: str) -> dict:
    audio = {
        "voice_type": config.VOLC_TTS_VOICE_TYPE,
        "encoding": config.VOLC_TTS_ENCODING,
        "rate": config.VOLC_TTS_RATE,
        "speed_ratio": config.VOLC_TTS_SPEED_RATIO,
        "volume_ratio": config.VOLC_TTS_VOLUME_RATIO,
        "pitch_ratio": config.VOLC_TTS_PITCH_RATIO,
    }
    if config.VOLC_TTS_EMOTION:
        audio["emotion"] = config.VOLC_TTS_EMOTION
    return {
        "app": {
            "appid": config.VOLC_TTS_APP_ID,
            "token": config.VOLC_TTS_ACCESS_TOKEN,
            "cluster": config.VOLC_TTS_CLUSTER,
        },
        "user": {"uid": "xuhua-web"},
        "audio": audio,
        "request": {
            "reqid": str(uuid.uuid4()),
            "text": text,
            "text_type": "plain",
            "operation": "query",
        },
    }


def _v3_request_payload(text: str) -> dict:
    req_params = {
        "text": text,
        "speaker": config.VOLC_TTS_VOICE_TYPE,
        "audio_params": {
            "format": config.VOLC_TTS_ENCODING,
            "sample_rate": config.VOLC_TTS_RATE,
            "speech_rate": _ratio_to_percent(config.VOLC_TTS_SPEED_RATIO),
            "loudness_rate": _ratio_to_percent(config.VOLC_TTS_VOLUME_RATIO),
        },
    }
    if config.VOLC_TTS_EMOTION:
        req_params["emotion"] = config.VOLC_TTS_EMOTION
        req_params["emotion_scale"] = config.VOLC_TTS_EMOTION_SCALE
    return {
        "user": {"uid": "xuhua-web"},
        "req_params": req_params,
    }


def _use_v3_api() -> bool:
    version = str(config.VOLC_TTS_API_VERSION or "auto").strip().lower()
    return version == "v3" or (version == "auto" and bool(config.VOLC_TTS_API_KEY))


def _ratio_to_percent(value: float) -> int:
    return round((float(value) - 1.0) * 100)


def _text_chunks(text: str) -> list[str]:
    max_bytes = max(120, config.VOLC_TTS_MAX_CHUNK_BYTES)
    chunks: list[str] = []
    current = ""
    for piece in _sentence_pieces(text):
        candidate = current + piece
        if current and len(candidate.encode("utf-8")) > max_bytes:
            chunks.append(current.strip())
            current = piece
        else:
            current = candidate
        while len(current.encode("utf-8")) > max_bytes:
            head, current = _split_by_bytes(current, max_bytes)
            chunks.append(head.strip())
    if current.strip():
        chunks.append(current.strip())
    return chunks or [text]


def _sentence_pieces(text: str) -> list[str]:
    pieces = re.split(r"([。！？!?；;])", text)
    result: list[str] = []
    for index in range(0, len(pieces), 2):
        sentence = pieces[index]
        mark = pieces[index + 1] if index + 1 < len(pieces) else ""
        piece = f"{sentence}{mark}".strip()
        if piece:
            result.append(piece)
    return result


def _split_by_bytes(text: str, max_bytes: int) -> tuple[str, str]:
    size = 0
    split_at = 0
    for index, char in enumerate(text):
        size += len(char.encode("utf-8"))
        if size > max_bytes:
            break
        split_at = index + 1
    split_at = max(split_at, 1)
    return text[:split_at], text[split_at:]


def _cache_key(text: str) -> str:
    options = {
        "api_version": "v3" if _use_v3_api() else "v1",
        "resource_id": config.VOLC_TTS_RESOURCE_ID,
        "voice_type": config.VOLC_TTS_VOICE_TYPE,
        "emotion": config.VOLC_TTS_EMOTION,
        "emotion_scale": config.VOLC_TTS_EMOTION_SCALE,
        "encoding": config.VOLC_TTS_ENCODING,
        "rate": config.VOLC_TTS_RATE,
        "speed_ratio": config.VOLC_TTS_SPEED_RATIO,
        "volume_ratio": config.VOLC_TTS_VOLUME_RATIO,
        "pitch_ratio": config.VOLC_TTS_PITCH_RATIO,
        "text": text,
    }
    raw = json.dumps(options, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _mime_type(encoding: str = "") -> str:
    enc = (encoding or config.VOLC_TTS_ENCODING).lower()
    return {
        "mp3": "audio/mpeg",
        "ogg": "audio/ogg",
        "opus": "audio/ogg",
        "wav": "audio/wav",
        "pcm": "audio/L16",
    }.get(enc, "application/octet-stream")
