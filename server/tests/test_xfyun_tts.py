"""Official iFLYTEK TTS protocol, streaming and secret-safety tests."""

from __future__ import annotations

import asyncio
import base64
import json
from urllib.parse import parse_qs, urlparse

import pytest

import heritage_explorer.providers.xfyun_tts as tts


class FakeSocket:
    def __init__(self, packets) -> None:
        self.packets = iter(packets)
        self.sent = []
        self.closed = False
        self.waiting = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        self.closed = True

    async def send(self, message):
        self.sent.append(json.loads(message))

    async def recv(self):
        packet = next(self.packets, None)
        if packet is None:
            self.waiting = True
            await asyncio.Event().wait()
        return packet


def packet(audio: bytes = b"", *, status: int = 1, code: int = 0):
    return json.dumps({
        "code": code,
        "message": "token=SECRET_DO_NOT_LOG",
        "data": {
            "audio": base64.b64encode(audio).decode("ascii"), "status": status,
        },
    })


def configured(monkeypatch) -> None:
    monkeypatch.setenv("XF_TTS_APP_ID", "app")
    monkeypatch.setenv("XF_TTS_API_KEY", "key")
    monkeypatch.setenv("XF_TTS_API_SECRET", "secret")
    monkeypatch.setenv("XF_TTS_VOICE_ZH", "xiaoyan")


def test_stream_protocol_uses_signed_ws_mp3_and_closes(monkeypatch) -> None:
    configured(monkeypatch)
    socket = FakeSocket([
        packet(b"first"),
        json.dumps({"code": 0, "data": None}),
        packet(b"second", status=2),
    ])
    urls = []

    def fake_connect(url, **_kwargs):
        urls.append(url)
        return socket

    monkeypatch.setattr(tts, "connect", fake_connect)

    async def scenario():
        speech = tts.Communicate("汴绣", voice="zh-CN-XiaoxiaoNeural", rate="-2%", pitch="+0Hz")
        chunks = [x async for x in speech.stream()]
        assert chunks == [
            {"type": "audio", "data": b"first"},
            {"type": "audio", "data": b"second"},
        ]

    asyncio.run(scenario())
    assert socket.closed
    assert socket.sent[0]["common"] == {"app_id": "app"}
    assert socket.sent[0]["business"]["aue"] == "lame"
    assert socket.sent[0]["business"]["sfl"] == 1
    assert socket.sent[0]["business"]["vcn"] == "xiaoyan"
    assert socket.sent[0]["data"]["status"] == 2
    assert base64.b64decode(socket.sent[0]["data"]["text"]) == "汴绣".encode()
    assert len(urls) == 1
    parsed = urlparse(urls[0])
    assert parsed.hostname == "tts-api.xfyun.cn"
    assert parsed.path == "/v2/tts"
    assert "authorization" in parse_qs(parsed.query)
    assert "secret" not in urls[0]


def test_first_audio_is_available_before_provider_finishes(monkeypatch) -> None:
    configured(monkeypatch)
    socket = FakeSocket([packet(b"early")])
    monkeypatch.setattr(tts, "connect", lambda *_args, **_kwargs: socket)

    async def scenario():
        stream = tts.Communicate(
            "开场白", voice="zh-CN-XiaoxiaoNeural", rate="-2%", pitch="+0Hz",
        ).stream()
        assert await asyncio.wait_for(anext(stream), 1) == {
            "type": "audio", "data": b"early",
        }
        assert socket.waiting is False
        await stream.aclose()
        assert socket.closed

    asyncio.run(scenario())


@pytest.mark.parametrize("bad", [
    json.dumps({"code": 11200, "message": "key=SECRET_DO_NOT_LOG", "data": None}),
    "invalid-json",
    packet(b"", status=2),
])
def test_bad_provider_response_fails_without_exposing_secrets(monkeypatch, bad) -> None:
    configured(monkeypatch)
    sock = FakeSocket([bad])
    monkeypatch.setattr(tts, "connect", lambda *_args, **_kwargs: sock)

    async def scenario():
        with pytest.raises(tts.TtsProviderError) as error:
            async for _ in tts.Communicate(
                "私人话语", voice="zh-CN-XiaoxiaoNeural", rate="-2%", pitch="+0Hz",
            ).stream():
                pass
        assert "SECRET_DO_NOT_LOG" not in str(error.value)
        assert "私人话语" not in str(error.value)
        if "11200" in bad:
            assert error.value.code == 11200

    asyncio.run(scenario())
    assert sock.closed


def test_missing_credentials_fail_before_connection(monkeypatch) -> None:
    monkeypatch.setenv("XF_TTS_APP_ID", " ")
    monkeypatch.setenv("XF_TTS_API_KEY", " ")
    monkeypatch.setenv("XF_TTS_API_SECRET", " ")
    monkeypatch.setattr(tts, "XF_APP_ID", "")
    monkeypatch.setattr(tts, "XF_API_KEY", "")
    monkeypatch.setattr(tts, "XF_API_SECRET", "")
    calls = []
    monkeypatch.setattr(tts, "connect", lambda *args, **kwargs: calls.append(args))

    async def scenario():
        stream = tts.Communicate(
            "你好", voice="zh-CN-XiaoxiaoNeural", rate="-2%", pitch="+0Hz",
        ).stream()
        with pytest.raises(tts.TtsProviderError, match="tts_provider_unconfigured"):
            await anext(stream)

    asyncio.run(scenario())
    assert calls == []


def test_oversized_text_is_rejected_before_sending(monkeypatch) -> None:
    configured(monkeypatch)
    calls = []
    monkeypatch.setattr(tts, "connect", lambda *args, **kwargs: calls.append(args))

    async def scenario():
        stream = tts.Communicate(
            "汴" * 3000, voice="zh-CN-XiaoxiaoNeural", rate="-2%", pitch="+0Hz",
        ).stream()
        with pytest.raises(tts.TtsProviderError, match="tts_text_too_long"):
            await anext(stream)

    asyncio.run(scenario())
    assert calls == []


def test_unknown_dialect_voice_is_not_sent_as_edge_identifier(monkeypatch):
    configured(monkeypatch)
    monkeypatch.setenv("XF_TTS_VOICE_YUE", "my_cantonese_voice")
    assert tts.Communicate(
        "粤语", voice="zh-HK-HiuMaanNeural", rate="-2%", pitch="+0Hz",
    ).vcn == "my_cantonese_voice"
    assert tts.Communicate(
        "河南", voice="zh-CN-YunxiNeural", rate="-2%", pitch="+0Hz",
    ).vcn == "xiaoyan"


def test_mandarin_defaults_to_xiaolu_when_not_configured(monkeypatch) -> None:
    monkeypatch.delenv("XF_TTS_VOICE_ZH", raising=False)
    assert tts.voice_for("zh-CN-XiaoxiaoNeural") == "x4_yezi"
    assert tts.Communicate(
        "你好，欢迎来到叙华。", voice="zh-CN-XiaoxiaoNeural", rate="-2%", pitch="+0Hz",
    ).vcn == "x4_yezi"
    monkeypatch.setenv("XF_TTS_VOICE_ZH", "  ")
    assert tts.voice_for("zh-CN-XiaoxiaoNeural") == "x4_yezi"


def test_explicit_mandarin_voice_still_overrides_xiaolu(monkeypatch) -> None:
    monkeypatch.setenv("XF_TTS_VOICE_ZH", "other_authorized_voice")
    assert tts.voice_for("zh-CN-XiaoxiaoNeural") == "other_authorized_voice"
