from __future__ import annotations

import asyncio

import pytest

from heritage_explorer.voice import VoiceProviderError, XfyunStream


def test_preconnect_audio_buffer_has_a_hard_backlog_limit() -> None:
    async def scenario() -> None:
        stream = XfyunStream(
            app_id="app",
            api_key="key",
            api_secret="secret",
            host="iat.xf-yun.com",
        )
        chunk = b"x" * (64 * 1024)
        with pytest.raises(VoiceProviderError, match="voice_audio_backlog"):
            while True:
                await stream.send_audio(chunk)
        assert len(stream._buffer) <= stream.max_audio_backlog_bytes
        assert stream._send_queue.qsize() <= stream.max_audio_backlog_frames
        await stream.close()

    asyncio.run(scenario())
