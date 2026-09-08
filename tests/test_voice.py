from __future__ import annotations

import base64
import asyncio
import json
from urllib.parse import parse_qs, urlparse

import heritage_explorer.voice as voice_module
from heritage_explorer.voice import AutoXfyunStream, VoiceProviderError, XfyunStream


def make_stream() -> XfyunStream:
    return XfyunStream(app_id="app", api_key="key", api_secret="secret")


def install_fake_provider_streams(
    monkeypatch,
    *,
    results: dict[str, str | Exception],
    languages: dict[str, str] | None = None,
    start_failures: set[str] | None = None,
):
    languages = languages or {}
    start_failures = start_failures or set()

    class FakeProviderStream:
        instances: dict[str, "FakeProviderStream"] = {}

        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            if kwargs.get("language") == "mul_cn":
                self.mode = AutoXfyunStream.MULTILINGUAL
            elif kwargs.get("accent") == "mulacc":
                self.mode = AutoXfyunStream.DIALECT
            else:
                self.mode = AutoXfyunStream.LEGACY
            self.detected_language = languages.get(self.mode, "")
            outcome = results.get(self.mode, "")
            self.candidates = (outcome,) if isinstance(outcome, str) and outcome else ()
            self.audio: list[bytes] = []
            self.started = False
            self.closed = False
            self.__class__.instances[self.mode] = self

        async def start(self) -> None:
            if self.mode in start_failures:
                raise VoiceProviderError(f"{self.mode}_unavailable")
            self.started = True

        async def send_audio(self, data: bytes) -> None:
            self.audio.append(data)

        async def finish(self) -> str:
            outcome = results.get(self.mode, "")
            if isinstance(outcome, Exception):
                raise outcome
            return outcome

        async def close(self) -> None:
            self.closed = True

    monkeypatch.setattr(voice_module, "XfyunStream", FakeProviderStream)
    return FakeProviderStream


def test_extract_text_uses_best_candidate_from_each_segment() -> None:
    result = {
        "ws": [
            {"cw": [{"w": "朱仙镇"}, {"w": "朱仙阵"}]},
            {"cw": [{"w": "木版年画"}]},
        ]
    }

    assert XfyunStream.extract_text(result) == "朱仙镇木版年画"


def test_extract_candidates_joins_nbest_words_in_provider_order() -> None:
    result = {
        "ws": [
            {"cw": [{"w": "朱仙镇"}, {"w": "朱仙阵"}]},
            {"cw": [{"w": "木版年画"}, {"w": "木板年画"}, {"w": "木版年华"}]},
        ]
    }

    assert XfyunStream.extract_candidates(result) == (
        "朱仙镇木版年画",
        "朱仙阵木板年画",
        "朱仙镇木版年华",
    )


def test_wpgs_replacement_discards_stale_top1_and_alternatives() -> None:
    stream = make_stream()
    assert stream.apply_result(
        {
            "sn": 0,
            "ws": [{"cw": [{"w": "前文"}]}],
        }
    )
    assert stream.apply_result(
        {
            "sn": 1,
            "ws": [{"cw": [{"w": "书秀"}, {"w": "旧候选"}]}],
        }
    )
    assert stream.alternative_texts == ("前文书秀", "前文旧候选")

    assert stream.apply_result(
        {
            "sn": 2,
            "pgs": "rpl",
            "rg": [1, 1],
            "ws": [{"cw": [{"w": "苏绣"}, {"w": "新候选"}]}],
        }
    )
    assert stream.current_text() == "前文苏绣"
    assert stream.candidates == ("前文苏绣", "前文新候选")
    assert "旧候选" not in "|".join(stream.alternative_texts)


