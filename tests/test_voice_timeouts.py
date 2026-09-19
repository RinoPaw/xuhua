from __future__ import annotations

import asyncio

import heritage_explorer.voice as voice_module
from heritage_explorer.voice import VoiceProviderError, XfyunStream


class BlockingSocket:
    async def send(self, _packet: str) -> None:
        await asyncio.Future()

    async def close(self) -> None:
        return

    def __aiter__(self):
        return self

    async def __anext__(self):
        await asyncio.Future()


def test_finish_times_out_when_terminal_packet_send_never_completes(monkeypatch) -> None:
    socket = BlockingSocket()

    async def fake_connect(*_args, **_kwargs):
        return socket

    monkeypatch.setattr(voice_module, "connect", fake_connect)

    async def scenario() -> None:
        stream = XfyunStream(
            app_id="app",
            api_key="key",
            api_secret="secret",
            host="iat.xf-yun.com",
        )
        stream.finish_timeout = 0.02
        await stream.send_audio(bytes(stream.chunk_size))
        await stream.start()

        try:
            await asyncio.wait_for(stream.finish(), timeout=0.2)
        except VoiceProviderError as exc:
            assert str(exc) == "voice_provider_timeout"
        else:
            raise AssertionError("finish must not wait forever for a blocked terminal send")

        assert stream._sender is None
        assert stream._receiver is None

    asyncio.run(scenario())
