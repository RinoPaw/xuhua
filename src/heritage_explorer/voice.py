"""Streaming Xunfei ASR transport for browser-captured 16 kHz PCM audio."""

from __future__ import annotations

import asyncio
import base64
from email.utils import formatdate
import hashlib
import hmac
import json
import logging
import re
from collections.abc import Awaitable, Callable
from urllib.parse import urlencode

from websockets.asyncio.client import ClientConnection, connect

from .language import detect_locale, is_chinese_locale


LOGGER = logging.getLogger(__name__)


class VoiceProviderError(RuntimeError):
    """Provider failure without secret-bearing diagnostic text."""


class _FinishRequest:
    """A queue barrier used to serialize the Xunfei status=2 packet."""

    def __init__(self) -> None:
        self.done: asyncio.Future[None] = asyncio.get_running_loop().create_future()


class XfyunStream:
    """One utterance over Xunfei's streaming IAT WebSocket protocol."""

    host = "iat.xf-yun.com"
    path = "/v1"
    chunk_size = 1280
    # 1280 bytes at 16 kHz, 16-bit, mono PCM represent exactly 40 ms.
    frame_interval = 0.04

    def __init__(
        self,
        *,
        app_id: str,
        api_key: str,
        api_secret: str,
        on_partial: Callable[[str], Awaitable[None]] | None = None,
        hotwords: str | list[str] | tuple[str, ...] | None = None,
        resource_id: str | None = None,
        host: str | None = None,
        path: str = "/v1",
        language: str = "zh_cn",
        accent: str = "mandarin",
        domain: str = "slm",
        language_hint: str = "",
        dynamic_correction: bool = True,
        eos: int = 1800,
    ) -> None:
        self.app_id = app_id.strip()
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.host = str(host or type(self).host).strip()
        self.path = str(path or "/v1").strip()
        self.language = str(language or "zh_cn").strip()
        self.accent = str(accent or "mandarin").strip()
        self.domain = str(domain or "slm").strip()
        self.language_hint = str(language_hint or "").strip()
        self.dynamic_correction = bool(dynamic_correction)
        self.eos = min(max(int(eos), 600), 10000)
        self.resource_id = (resource_id or "").strip()
        self._hotword_spec = self._format_hotwords(hotwords)
        self._socket: ClientConnection | None = None
        self._receiver: asyncio.Task[None] | None = None
        self._sender: asyncio.Task[None] | None = None
        self._done = asyncio.Event()
        self._buffer = bytearray()
        self._send_queue: asyncio.Queue[bytes | _FinishRequest] = asyncio.Queue()
        self._send_lock = asyncio.Lock()
        self._pieces: dict[int, str] = {}
        # Keep the candidates at result-sequence granularity.  WPGS can
        # replace a range of old sequences, so retaining this mapping lets us
        # discard every hypothesis from the replaced range together with its
        # top-1 text.
        self._candidate_pieces: dict[int, tuple[str, ...]] = {}
        self._language_pieces: dict[int, str] = {}
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
        return bool(self.app_id and self.api_key and self.api_secret)

    @staticmethod
    def _format_hotwords(hotwords: str | list[str] | tuple[str, ...] | None) -> str:
        """Return Xunfei's ``dhw`` value, bounded to 1024 UTF-8 bytes.

        The service uses ``|`` as a separator and ``utf-8;`` as an encoding
        marker.  Accepting a delimited string as well as a sequence keeps the
        constructor convenient while stripping separators/control whitespace
        prevents malformed provider parameters.
        """
        if hotwords is None:
            return ""
        values = [hotwords] if isinstance(hotwords, str) else hotwords
        cleaned: list[str] = []
        seen: set[str] = set()
        for value in values:
            text = str(value or "")
            # A pipe/comma-delimited value is common when the list originates
            # in an environment variable or a form field.
            for item in re.split(r"[|,，、;；\r\n\t]+", text):
                item = "".join(item.split())
                if not item or item in seen:
                    continue
                seen.add(item)
                cleaned.append(item)

        prefix = "utf-8;"
        remaining = 1024 - len(prefix.encode("utf-8"))
        selected: list[str] = []
        used = 0
        for item in cleaned:
            encoded = item.encode("utf-8")
            required = len(encoded) if not selected else len(encoded) + 1
            if required <= remaining - used:
                selected.append(item)
                used += required
                continue
            # Preserve order and stop at the first item that cannot fit.  If
            # it is the first item, retain as much as the provider permits.
            if not selected and remaining > 0:
                item = encoded[:remaining].decode("utf-8", errors="ignore")
                if item:
                    selected.append(item)
            break
        return prefix + "|".join(selected) if selected else ""

    def signed_url(self) -> str:
        date = formatdate(usegmt=True)
        origin = f"host: {self.host}\ndate: {date}\nGET {self.path} HTTP/1.1"
        digest = hmac.new(
            self.api_secret.encode(), origin.encode(), digestmod=hashlib.sha256
        ).digest()
        signature = base64.b64encode(digest).decode()
        authorization = (
            f'api_key="{self.api_key}", algorithm="hmac-sha256", '
            f'headers="host date request-line", signature="{signature}"'
        )
        params = {
            "authorization": base64.b64encode(authorization.encode()).decode(),
            "date": date,
            "host": self.host,
        }
        return f"wss://{self.host}{self.path}?{urlencode(params)}"

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
        # Give the pump one turn to deliver the first frame immediately.  The
        # remaining handshake cache stays queued and is paced by the pump.
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
                    # Some event loops wake timers a little early. Recheck so
                    # a coarse timer cannot turn 40 ms frames into a burst.
                    now = asyncio.get_running_loop().time()
                await self._send_frame(current)
                # Schedule from the actual completion time so a slow network
                # write never causes the next frame to burst immediately.
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
            # The barrier is consumed only after every queued audio frame has
            # been written. Shield it so cancellation can be followed by the
            # normal close path without leaving a canceled queue item behind.
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
                # Different IAT deployments place the terminal marker in
                # different layers: retain compatibility with all of them.
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
        return XfyunStream.extract_candidates(result)[0]

    @staticmethod
    def extract_candidates(result: dict[str, object]) -> tuple[str, ...]:
        """Extract full-text hypotheses, preserving provider candidate order.

        ``cw`` contains alternatives for each word segment.  Candidate index
        is stable across segments in Xunfei's response; where a segment has
        fewer alternatives, its top-1 word is used for the remaining joined
        hypotheses.
        """
        words: list[list[str]] = []
        segments = result.get("ws", [])
        if not isinstance(segments, list):
            return ("",)
        for segment in segments:
            raw_candidates = segment.get("cw", []) if isinstance(segment, dict) else []
            if not isinstance(raw_candidates, list):
                continue
            candidates = []
            for candidate in raw_candidates:
                if isinstance(candidate, dict):
                    word = str(candidate.get("w", ""))
                    if word:
                        candidates.append(word)
            if candidates:
                words.append(candidates)
        if not words:
            return ("",)
        count = max(len(items) for items in words)
        output: list[str] = []
        for index in range(count):
            output.append(
                "".join(items[index] if index < len(items) else items[0] for items in words)
            )
        return tuple(output)

    @staticmethod
    def _is_status_two(value: object) -> bool:
        return value == 2 or value == "2"

    @staticmethod
    def _is_last_result(value: object) -> bool:
        return value is True or value == "true" or value == 1 or value == "1"

    def apply_result(self, result: dict[str, object]) -> bool:
        candidates = self.extract_candidates(result)
        piece = candidates[0] if candidates else ""
        sequence = int(result.get("sn", max(self._pieces, default=-1) + 1))
        replacement = result.get("rg") if result.get("pgs") == "rpl" else None
        if isinstance(replacement, list) and len(replacement) == 2:
            start, end = int(replacement[0]), int(replacement[1])
            for key in range(start, end + 1):
                self._pieces.pop(key, None)
                self._candidate_pieces.pop(key, None)
                self._language_pieces.pop(key, None)
        if piece:
            self._pieces[sequence] = piece
        if candidates and any(candidates):
            self._candidate_pieces[sequence] = tuple(
                candidate
                for index, candidate in enumerate(candidates)
                if candidate and candidate not in candidates[:index]
            )
        source_language = self.extract_language(result)
        if source_language:
            self._language_pieces[sequence] = source_language
        return bool(piece or replacement)

    def current_text(self) -> str:
        return "".join(self._pieces[key] for key in sorted(self._pieces)).strip()

    @staticmethod
    def extract_language(result: dict[str, object]) -> str:
        """Return the dominant provider ``cw.lg`` source-language tag."""

        counts: dict[str, int] = {}
        segments = result.get("ws", [])
        if not isinstance(segments, list):
            return ""
        for segment in segments:
            candidates = segment.get("cw", []) if isinstance(segment, dict) else []
            if not isinstance(candidates, list):
                continue
            for candidate in candidates:
                if not isinstance(candidate, dict):
                    continue
                language = str(candidate.get("lg") or "").strip().casefold()
                if language:
                    counts[language] = counts.get(language, 0) + 1
                    break
        return max(counts, key=counts.get) if counts else ""

    @property
    def detected_language(self) -> str:
        counts: dict[str, int] = {}
        for language in self._language_pieces.values():
            counts[language] = counts.get(language, 0) + 1
        return max(counts, key=counts.get) if counts else ""

    @property
    def alternative_texts(self) -> tuple[str, ...]:
        """Final, de-duplicated full-transcript hypotheses (top-1 first)."""
        if not self._candidate_pieces:
            text = self.current_text()
            return (text,) if text else ()
        keys = sorted(self._candidate_pieces)
        count = max(len(self._candidate_pieces[key]) for key in keys)
        texts: list[str] = []
        for index in range(count):
            parts = []
            for key in keys:
                candidates = self._candidate_pieces[key]
                parts.append(candidates[index] if index < len(candidates) else candidates[0])
            text = "".join(parts).strip()
            if text and text not in texts:
                texts.append(text)
        # Results without a candidate payload should never hide top-1.
        top1 = self.current_text()
        if top1 and top1 not in texts:
            texts.insert(0, top1)
        return tuple(texts)

    @property
    def candidates(self) -> tuple[str, ...]:
        """Alias for consumers that call the n-best result ``candidates``."""
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
        header: dict[str, object] = {"app_id": self.app_id, "status": status}
        if self.resource_id:
            header["res_id"] = self.resource_id
        return header

    def _first_packet(self, audio: str) -> dict[str, object]:
        iat: dict[str, object] = {
            "domain": self.domain,
            "language": self.language,
            "accent": self.accent,
            "eos": self.eos,
            "result": {"encoding": "utf8", "compress": "raw", "format": "json"},
        }
        # Xunfei documents WPGS and session hotwords for the dialect SLM,
        # while the multilingual SLM leaves both out of its request contract.
        if self.dynamic_correction:
            iat["dwa"] = "wpgs"
        if self.language_hint:
            iat["ln"] = self.language_hint
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


