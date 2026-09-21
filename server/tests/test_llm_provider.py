from __future__ import annotations

import asyncio

from heritage_explorer.providers.llm import OpenAICompatibleLLM


class _Response:
    def raise_for_status(self) -> None:
        return None

    async def aiter_lines(self):
        yield 'data: {"choices":[{"delta":{"content":"你好"}}]}'
        yield "data: [DONE]"


class _StreamContext:
    async def __aenter__(self):
        return _Response()

    async def __aexit__(self, *_exc_info: object) -> None:
        return None


class _Client:
    def __init__(self) -> None:
        self.payload: dict[str, object] | None = None

    def stream(self, _method: str, _url: str, **kwargs: object):
        self.payload = kwargs["json"]  # type: ignore[assignment]
        return _StreamContext()


def test_current_deepseek_flash_explicitly_disables_thinking() -> None:
    async def scenario() -> None:
        client = _Client()
        provider = OpenAICompatibleLLM(
            api_key="test-key",
            base_url="https://api.deepseek.com",
            model="deepseek-flash",
            client=client,
        )

        deltas = [
            delta
            async for delta in provider.stream_chat(
                [{"role": "user", "content": "你好"}],
                temperature=0.2,
                max_tokens=700,
            )
        ]

        assert deltas == ["你好"]
        assert client.payload is not None
        assert client.payload["model"] == "deepseek-flash"
        assert client.payload["thinking"] == {"type": "disabled"}

    asyncio.run(scenario())


def test_non_deepseek_provider_does_not_receive_vendor_thinking_parameter() -> None:
    async def scenario() -> None:
        client = _Client()
        provider = OpenAICompatibleLLM(
            api_key="test-key",
            base_url="https://example.invalid/v1",
            model="other-model",
            client=client,
        )

        _ = [delta async for delta in provider.stream_chat([{"role": "user", "content": "hi"}])]

        assert client.payload is not None
        assert "thinking" not in client.payload

    asyncio.run(scenario())
