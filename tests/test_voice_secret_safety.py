from __future__ import annotations

import asyncio

import pytest

import heritage_explorer.voice as voice_module
from heritage_explorer.voice import VoiceProviderError, XfyunStream


def test_connect_failure_drops_secret_bearing_exception_chain(monkeypatch) -> None:
    async def fail_connect(*_args, **_kwargs):
        raise RuntimeError("wss://provider.test/v1?authorization=SECRET_SIGNATURE")

    monkeypatch.setattr(voice_module, "connect", fail_connect)

    async def scenario() -> None:
        stream = XfyunStream(
            app_id="app",
            api_key="key",
            api_secret="secret",
            host="iat.xf-yun.com",
        )
        with pytest.raises(VoiceProviderError) as raised:
            await stream.start()
        assert raised.value.__cause__ is None
        assert "SECRET_SIGNATURE" not in str(raised.value)

    asyncio.run(scenario())