class AutoXfyunStream:
    """Probe Xunfei's dialect and multilingual SLMs behind one stream API.

    The provider exposes ``zh_cn/mulacc`` (Mandarin plus Chinese dialects) and
    ``mul_cn/mandarin`` (automatic language recognition) as separate models.
    The first utterance can therefore be sent to both models; the result's
    ``cw.lg`` tags choose multilingual output only when it is genuinely
    non-Chinese.  A third legacy stream preserves existing Mandarin/simple
    English recognition when neither newer entitlement is enabled.
    """

    DIALECT = "dialect"
    MULTILINGUAL = "multilingual"
    LEGACY = "legacy"
    AUTO = "auto"

    def __init__(
        self,
        *,
        app_id: str,
        api_key: str,
        api_secret: str,
        multilingual_app_id: str = "",
        multilingual_api_key: str = "",
        multilingual_api_secret: str = "",
        host: str | None = None,
        multilingual_host: str | None = None,
        multilingual_language_hint: str = "en|ja|ko",
        legacy_host: str | None = "iat.xf-yun.com",
        on_partial: Callable[[str], Awaitable[None]] | None = None,
        hotwords: str | list[str] | tuple[str, ...] | None = None,
        resource_id: str | None = None,
        mode: str = AUTO,
        preferred_mode: str = DIALECT,
    ) -> None:
        requested_mode = str(mode or self.AUTO).strip().casefold()
        self.mode = (
            requested_mode
            if requested_mode
            in {
                self.AUTO,
                self.DIALECT,
                self.MULTILINGUAL,
                self.LEGACY,
            }
            else self.AUTO
        )
        preferred = str(preferred_mode or self.DIALECT).strip().casefold()
        self.preferred_mode = (
            preferred
            if preferred
            in {
                self.DIALECT,
                self.MULTILINGUAL,
            }
            else self.DIALECT
        )
        self._on_partial = on_partial
        self._partials: dict[str, str] = {}
        self._active_modes: set[str] = set()
        self._start_errors: dict[str, Exception] = {}
        self._selected_mode = ""

        async def dialect_partial(text: str) -> None:
            await self._publish_partial(self.DIALECT, text)

        async def multilingual_partial(text: str) -> None:
            await self._publish_partial(self.MULTILINGUAL, text)

        async def legacy_partial(text: str) -> None:
            await self._publish_partial(self.LEGACY, text)

        self._streams: dict[str, XfyunStream] = {}
        if self.mode in {self.AUTO, self.DIALECT}:
            self._streams[self.DIALECT] = XfyunStream(
                app_id=app_id,
                api_key=api_key,
                api_secret=api_secret,
                host=host,
                language="zh_cn",
                accent="mulacc",
                domain="slm",
                dynamic_correction=True,
                on_partial=dialect_partial,
                hotwords=hotwords,
                resource_id=resource_id,
            )
        if self.mode in {self.AUTO, self.MULTILINGUAL}:
            self._streams[self.MULTILINGUAL] = XfyunStream(
                app_id=(multilingual_app_id or app_id),
                api_key=(multilingual_api_key or api_key),
                api_secret=(multilingual_api_secret or api_secret),
                host=multilingual_host or host,
                language="mul_cn",
                accent="mandarin",
                domain="slm",
                dynamic_correction=False,
                eos=6000,
                language_hint=multilingual_language_hint,
                on_partial=multilingual_partial,
            )
        if self.mode in {self.AUTO, self.LEGACY}:
            self._streams[self.LEGACY] = XfyunStream(
                app_id=app_id,
                api_key=api_key,
                api_secret=api_secret,
                host=legacy_host,
                language="zh_cn",
                accent="mandarin",
                domain="slm",
                dynamic_correction=True,
                on_partial=legacy_partial,
                hotwords=hotwords,
                resource_id=resource_id,
            )

    @staticmethod
    def _is_chinese_tag(value: object) -> bool:
        language = str(value or "").strip().casefold().replace("-", "_")
        return language in {"zh", "cn", "zh_cn", "cn_cbm", "chinese"}

    @classmethod
    def _is_foreign_transcript(cls, text: str, detected: object) -> bool:
        """Reject foreign-language tags contradicted by Chinese dialect text."""

        if cls._is_chinese_tag(detected):
            return False
        return not is_chinese_locale(detect_locale(text, hint=detected))

    async def _publish_partial(self, mode: str, text: str) -> None:
        content = str(text or "")
        self._partials[mode] = content
        if self._on_partial is None or not content:
            return
        if self._selected_mode:
            if mode == self._selected_mode:
                await self._on_partial(content)
            return
        multilingual = self._streams.get(self.MULTILINGUAL)
        detected = getattr(multilingual, "detected_language", "") if multilingual else ""
        multilingual_text = self._partials.get(self.MULTILINGUAL, "")
        if detected and self._is_foreign_transcript(multilingual_text, detected):
            if mode == self.MULTILINGUAL:
                await self._on_partial(content)
            return
        if (
            self.mode != self.AUTO
            or mode == self.preferred_mode
            or (
                mode == self.LEGACY
                and not self._partials.get(self.preferred_mode)
            )
        ):
            await self._on_partial(content)

    async def start(self) -> None:
        async def start_one(mode: str, stream: XfyunStream) -> None:
            try:
                await stream.start()
                self._active_modes.add(mode)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._start_errors[mode] = exc
                await stream.close()

        await asyncio.gather(*(start_one(mode, stream) for mode, stream in self._streams.items()))
        if not self._active_modes:
            failure = next(iter(self._start_errors.values()), None)
            if isinstance(failure, VoiceProviderError):
                raise failure
            raise VoiceProviderError("voice_provider_unavailable") from failure

    async def send_audio(self, data: bytes) -> None:
        # Audio can arrive while ``start`` is still negotiating sockets.  Each
        # child stream already buffers pre-connect PCM, preserving first audio.
        await asyncio.gather(
            *(
                stream.send_audio(data)
                for mode, stream in self._streams.items()
                if mode not in self._start_errors
            )
        )

    async def finish(self) -> str:
        async def finish_one(mode: str, stream: XfyunStream) -> tuple[str, str | Exception]:
            if mode not in self._active_modes:
                return mode, self._start_errors.get(
                    mode,
                    VoiceProviderError("voice_provider_unavailable"),
                )
            try:
                return mode, await stream.finish()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                return mode, exc

        finished = await asyncio.gather(
            *(finish_one(mode, stream) for mode, stream in self._streams.items())
        )
        results = {mode: result for mode, result in finished}
        dialect = results.get(self.DIALECT, "")
        multilingual = results.get(self.MULTILINGUAL, "")
        legacy = results.get(self.LEGACY, "")
        dialect_text = dialect if isinstance(dialect, str) else ""
        multilingual_text = multilingual if isinstance(multilingual, str) else ""
        legacy_text = legacy if isinstance(legacy, str) else ""
        multilingual_stream = self._streams.get(self.MULTILINGUAL)
        detected = (
            getattr(multilingual_stream, "detected_language", "") if multilingual_stream else ""
        )

        if (
            multilingual_text
            and detected
            and self._is_foreign_transcript(multilingual_text, detected)
        ):
            self._selected_mode = self.MULTILINGUAL
            return multilingual_text
        if dialect_text:
            self._selected_mode = self.DIALECT
            return dialect_text
        if multilingual_text:
            self._selected_mode = self.MULTILINGUAL
            return multilingual_text
        if legacy_text:
            self._selected_mode = self.LEGACY
            return legacy_text

        # Empty speech is still a successful provider result.  Do not turn a
        # valid rejection/silence into an ASR outage merely because another
        # optional model is not licensed for this account.
        successful_modes = [
            mode for mode, result in results.items() if isinstance(result, str)
        ]
        if successful_modes:
            if self.LEGACY in successful_modes:
                self._selected_mode = self.LEGACY
            else:
                self._selected_mode = successful_modes[0]
            return ""

        failures = [result for result in results.values() if isinstance(result, Exception)]
        if failures:
            failure = failures[0]
            if isinstance(failure, VoiceProviderError):
                raise failure
            raise VoiceProviderError("voice_provider_failed") from failure
        return ""

    async def close(self) -> None:
        await asyncio.gather(
            *(stream.close() for stream in self._streams.values()),
            return_exceptions=True,
        )

    @property
    def selected_mode(self) -> str:
        return self._selected_mode

    @property
    def detected_language(self) -> str:
        stream = self._streams.get(self._selected_mode or self.MULTILINGUAL)
        return str(getattr(stream, "detected_language", "") or "")

    @property
    def candidates(self) -> tuple[str, ...]:
        stream = self._streams.get(self._selected_mode)
        if stream is not None:
            return stream.candidates
        values: list[str] = []
        for child in self._streams.values():
            for candidate in child.candidates:
                if candidate and candidate not in values:
                    values.append(candidate)
        return tuple(values)


__all__ = ["AutoXfyunStream", "VoiceProviderError", "XfyunStream"]