def test_packets_contain_dialect_slm_options_resource_and_clean_hotwords() -> None:
    stream = XfyunStream(
        app_id="app",
        api_key="key",
        api_secret="secret",
        host="iat.cn-huabei-1.xf-yun.com",
        language="zh_cn",
        accent="mulacc",
        resource_id="  res-123 ",
        hotwords=[" 苏绣 ", "苏绣", "木|版年画", "", "甲\n乙"],
    )
    packet = stream._first_packet("")
    iat = packet["parameter"]["iat"]

    assert packet["header"]["res_id"] == "res-123"
    assert stream._middle_packet("")["header"]["res_id"] == "res-123"
    assert stream._last_packet()["header"]["res_id"] == "res-123"
    assert iat["domain"] == "slm"
    assert iat["language"] == "zh_cn"
    assert iat["accent"] == "mulacc"
    assert iat["dwa"] == "wpgs"
    assert "nbest" not in iat
    assert "wbest" not in iat
    assert iat["dhw"] == "utf-8;苏绣|木|版年画|甲|乙"
    assert len(iat["dhw"].encode("utf-8")) <= 1024


def test_default_packet_preserves_the_legacy_mandarin_contract() -> None:
    stream = make_stream()

    packet = stream._first_packet("")
    iat = packet["parameter"]["iat"]

    assert stream.host == "iat.xf-yun.com"
    assert iat["language"] == "zh_cn"
    assert iat["accent"] == "mandarin"
    assert iat["dwa"] == "wpgs"


def test_signed_url_uses_the_selected_profile_host() -> None:
    stream = XfyunStream(
        app_id="app",
        api_key="key",
        api_secret="secret",
        host="iat.cn-huabei-1.xf-yun.com",
        accent="mulacc",
    )

    parsed = urlparse(stream.signed_url())

    assert parsed.hostname == "iat.cn-huabei-1.xf-yun.com"
    assert parse_qs(parsed.query)["host"] == ["iat.cn-huabei-1.xf-yun.com"]


def test_multilingual_packet_uses_auto_language_contract_without_dialect_features() -> None:
    stream = XfyunStream(
        app_id="app",
        api_key="key",
        api_secret="secret",
        language="mul_cn",
        accent="mandarin",
        language_hint="en|ja",
        dynamic_correction=False,
        eos=6000,
    )

    packet = stream._first_packet("")
    iat = packet["parameter"]["iat"]

    assert iat == {
        "domain": "slm",
        "language": "mul_cn",
        "accent": "mandarin",
        "eos": 6000,
        "ln": "en|ja",
        "result": {"encoding": "utf8", "compress": "raw", "format": "json"},
    }
    assert packet["header"] == {"app_id": "app", "status": 0}


def test_provider_language_tracks_dominant_cw_lg_and_wpgs_replacement() -> None:
    result = {
        "ws": [
            {"cw": [{"w": "hello", "lg": "en"}]},
            {"cw": [{"w": "heritage", "lg": "en"}]},
            {"cw": [{"w": "遗产", "lg": "zh"}]},
        ]
    }
    assert XfyunStream.extract_language(result) == "en"

    stream = make_stream()
    stream.apply_result({"sn": 0, "ws": [{"cw": [{"w": "hello", "lg": "en"}]}]})
    stream.apply_result({"sn": 1, "ws": [{"cw": [{"w": "there", "lg": "en"}]}]})
    assert stream.detected_language == "en"

    stream.apply_result(
        {
            "sn": 2,
            "pgs": "rpl",
            "rg": [0, 1],
            "ws": [{"cw": [{"w": "你好", "lg": "zh"}]}],
        }
    )
    assert stream.detected_language == "zh"
    assert stream.current_text() == "你好"


