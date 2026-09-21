import asyncio

from heritage_explorer.voice import VoiceProviderError
from heritage_explorer.voice_events import ReadyEvent, VoiceStatusEvent
from heritage_explorer.voice_transport import (
    MAX_VOICE_FRAME_BYTES,
    VoiceWebSocketChannel,
    run_voice_transport,
)


class RecordingWebSocket:
    def __init__(self) -> None:
        self.messages: list[dict[str, object]] = []

    async def send_json(self, payload: dict[str, object]) -> None:
        self.messages.append(payload)


def test_websocket_channel_owns_connection_envelope_and_sequence() -> None:
    async def scenario() -> list[dict[str, object]]:
        websocket = RecordingWebSocket()
        channel = VoiceWebSocketChannel(websocket, connection_id="connection")  # type: ignore[arg-type]
        await asyncio.gather(
            channel.emit(ReadyEvent()),
            channel.emit(VoiceStatusEvent("listening", utterance_id=2)),
        )
        return websocket.messages

    messages = asyncio.run(scenario())

    assert [message["sequence"] for message in messages] == [1, 2]
    assert {message["connection_id"] for message in messages} == {"connection"}
    assert messages[0]["type"] == "ready"
    assert messages[1] == {
        "connection_id": "connection",
        "sequence": 2,
        "type": "status",
        "status": "listening",
        "utterance_id": 2,
    }


def test_transport_closes_oversized_frame_before_runtime_dispatch() -> None:
    class OversizedWebSocket(RecordingWebSocket):
        def __init__(self) -> None:
            super().__init__()
            self.closed: tuple[int, str] | None = None
            self.received = False

        async def receive(self) -> dict[str, object]:
            if self.received:
                return {"type": "websocket.disconnect"}
            self.received = True
            return {
                "type": "websocket.receive",
                "bytes": b"x" * (MAX_VOICE_FRAME_BYTES + 1),
            }

        async def close(self, *, code: int, reason: str) -> None:
            self.closed = (code, reason)

    class Runtime:
        def __init__(self) -> None:
            self.audio_calls = 0
            self.closed = False

        async def handle_audio(self, _data: bytes) -> None:
            self.audio_calls += 1

        async def close(self) -> None:
            self.closed = True

    async def scenario():
        websocket = OversizedWebSocket()
        runtime = Runtime()
        channel = VoiceWebSocketChannel(websocket, connection_id="connection")  # type: ignore[arg-type]
        await run_voice_transport(websocket, channel, runtime)  # type: ignore[arg-type]
        return websocket, runtime

    websocket, runtime = asyncio.run(scenario())
    assert websocket.closed == (1009, "voice_frame_too_large")
    assert runtime.audio_calls == 0
    assert runtime.closed is True


def test_transport_closes_provider_backlog_with_retryable_code() -> None:
    class AudioWebSocket(RecordingWebSocket):
        def __init__(self) -> None:
            super().__init__()
            self.closed: tuple[int, str] | None = None
            self.received = False

        async def receive(self) -> dict[str, object]:
            if self.received:
                return {"type": "websocket.disconnect"}
            self.received = True
            return {"type": "websocket.receive", "bytes": b"pcm"}

        async def close(self, *, code: int, reason: str) -> None:
            self.closed = (code, reason)

    class Runtime:
        def __init__(self) -> None:
            self.closed = False

        async def handle_audio(self, _data: bytes) -> None:
            raise VoiceProviderError("voice_audio_backlog")

        async def close(self) -> None:
            self.closed = True

    async def scenario():
        websocket = AudioWebSocket()
        runtime = Runtime()
        channel = VoiceWebSocketChannel(websocket, connection_id="connection")  # type: ignore[arg-type]
        await run_voice_transport(websocket, channel, runtime)  # type: ignore[arg-type]
        return websocket, runtime

    websocket, runtime = asyncio.run(scenario())
    assert websocket.closed == (1013, "voice_audio_backlog")
    assert runtime.closed is True
