import asyncio

from heritage_explorer.voice_transport import VoiceWebSocketChannel


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
            channel.emit({"type": "first"}),
            channel.emit({"type": "second"}),
        )
        return websocket.messages

    messages = asyncio.run(scenario())

    assert [message["sequence"] for message in messages] == [1, 2]
    assert {message["connection_id"] for message in messages} == {"connection"}
    assert [message["type"] for message in messages] == ["first", "second"]