def test_auto_stream_builds_distinct_new_and_legacy_profiles(monkeypatch) -> None:
    fake = install_fake_provider_streams(
        monkeypatch,
        results={AutoXfyunStream.DIALECT: "", AutoXfyunStream.MULTILINGUAL: ""},
    )

    AutoXfyunStream(
        app_id="dialect-app",
        api_key="dialect-key",
        api_secret="dialect-secret",
        multilingual_app_id="multi-app",
        multilingual_api_key="multi-key",
        multilingual_api_secret="multi-secret",
        hotwords=("苏绣",),
        resource_id="dialect-resource",
    )

    dialect = fake.instances[AutoXfyunStream.DIALECT].kwargs
    multilingual = fake.instances[AutoXfyunStream.MULTILINGUAL].kwargs
    legacy = fake.instances[AutoXfyunStream.LEGACY].kwargs
    assert dialect["language"] == "zh_cn"
    assert dialect["accent"] == "mulacc"
    assert dialect["dynamic_correction"] is True
    assert dialect["hotwords"] == ("苏绣",)
    assert dialect["resource_id"] == "dialect-resource"
    assert multilingual["app_id"] == "multi-app"
    assert multilingual["api_key"] == "multi-key"
    assert multilingual["language"] == "mul_cn"
    assert multilingual["accent"] == "mandarin"
    assert multilingual["dynamic_correction"] is False
    assert multilingual["eos"] == 6000
    assert multilingual["language_hint"] == "en|ja|ko"
    assert "hotwords" not in multilingual
    assert "resource_id" not in multilingual
    assert legacy["host"] == "iat.xf-yun.com"
    assert legacy["language"] == "zh_cn"
    assert legacy["accent"] == "mandarin"
    assert legacy["hotwords"] == ("苏绣",)
    assert legacy["resource_id"] == "dialect-resource"


def test_auto_stream_chooses_multilingual_for_non_chinese_provider_tag(monkeypatch) -> None:
    fake = install_fake_provider_streams(
        monkeypatch,
        results={
            AutoXfyunStream.DIALECT: "哈罗世界",
            AutoXfyunStream.MULTILINGUAL: "hello world",
        },
        languages={AutoXfyunStream.MULTILINGUAL: "en"},
    )

    async def scenario() -> None:
        stream = AutoXfyunStream(app_id="app", api_key="key", api_secret="secret")
        await stream.start()
        await stream.send_audio(b"pcm")

        assert await stream.finish() == "hello world"
        assert stream.selected_mode == AutoXfyunStream.MULTILINGUAL
        assert stream.detected_language == "en"
        assert stream.candidates == ("hello world",)
        assert all(child.audio == [b"pcm"] for child in fake.instances.values())

        await stream.close()
        assert all(child.closed for child in fake.instances.values())

    asyncio.run(scenario())


def test_auto_stream_rejects_english_tag_when_text_is_clearly_henan(monkeypatch) -> None:
    install_fake_provider_streams(
        monkeypatch,
        results={
            AutoXfyunStream.DIALECT: "恁看这个汴绣中不中，可得劲。",
            AutoXfyunStream.MULTILINGUAL: "Then. 看这个变秀中不中。 Could.",
        },
        languages={AutoXfyunStream.MULTILINGUAL: "en"},
    )

    async def scenario() -> None:
        stream = AutoXfyunStream(app_id="app", api_key="key", api_secret="secret")
        await stream.start()

        assert await stream.finish() == "恁看这个汴绣中不中，可得劲。"
        assert stream.selected_mode == AutoXfyunStream.DIALECT

    asyncio.run(scenario())


def test_auto_stream_falls_back_to_dialect_when_multilingual_finish_fails(
    monkeypatch,
) -> None:
    install_fake_provider_streams(
        monkeypatch,
        results={
            AutoXfyunStream.DIALECT: "我想听苏绣",
            AutoXfyunStream.MULTILINGUAL: VoiceProviderError("multilingual_failed"),
        },
        languages={AutoXfyunStream.MULTILINGUAL: "en"},
    )

    async def scenario() -> None:
        stream = AutoXfyunStream(app_id="app", api_key="key", api_secret="secret")
        await stream.start()

        assert await stream.finish() == "我想听苏绣"
        assert stream.selected_mode == AutoXfyunStream.DIALECT

    asyncio.run(scenario())


def test_auto_stream_falls_back_when_dialect_start_is_unavailable(monkeypatch) -> None:
    fake = install_fake_provider_streams(
        monkeypatch,
        results={
            AutoXfyunStream.DIALECT: "",
            AutoXfyunStream.MULTILINGUAL: "bonjour",
        },
        languages={AutoXfyunStream.MULTILINGUAL: "fr"},
        start_failures={AutoXfyunStream.DIALECT},
    )

    async def scenario() -> None:
        stream = AutoXfyunStream(app_id="app", api_key="key", api_secret="secret")
        await stream.start()
        await stream.send_audio(b"pcm")

        assert await stream.finish() == "bonjour"
        assert stream.selected_mode == AutoXfyunStream.MULTILINGUAL
        assert fake.instances[AutoXfyunStream.DIALECT].closed
        assert fake.instances[AutoXfyunStream.MULTILINGUAL].audio == [b"pcm"]

    asyncio.run(scenario())


