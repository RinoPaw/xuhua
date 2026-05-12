"""Model-calling functions for the heritage AI."""

from __future__ import annotations


from .. import config
from ..dataset import HeritageItem


def call_model_with_messages(
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 2000,
) -> str:
    """Send a chat completion via the unified http_client."""
    from ..http_client import chat_completion

    return chat_completion(messages, temperature, max_tokens)


def call_chat_model(question: str, sources: list[HeritageItem]) -> str:
    from ..ai.speech import build_messages

    return call_model_with_messages(
        build_messages(question, sources),
        temperature=0.2,
        max_tokens=2000,
    )


def call_speech_model(
    answer: str,
    question: str = "",
    sources: list[HeritageItem] | None = None,
    max_chars: int = 1800,
) -> str:
    from ..ai.speech import build_speech_messages

    return call_model_with_messages(
        build_speech_messages(answer, question=question, sources=sources or [], max_chars=max_chars),
        temperature=0.1,
        max_tokens=max(900, min(2400, max_chars + 300)),
    )


def describe_model_error(exc: Exception) -> str:
    from ..http_client import describe_error

    return describe_error(exc, config.AI_API_KEY)
