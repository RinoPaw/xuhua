"""Dual iFlytek ASR stream for Chinese dialects plus Chinese/English/Japanese/Korean."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from .voice import VoiceProviderError, XfyunStream

LOGGER = logging.getLogger(__name__)
CHINESE_CODES = frozenset({"zh", "zh_cn", "cn", "cmn"})


def _looks_chinese(text: str) -> bool:
    han = sum("\u3400" <= c <= "\u9fff" for c in text)
    latin = sum(c.isascii() and c.isalpha() for c in text)
    kana = sum("\u3040" <= c <= "\u30ff" for c in text)
    hangul = sum("\uac00" <= c <= "\ud7af" for c in text)
    return han > 0 and han > latin and not kana and not hangul


class HybridXfyunStream:
    """Two provider connections, one lifecycle and one final transcript."""

    def __init__(
        self,
        *,
        app_id: str,
        api_key: str,
        api_secret: str,
        host: str,
        on_partial: Callable[[str], Awaitable[None]] | None = None,
        hotwords: str | list[str] | tuple[str, ...] | None = None,
        stream_factory: Callable[..., Any] = XfyunStream,
        **_unused: Any,
    ) -> None:
        self._on_partial = on_partial
        self._closed = False
        self._selected = "multilingual"
        common = dict(
            app_id=app_id,
            api_key=api_key,
            api_secret=api_secret,
            host=host,
            path="/v1",
            domain="slm",
            hotwords=hotwords,
        )
        self._streams = {
            "multilingual": stream_factory(
                **common,
                language="mul_cn",
                accent="mandarin",
                ln="zh|en|ja|ko",
                dynamic_correction=False,
                on_partial=self._callback("multilingual"),
            ),
            "dialect": stream_factory(
                **common,
                language="zh_cn",
                accent="mulacc",
                dynamic_correction=True,
                on_partial=self._callback("dialect"),
            ),
        }
        self._active = dict(self._streams)

    @property
    def configured(self) -> bool:
        return all(getattr(s, "configured", True) for s in self._streams.values())

    def _prefer_dialect(self) -> bool:
        multi = self._streams["multilingual"]
        language = str(getattr(multi, "detected_language", "") or "").lower()
        if language in CHINESE_CODES:
            return True
        if language:
            return False
        return _looks_chinese(str(multi.current_text() or ""))

    def _visible_model(self) -> str:
        if "multilingual" not in self._active:
            return "dialect"
        if "dialect" in self._active and self._prefer_dialect():
            return "dialect"
        return "multilingual"

    def _callback(self, model: str) -> Callable[[str], Awaitable[None]]:
        async def forward(text: str) -> None:
            if not self._closed and model == self._visible_model():
                if self._on_partial is not None:
                    await self._on_partial(text)

        return forward

    async def start(self) -> None:
        if self._closed:
            raise VoiceProviderError("voice_stream_closed")
        names = tuple(self._active)
        outcomes = await asyncio.gather(
            *(self._active[name].start() for name in names),
            return_exceptions=True,
        )
        for name, result in zip(names, outcomes):
            if isinstance(result, BaseException):
                LOGGER.warning("asr.hybrid.start_failed model=%s", name)
                self._active.pop(name, None)
                await self._streams[name].close()
        if not self._active:
            raise VoiceProviderError("voice_provider_unavailable")

    async def send_audio(self, data: bytes) -> None:
        if self._closed or not data:
            return
        names = tuple(self._active)
        if not names:
            raise VoiceProviderError("voice_provider_unavailable")
        outcomes = await asyncio.gather(
            *(self._active[name].send_audio(data) for name in names),
            return_exceptions=True,
        )
        for name, result in zip(names, outcomes):
            if isinstance(result, BaseException):
                LOGGER.warning("asr.hybrid.audio_failed model=%s", name)
                self._active.pop(name, None)
                await self._streams[name].close()
        if not self._active:
            raise VoiceProviderError("voice_provider_unavailable")

    async def finish_result(self) -> str:
        names = tuple(self._active)
        if not names:
            raise VoiceProviderError("voice_provider_unavailable")
        results = await asyncio.gather(
            *(self._active[name].finish_result() for name in names),
            return_exceptions=True,
        )
        texts: dict[str, str] = {}
        for name, result in zip(names, results):
            if isinstance(result, BaseException):
                LOGGER.warning("asr.hybrid.finish_failed model=%s", name)
            else:
                texts[name] = str(result or "")
        if not texts:
            raise VoiceProviderError("voice_provider_failed")
        multi, dialect = texts.get("multilingual", ""), texts.get("dialect", "")
        self._selected = (
            "dialect" if dialect and (not multi or self._prefer_dialect()) else "multilingual"
        )
        LOGGER.info("asr.hybrid.selected model=%s", self._selected)
        return texts.get(self._selected, "")

    async def finish(self) -> str:
        try:
            return await self.finish_result()
        finally:
            await self.close()

    @property
    def detected_language(self) -> str:
        if self._selected == "dialect":
            return "zh"
        return str(self._streams["multilingual"].detected_language or "")

    @property
    def candidates(self) -> tuple[str, ...]:
        return tuple(self._streams[self._selected].candidates)

    async def close(self) -> None:
        self._closed = True
        await asyncio.gather(
            *(stream.close() for stream in self._streams.values()),
            return_exceptions=True,
        )


__all__ = ["HybridXfyunStream"]