def test_auto_stream_falls_back_to_legacy_when_new_models_are_unlicensed(
    monkeypatch,
) -> None:
    install_fake_provider_streams(
        monkeypatch,
        results={
            AutoXfyunStream.DIALECT: VoiceProviderError("dialect_unlicensed"),
            AutoXfyunStream.MULTILINGUAL: VoiceProviderError("multilingual_unlicensed"),
            AutoXfyunStream.LEGACY: "我想听苏绣",
        },
    )

    async def scenario() -> None:
        stream = AutoXfyunStream(app_id="app", api_key="key", api_secret="secret")
        await stream.start()

        assert await stream.finish() == "我想听苏绣"
        assert stream.selected_mode == AutoXfyunStream.LEGACY
        assert stream.candidates == ("我想听苏绣",)

    asyncio.run(scenario())


def test_optional_model_failures_do_not_turn_legacy_silence_into_an_outage(
    monkeypatch,
) -> None:
    install_fake_provider_streams(
        monkeypatch,
        results={
            AutoXfyunStream.DIALECT: VoiceProviderError("dialect_unlicensed"),
            AutoXfyunStream.MULTILINGUAL: VoiceProviderError("multilingual_unlicensed"),
            AutoXfyunStream.LEGACY: "",
        },
    )

    async def scenario() -> None:
        stream = AutoXfyunStream(app_id="app", api_key="key", api_secret="secret")
        await stream.start()

        assert await stream.finish() == ""
        assert stream.selected_mode == AutoXfyunStream.LEGACY

    asyncio.run(scenario())


def test_hotwords_are_bounded_to_1024_utf8_bytes() -> None:
    stream = XfyunStream(app_id="app", api_key="key", api_secret="secret", hotwords=["词" * 1000])

    assert len(stream._hotword_spec.encode("utf-8")) <= 1024
    assert stream._hotword_spec.startswith("utf-8;")


def test_receive_accepts_terminal_status_from_result_or_decoded_ls() -> None:
    async def scenario() -> None:
        for message in (
            {"header": {"code": 0, "status": 0}, "payload": {"result": {"status": 2}}},
            {
                "header": {"code": 0, "status": 0},
                "payload": {
                    "result": {"text": base64.b64encode(json.dumps({"ls": True}).encode()).decode()}
                },
            },
        ):

            class FakeSocket:
                def __aiter__(self):
                    return self

                async def __anext__(self):
                    if getattr(self, "sent", False):
                        raise StopAsyncIteration
                    self.sent = True
                    return json.dumps(message)

            stream = make_stream()
            stream._socket = FakeSocket()
            await stream._receive()
            assert stream._done.is_set()

    asyncio.run(scenario())


def test_dynamic_correction_replaces_only_the_requested_range() -> None:
    stream = make_stream()
    assert stream.apply_result({"sn": 0, "ws": [{"cw": [{"w": "后还有"}]}]})
    assert stream.apply_result({"sn": 1, "ws": [{"cw": [{"w": "书秀"}]}]})
    assert stream.current_text() == "后还有书秀"
    assert stream.apply_result(
        {"sn": 2, "pgs": "rpl", "rg": [1, 1], "ws": [{"cw": [{"w": "苏绣"}]}]}
    )
    assert stream.current_text() == "后还有苏绣"


def test_packets_follow_streaming_status_contract() -> None:
    stream = make_stream()
    audio = base64.b64encode(bytes(1280)).decode()

    first = stream._first_packet(audio)
    middle = stream._middle_packet(audio)
    last = stream._last_packet()

    assert first["header"] == {"app_id": "app", "status": 0}
    assert first["parameter"]["iat"]["dwa"] == "wpgs"
    assert first["payload"]["audio"]["status"] == 0
    assert middle["payload"]["audio"]["status"] == 1
    assert last["payload"]["audio"]["status"] == 2
    assert last["payload"]["audio"]["audio"] == ""
    assert [
        first["payload"]["audio"]["seq"],
        middle["payload"]["audio"]["seq"],
        last["payload"]["audio"]["seq"],
    ] == [1, 2, 3]


