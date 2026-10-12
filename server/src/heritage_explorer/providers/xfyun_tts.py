"""Official iFLYTEK streaming TTS over authenticated WebSocket.

The service is independent from ASR; enabling ASR does not automatically
authorize TTS voices. We reuse app credentials by default, with optional
TTS-specific overrides from the environment.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import json
import logging
import os

from websockets.asyncio.client import connect

from ..config import XF_API_KEY, XF_API_SECRET, XF_APP_ID
from ..xfyun_protocol import signed_url

LOGGER = logging.getLogger(__name__)
HOST = "tts-api.xfyun.cn"
PATH = "/v2/tts"
MAX_TEXT_BYTES = 7999
MAX_AUDIO_BYTES = 16 * 1024 * 1024
DEFAULT_MANDARIN_VOICE = "x4_yezi"  # 讯飞小露 (Mandarin voice)
FIRST_AUDIO_TIMEOUT = 12.0
STREAM_TIMEOUT = 30.0


class TtsProviderError(RuntimeError):
    """Provider failure whose message never includes text or credentials."""

    def __init__(self, reason: str, *, code: int | None = None) -> None:
        super().__init__(reason)
        self.code = code


def voice_for(edge_voice: str) -> str:
    """Select an explicitly enabled iFLYTEK voice; never send Edge voice IDs."""
    if edge_voice.startswith("zh-HK-"):
        return os.environ.get("XF_TTS_VOICE_YUE", "").strip() or "xiaoyan"
    if edge_voice.startswith("en-"):
        return os.environ.get("XF_TTS_VOICE_EN", "").strip() or "xiaoyan"
    if edge_voice.startswith("ja-"):
        return os.environ.get("XF_TTS_VOICE_JA", "").strip() or "xiaoyan"
    if edge_voice.startswith("ko-"):
        return os.environ.get("XF_TTS_VOICE_KO", "").strip() or "xiaoyan"
    return os.environ.get("XF_TTS_VOICE_ZH", "").strip() or DEFAULT_MANDARIN_VOICE


class Communicate:
    """Edge-compatible constructor for the existing TTS endpoint boundary."""

    def __init__(self, text: str, *, voice: str, rate: str, pitch: str) -> None:
        self.text = text
        self.vcn = voice_for(voice)
        self.app_id = os.environ.get("XF_TTS_APP_ID", "").strip() or XF_APP_ID.strip()
        self.api_key = os.environ.get("XF_TTS_API_KEY", "").strip() or XF_API_KEY.strip()
        self.api_secret = os.environ.get("XF_TTS_API_SECRET", "").strip() or XF_API_SECRET.strip()
        # No forwarding Edge-specific speaking-rate/pitch strings to iFLYTEK.
        self.speed = 50
        self.pitch = 50

    async def stream(self):
        if not (self.app_id and self.api_key and self.api_secret):
            raise TtsProviderError("tts_provider_unconfigured")
        encoded = self.text.encode("utf-8")
        if not 0 < len(encoded) <= MAX_TEXT_BYTES:
            raise TtsProviderError("tts_text_too_long")
        if not self.vcn or len(self.vcn) > 64 or not all(
            char.isascii() and (char.isalnum() or char in "_-") for char in self.vcn
        ):
            raise TtsProviderError("tts_voice_invalid")

        url = signed_url(
            host=HOST, path=PATH, api_key=self.api_key, api_secret=self.api_secret
        )
        payload = {
            "common": {"app_id": self.app_id},
            "business": {
                "aue": "lame", "sfl": 1, "auf": "audio/L16;rate=16000",
                "tte": "UTF8", "vcn": self.vcn,
                "speed": self.speed, "pitch": self.pitch,
            },
            "data": {"status": 2, "text": base64.b64encode(encoded).decode("ascii")},
        }
        try:
            async with connect(
                url, open_timeout=8, close_timeout=1, max_size=2**20,
            ) as socket:
                await asyncio.wait_for(socket.send(json.dumps(payload)), timeout=5)
                received = 0
                finished = False
                first = True
                while not finished:
                    raw = await asyncio.wait_for(
                        socket.recv(), timeout=FIRST_AUDIO_TIMEOUT if first else STREAM_TIMEOUT
                    )
                    if not isinstance(raw, str):
                        raise TtsProviderError("tts_invalid_frame")
                    try:
                        packet = json.loads(raw)
                    except (ValueError, TypeError):
                        raise TtsProviderError("tts_invalid_json") from None
                    if not isinstance(packet, dict):
                        raise TtsProviderError("tts_invalid_json")
                    code = packet.get("code")
                    if type(code) is not int:
                        raise TtsProviderError("tts_invalid_response")
                    if code != 0:
                        # Never surface upstream message; it can contain PII.
                        raise TtsProviderError("tts_provider_rejected", code=code)
                    data = packet.get("data")
                    if data is None:
                        continue
                    if not isinstance(data, dict):
                        raise TtsProviderError("tts_invalid_response")
                    audio = data.get("audio", "")
                    if audio:
                        if not isinstance(audio, str):
                            raise TtsProviderError("tts_invalid_audio")
                        try:
                            chunk = base64.b64decode(audio, validate=True)
                        except (ValueError, binascii.Error):
                            raise TtsProviderError("tts_invalid_audio") from None
                        received += len(chunk)
                        if received > MAX_AUDIO_BYTES:
                            raise TtsProviderError("tts_audio_too_large")
                        if chunk:
                            first = False
                            yield {"type": "audio", "data": chunk}
                    status = data.get("status")
                    if status == 2:
                        finished = True
                    elif status not in (None, 1):
                        raise TtsProviderError("tts_invalid_status")
                if received == 0:
                    raise TtsProviderError("tts_provider_no_audio")
        except asyncio.CancelledError:
            raise
        except TtsProviderError:
            raise
        except Exception as exc:
            LOGGER.warning("tts.socket.failed type=%s", type(exc).__name__)
            raise TtsProviderError("tts_provider_unavailable") from None
