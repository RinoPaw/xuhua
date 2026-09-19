"""Streaming Xunfei ASR transport for browser-captured 16 kHz PCM audio.

叙华只使用讯飞“中英识别大模型”这一条实时识别链路。该模型本身支持
普通话、英语以及 202 种中文方言免切换识别。
"""

from __future__ import annotations

import asyncio
import base64
from collections.abc import Awaitable, Callable
import json
import logging

from websockets.asyncio.client import ClientConnection, connect

from .xfyun_protocol import (
    TranscriptAccumulator,
    extract_candidates,
    extract_language,
    extract_text,
    format_hotwords,
    is_last_result,
    is_status_two,
    signed_url as build_signed_url,
)


LOGGER = logging.getLogger(__name__)


class VoiceProviderError(RuntimeError):
    """Provider failure without secret-bearing diagnostic text."""


class _FinishRequest:
    """A queue barrier used to serialize the Xunfei status=2 packet."""

    def __init__(self) -> None:
        self.done: asyncio.Future[None] = asyncio.get_running_loop().create_future()


class XfyunStream:
    """One utterance over Xunfei's streaming IAT WebSocket protocol."""

    path = "/v1"
    chunk_size = 1280
    frame_interval = 0.04

    def __init__(
        self,
        *,
        app_id: str,
        api_key: str,
        api_secret: str,
        host: str,
        on_partial: Callable[[str], Awaitable[None]] | None = None,
        hotwords: str | list[str] | tuple[str, ...] | None = None,
        path: str = "/v1",
        language: str = "zh_cn",
        accent: str = "mandarin",
        domain: str = "slm",
        dynamic_correction: bool = True,
        eos: int = 1800,
    ) -> None:
        self.app_id = app_id.strip()
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.host = host.strip()
        self.path = str(path or "/v1").strip()
        self.language = str(language or "zh_cn").strip()
        self.accent = str(accent or "mandarin").strip()
        self.domain = str(domain or "slm").strip()
        self.dynamic_correction = bool(dynamic_correction)
        self.eos = min(max(int(eos), 600), 10000)
        self._hotword_spec = self._format_hotwords(hotwords)
        self._socket: ClientConnection | None = None
        self._receiver: asyncio.Task[None] | None = None
        self._sender: asyncio.Task[None] | None = None
        self._done = asyncio.Event()
        self._buffer = bytearray()
        self._send_queue: asyncio.Queue[bytes | _FinishRequest] = asyncio.Queue()
        self._send_lock = asyncio.Lock()
        self._transcript = TranscriptAccumulator()
        # Keep the old internal dictionaries as aliases for debugging and any
        # downstream tests that inspected them before the protocol extraction.
        self._pieces = self._transcript.pieces
        self._candidate_pieces = self._transcript.candidate_pieces
        self._language_pieces = self._transcript.language_pieces
        self._sequence = 0
        self._first = True
        self._has_audio = False
        self._next_send_at: float | None = None
        self._send_failure: VoiceProviderError | None = None
        self._closed = False
        self._error = False
        self._on_partial = on_partial

    @property
    def configured(self) -> bool:
        return bool(self.app_id and self.api_key and self.api_secret and self.host)

    @staticmethod
    def _format_hotwords(hotwords: str | list[str] | tuple[str, ...] | None) -> str:
        return format_hotwords(hotwords)

    def signed_url(self) -> str:
        return build_signed_url(
            host=self.host,
            path=self.path,
            api_key=self.api_key,
            api_secret=self.api_secret,
        )

    async def start(self) -> None:
        if not self.configured:
            raise VoiceProviderError("voice_provider_unconfigured")
        async with self._send_lock:
            if self._closed:
                raise VoiceProviderError("voice_stream_closed")
        try:
            socket = await connect(
                self.signed_url(), open_timeout=10, close_timeout=2, max_size=2**20
            )
        except Exception as exc:
            raise VoiceProviderError("voice_provider_unavailable") from exc
        should_close = False
        async with self._send_lock:
            if self._closed:
                should_close = True
            else:
                self._socket = socket
                self._next_send_at = None
                self._receiver = asyncio.create_task(self._receive())
                self._sender = asyncio.create_task(self._send_loop())
                self._enqueue_complete_frames()
        if should_close:
            await socket.close()
            raise VoiceProviderError("voice_stream_closed")
        await asyncio.sleep(0)

    async def send_audio(self, data: bytes) -> None:
        if not data:
            return
        async with self._send_lock:
            if self._closed:
                return
            self._has_audio = True
            self._buffer.extend(data)
            if self._socket is not None:
                self._enqueue_complete_frames()

    def _enqueue_complete_frames(self) -> None:
        while len(self._buffer) >= self.chunk_size:
            frame = bytes(self._buffer[: self.chunk_size])
            del self._buffer[: self.chunk_size]
            self._send_queue.put_nowait(frame)

    async def _send_loop(self) -> None:
        current: bytes | _FinishRequest | None = None
        try:
            while True:
                current = await self._send_queue.get()
                if isinstance(current, _FinishRequest):
                    if self._socket is None:
                        raise VoiceProviderError("voice_provider_disconnected")
                    if self._send_failure is not None:
                        raise self._send_failure
                    try:
                        await self._socket.send(json.dumps(self._last_packet()))
                    except Exception as exc:
                        raise VoiceProviderError("voice_provider_disconnected") from exc
                    if not current.done.done():
                        current.done.set_result(None)
                    current = None
                    continue

                now = asyncio.get_running_loop().time()
                while self._next_send_at is not None and self._next_send_at > now:
                    await asyncio.sleep(self._next_send_at - now)
                    now = asyncio.get_running_loop().time()
                await self._send_frame(current)
                self._next_send_at = asyncio.get_running_loop().time() + self.frame_interval
                current = None
        except asyncio.CancelledError:
            if isinstance(current, _FinishRequest) and not current.done.done():
                current.done.cancel()
            raise
        except Exception as exc:
            failure = (
                exc
                if isinstance(exc, VoiceProviderError)
                else VoiceProviderError("voice_provider_disconnected")
            )
            self._send_failure = failure
            self._error = True
            self._done.set()
            if isinstance(current, _FinishRequest) and not current.done.done():
                current.done.set_exception(failure)
            while True:
                try:
                    pending = self._send_queue.get_nowait()
                except asyncio.QueueEmpty:
                    break
                if isinstance(pending, _FinishRequest) and not pending.done.done():
                    pending.done.set_exception(failure)

    async def finish(self) -> str:
        try:
            async with self._send_lock:
                if self._socket is None:
                    raise VoiceProviderError("voice_stream_not_started")
                if self._send_failure is not None:
                    raise self._send_failure
                self._enqueue_complete_frames()
                if self._buffer:
                    self._send_queue.put_nowait(bytes(self._buffer))
                    self._buffer.clear()
                empty = not self._has_audio
                sender = self._sender
                if not empty:
                    if sender is None or sender.done():
                        raise VoiceProviderError("voice_provider_disconnected")
                    request = _FinishRequest()
                    self._send_queue.put_nowait(request)
            if empty:
                return ""
            await asyncio.shield(request.done)
            await asyncio.wait_for(self._done.wait(), timeout=8)
        except TimeoutError as exc:
            raise VoiceProviderError("voice_provider_timeout") from exc
        finally:
            await self.close()
        if self._error:
            raise VoiceProviderError("voice_provider_failed")
        return self.current_text()

    async def close(self) -> None:
        async with self._send_lock:
            self._closed = True
            socket, self._socket = self._socket, None
            sender, self._sender = self._sender, None
            receiver, self._receiver = self._receiver, None
            pending = []
            while True:
                try:
                    pending.append(self._send_queue.get_nowait())
                except asyncio.QueueEmpty:
                    break
            self._buffer.clear()
        for item in pending:
            if isinstance(item, _FinishRequest) and not item.done.done():
                item.done.cancel()
        if sender is not None and sender is not asyncio.current_task():
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)
        if socket is not None:
            try:
                await socket.close()
            except Exception:
                LOGGER.info("asr.socket.close_failed", exc_info=True)
        if receiver is not None and receiver is not asyncio.current_task():
            receiver.cancel()
            await asyncio.gather(receiver, return_exceptions=True)

    async def _send_frame(self, frame: bytes) -> None:
        if self._socket is None:
            return
        audio = base64.b64encode(frame).decode()
        packet = self._first_packet(audio) if self._first else self._middle_packet(audio)
        self._first = False
        try:
            await self._socket.send(json.dumps(packet))
        except Exception as exc:
            self._error = True
            self._done.set()
            raise VoiceProviderError("voice_provider_disconnected") from exc

    async def _receive(self) -> None:
        assert self._socket is not None
        try:
            async for raw in self._socket:
                message = json.loads(raw)
                header = message.get("header", {})
                if header.get("code", -1) != 0:
                    self._error = True
                    self._done.set()
                    return
                result = message.get("payload", {}).get("result") or {}
                encoded = result.get("text")
                decoded: dict[str, object] | None = None
                if encoded:
                    decoded_value = json.loads(base64.b64decode(encoded).decode())
                    if isinstance(decoded_value, dict):
                        decoded = decoded_value
                    if decoded is not None and self.apply_result(decoded):
                        if self._on_partial is not None:
                            await self._on_partial(self.current_text())
                if (
                    self._is_status_two(header.get("status"))
                    or self._is_status_two(result.get("status"))
                    or (
                        decoded is not None
                        and (
                            self._is_status_two(decoded.get("status"))
                            or self._is_last_result(decoded.get("ls"))
                        )
                    )
                ):
                    self._done.set()
                    return
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            LOGGER.warning("asr.socket.receive_failed reason=%s", type(exc).__name__)
            self._error = True
            self._done.set()

    @staticmethod
    def extract_text(result: dict[str, object]) -> str:
        return extract_text(result)

    @staticmethod
    def extract_candidates(result: dict[str, object]) -> tuple[str, ...]:
        return extract_candidates(result)

    @staticmethod
    def _is_status_two(value: object) -> bool:
        return is_status_two(value)

    @staticmethod
    def _is_last_result(value: object) -> bool:
        return is_last_result(value)

    def apply_result(self, result: dict[str, object]) -> bool:
        return self._transcript.apply(result)

    def current_text(self) -> str:
        return self._transcript.text

    @staticmethod
    def extract_language(result: dict[str, object]) -> str:
        return extract_language(result)

    @property
    def detected_language(self) -> str:
        return self._transcript.detected_language

    @property
    def alternative_texts(self) -> tuple[str, ...]:
        return self._transcript.alternatives

    @property
    def candidates(self) -> tuple[str, ...]:
        return self.alternative_texts

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _audio(self, audio: str, status: int) -> dict[str, object]:
        return {
            "encoding": "raw",
            "sample_rate": 16000,
            "channels": 1,
            "bit_depth": 16,
            "seq": self._next_sequence(),
            "status": status,
            "audio": audio,
        }

    def _header(self, status: int) -> dict[str, object]:
        return {"app_id": self.app_id, "status": status}

    def _first_packet(self, audio: str) -> dict[str, object]:
        iat: dict[str, object] = {
            "domain": self.domain,
            "language": self.language,
            "accent": self.accent,
            "eos": self.eos,
            "result": {"encoding": "utf8", "compress": "raw", "format": "json"},
        }
        if self.dynamic_correction:
            iat["dwa"] = "wpgs"
        if self._hotword_spec:
            iat["dhw"] = self._hotword_spec
        return {
            "header": self._header(0),
            "parameter": {"iat": iat},
            "payload": {"audio": self._audio(audio, 0)},
        }

    def _middle_packet(self, audio: str) -> dict[str, object]:
        return {
            "header": self._header(1),
            "payload": {"audio": self._audio(audio, 1)},
        }

    def _last_packet(self) -> dict[str, object]:
        return {
            "header": self._header(2),
            "payload": {"audio": self._audio("", 2)},
        }


__all__ = ["VoiceProviderError", "XfyunStream"]