def test_audio_captured_before_provider_connect_is_flushed_in_order(monkeypatch) -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.packets: list[str] = []

        async def send(self, packet: str) -> None:
            self.packets.append(packet)

        async def close(self) -> None:
            return

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.Future()

    socket = FakeSocket()

    async def fake_connect(*_args, **_kwargs):
        return socket

    monkeypatch.setattr(voice_module, "connect", fake_connect)

    async def scenario() -> None:
        stream = make_stream()
        await stream.send_audio(bytes(stream.chunk_size))
        assert socket.packets == []
        await stream.start()
        assert len(socket.packets) == 1
        assert '"status": 0' in socket.packets[0]
        await stream.close()

    asyncio.run(scenario())


def test_handshake_cache_is_sent_on_a_40ms_paced_queue(monkeypatch) -> None:
    class FakeSocket:
        def __init__(self) -> None:
            self.packets: list[str] = []
            self.sent_at: list[float] = []

        async def send(self, packet: str) -> None:
            self.packets.append(packet)
            self.sent_at.append(asyncio.get_running_loop().time())

        async def close(self) -> None:
            return

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.Future()

    socket = FakeSocket()

    async def fake_connect(*_args, **_kwargs):
        return socket

    monkeypatch.setattr(voice_module, "connect", fake_connect)

    async def scenario() -> None:
        stream = make_stream()
        await stream.send_audio(bytes(stream.chunk_size) * 3)
        await stream.start()
        while len(socket.packets) < 3:
            await asyncio.sleep(0.005)
        statuses = [json.loads(packet)["header"]["status"] for packet in socket.packets]
        assert statuses == [0, 1, 1]
        assert socket.sent_at[1] - socket.sent_at[0] >= stream.frame_interval * 0.8
        assert socket.sent_at[2] - socket.sent_at[1] >= stream.frame_interval * 0.8
        await stream.close()

    asyncio.run(scenario())


def test_finish_queues_status_two_after_all_audio(monkeypatch) -> None:
    class FakeSocket:
        def __init__(self, stream: XfyunStream) -> None:
            self.stream = stream
            self.packets: list[str] = []

        async def send(self, packet: str) -> None:
            self.packets.append(packet)
            if json.loads(packet)["header"]["status"] == 2:
                self.stream._done.set()

        async def close(self) -> None:
            return

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.Future()

    async def scenario() -> None:
        stream = make_stream()
        socket = FakeSocket(stream)

        async def fake_connect(*_args, **_kwargs):
            return socket

        monkeypatch.setattr(voice_module, "connect", fake_connect)
        await stream.send_audio(bytes(stream.chunk_size) * 2)
        await stream.start()
        assert await stream.finish() == ""
        statuses = [json.loads(packet)["header"]["status"] for packet in socket.packets]
        assert statuses == [0, 1, 2]

    asyncio.run(scenario())


def test_cancel_and_close_stop_the_sender_without_leaking_queued_frames(monkeypatch) -> None:
    class FakeSocket:
        async def send(self, _packet: str) -> None:
            return

        async def close(self) -> None:
            return

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.Future()

    socket = FakeSocket()

    async def fake_connect(*_args, **_kwargs):
        return socket

    monkeypatch.setattr(voice_module, "connect", fake_connect)

    async def scenario() -> None:
        stream = make_stream()
        await stream.send_audio(bytes(stream.chunk_size) * 4)
        await stream.start()
        finishing = asyncio.create_task(stream.finish())
        await asyncio.sleep(0.005)
        finishing.cancel()
        await asyncio.gather(finishing, return_exceptions=True)
        await stream.close()
        assert stream._sender is None
        assert stream._receiver is None
        assert stream._send_queue.empty()

    asyncio.run(scenario())
