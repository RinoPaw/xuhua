import asyncio
import pytest
from heritage_explorer.voice import VoiceProviderError, XfyunStream
from heritage_explorer.voice_hybrid import HybridXfyunStream


class Stub:
    def __init__(self, **opts):
        self.opts = opts
        self.text = ""
        self.lang = ""
        self.fail = False
        self.sent = []
        self.closed = False

    @property
    def detected_language(self):
        return self.lang

    @property
    def candidates(self):
        return (self.text,)

    def current_text(self):
        return self.text

    async def start(self):
        if self.fail:
            raise VoiceProviderError("unavailable")

    async def send_audio(self, data):
        self.sent.append(data)

    async def finish_result(self):
        if self.fail:
            raise VoiceProviderError("unavailable")
        return self.text

    async def close(self):
        self.closed = True


def build():
    streams = {}

    def factory(**opts):
        name = "dialect" if opts["accent"] == "mulacc" else "multi"
        streams[name] = Stub(**opts)
        return streams[name]

    stream = HybridXfyunStream(
        app_id="a",
        api_key="b",
        api_secret="c",
        host="iat.cn-huabei-1.xf-yun.com",
        stream_factory=factory,
    )
    return stream, streams


def test_hybrid_limits_multilingual_recognition_to_four_languages():
    hybrid, streams = build()
    assert streams["multi"].opts["ln"] == "zh|en|ja|ko"
    assert streams["dialect"].opts["language"] == "zh_cn"
    assert streams["dialect"].opts["accent"] == "mulacc"

def test_provider_parameters():
    multi = XfyunStream(
        app_id="a", api_key="b", api_secret="c", host="iat.cn-huabei-1.xf-yun.com", ln=None
    )
    assert "ln" not in multi._first_packet("")["parameter"]["iat"]
    dialect = XfyunStream(
        app_id="a",
        api_key="b",
        api_secret="c",
        host="iat.cn-huabei-1.xf-yun.com",
        language="zh_cn",
        accent="mulacc",
    )
    packet = dialect._first_packet("")["parameter"]["iat"]
    assert packet["language"] == "zh_cn"
    assert packet["accent"] == "mulacc"
    assert packet["dwa"] == "wpgs"


@pytest.mark.parametrize(
    "lang,raw,zh,expected,locale",
    [
        ("zh", "bad", "dialect", "dialect", "zh"),
        ("en", "hello", "dialect", "hello", "en"),
        ("ja", "japanese", "dialect", "japanese", "ja"),
        ("ko", "korean", "dialect", "korean", "ko"),
        ("fr", "bonjour", "dialect", "bonjour", "fr"),
    ],
)
def test_language_routing(lang, raw, zh, expected, locale):
    async def run():
        stream, s = build()
        s["multi"].lang, s["multi"].text, s["dialect"].text = lang, raw, zh
        await stream.send_audio(b"first")
        await stream.start()
        assert await stream.finish_result() == expected
        assert stream.detected_language == locale
        assert s["multi"].sent == s["dialect"].sent == [b"first"]
        await stream.close()
        assert s["multi"].closed and s["dialect"].closed

    asyncio.run(run())


def test_fallback_and_both_failed():
    async def run():
        stream, s = build()
        s["dialect"].fail = True
        s["multi"].text, s["multi"].lang = "bonjour", "fr"
        await stream.start()
        assert await stream.finish_result() == "bonjour"
        assert s["dialect"].closed
        await stream.close()

        stream, s = build()
        s["multi"].text, s["multi"].lang = "", ""
        s["dialect"].text = "dialect"
        await stream.start()
        assert await stream.finish_result() == "dialect"
        assert stream.detected_language == "zh"
        await stream.close()

        stream, s = build()
        await stream.start()
        s["multi"].fail = s["dialect"].fail = True
        with pytest.raises(VoiceProviderError):
            await stream.finish_result()
        await stream.close()

    asyncio.run(run())


def test_close_cancels_all_children():
    async def run():
        stream, s = build()
        await stream.start()
        await stream.close()
        assert all(p.closed for p in s.values())
        await stream.send_audio(b"ignored")
        assert all(not p.sent for p in s.values())

    asyncio.run(run())


def test_chinese_script_fallback_without_provider_language():
    async def run():
        stream, s = build()
        s["multi"].text = "\u6cb3\u5357\u8bdd"
        s["dialect"].text = "\u6cb3\u5357\u65b9\u8a00"
        await stream.start()
        assert await stream.finish_result() == "\u6cb3\u5357\u65b9\u8a00"
        assert stream.detected_language == "zh"
        await stream.close()

    asyncio.run(run())
