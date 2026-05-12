"""Model-calling functions for the heritage AI."""

from __future__ import annotations

import json
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .. import config
from ..dataset import HeritageItem, normalize_text


def should_use_zhipu_sdk() -> bool:
    host = urllib.parse.urlparse(config.AI_BASE_URL).hostname or ""
    return host.endswith("bigmodel.cn")


def zhipu_extra_options() -> dict[str, Any]:
    model = config.AI_MODEL.lower()
    thinking_models = ("glm-4.5", "glm-4.6", "glm-4.7", "glm-5")
    if any(name in model for name in thinking_models):
        return {"thinking": {"type": "disabled"}}
    return {}


def call_zhipu_sdk(question: str, sources: list[HeritageItem]) -> str:
    from ..ai.speech import build_messages

    return call_zhipu_messages(
        build_messages(question, sources),
        temperature=0.2,
        max_tokens=1000,
    )


def call_zhipu_messages(
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 1000,
) -> str:
    from zhipuai import ZhipuAI

    client = ZhipuAI(
        api_key=config.AI_API_KEY,
        base_url=config.AI_BASE_URL.rstrip("/"),
        timeout=config.AI_TIMEOUT,
        max_retries=0,
    )
    response = client.chat.completions.create(
        model=config.AI_MODEL,
        messages=messages,
        temperature=temperature,
        top_p=0.8,
        max_tokens=max_tokens,
        **zhipu_extra_options(),
        stream=False,
    )
    try:
        choice = response.choices[0]
        message = choice.message
    except (AttributeError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected model response: {response}") from exc

    text = (getattr(message, "content", "") or "").strip()
    if text:
        return text

    finish_reason = getattr(choice, "finish_reason", "")
    reasoning = getattr(message, "reasoning_content", "")
    detail = "Empty model response"
    if finish_reason:
        detail += f"; finish_reason={finish_reason}"
    if reasoning:
        detail += "; reasoning_content was returned without final content"
    raise RuntimeError(detail)


def call_openai_compatible_model(question: str, sources: list[HeritageItem]) -> str:
    from ..ai.speech import build_messages

    return call_openai_compatible_messages(
        build_messages(question, sources),
        temperature=0.2,
        max_tokens=1000,
    )


def call_openai_compatible_messages(
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 1000,
) -> str:
    payload = {
        "model": config.AI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    url = config.AI_BASE_URL.rstrip("/") + "/chat/completions"
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.AI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=config.AI_TIMEOUT) as response:
        body = json.loads(response.read().decode("utf-8"))

    try:
        return body["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected model response: {body}") from exc


def call_model_with_messages(
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 1000,
) -> str:
    if should_use_zhipu_sdk():
        return call_zhipu_messages(messages, temperature=temperature, max_tokens=max_tokens)
    return call_openai_compatible_messages(messages, temperature=temperature, max_tokens=max_tokens)


def call_chat_model(question: str, sources: list[HeritageItem]) -> str:
    from ..ai.speech import build_messages

    return call_model_with_messages(
        build_messages(question, sources),
        temperature=0.2,
        max_tokens=1000,
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
    if isinstance(exc, urllib.error.HTTPError):
        detail = f"HTTPError {exc.code}"
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - best effort diagnostics only.
            body = ""
        if body:
            detail += f": {body}"
        return sanitize_error(detail)

    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", "")
        return sanitize_error(f"URLError: {reason or exc}")

    detail = str(exc)
    if not detail:
        detail = type(exc).__name__
    return sanitize_error(f"{type(exc).__name__}: {detail}")


def sanitize_error(value: str, max_chars: int = 220) -> str:
    text = normalize_text(value)
    if config.AI_API_KEY:
        text = text.replace(config.AI_API_KEY, "***")
    return textwrap.shorten(text, width=max_chars, placeholder="...")
