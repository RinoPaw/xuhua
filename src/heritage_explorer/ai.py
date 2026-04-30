"""Retrieval-augmented question answering over the heritage dataset."""

from __future__ import annotations

import json
import textwrap
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any

from . import config
from .dataset import HeritageItem, KnowledgeBase, item_to_dict, normalize_text
from .search import search_items


@dataclass(frozen=True)
class Answer:
    answer: str
    mode: str
    sources: list[dict[str, Any]]


def answer_question(kb: KnowledgeBase, question: str, category: str = "") -> Answer:
    question = normalize_text(question)
    category = normalize_text(category)
    if not question:
        return Answer(answer="请先输入问题。", mode="empty", sources=[])

    sources, _ = search_items(kb, query=question, category=category, limit=5)
    if not sources:
        return Answer(answer="没有在数据集中找到足够相关的资料。", mode="no_context", sources=[])

    if config.AI_API_KEY:
        try:
            return Answer(
                answer=call_chat_model(question, sources),
                mode="llm",
                sources=[source_payload(item) for item in sources],
            )
        except Exception as exc:  # noqa: BLE001 - API failures should gracefully fall back.
            fallback = build_local_answer(question, sources)
            fallback += (
                "\n\n模型接口暂不可用，已退回本地依据式回答。"
                f"错误：{describe_model_error(exc)}"
            )
            return Answer(
                answer=fallback,
                mode="fallback",
                sources=[source_payload(item) for item in sources],
            )

    return Answer(
        answer=build_local_answer(question, sources),
        mode="local",
        sources=[source_payload(item) for item in sources],
    )


def call_chat_model(question: str, sources: list[HeritageItem]) -> str:
    if should_use_zhipu_sdk():
        return call_zhipu_sdk(question, sources)
    return call_openai_compatible_model(question, sources)


def call_zhipu_sdk(question: str, sources: list[HeritageItem]) -> str:
    from zhipuai import ZhipuAI

    client = ZhipuAI(
        api_key=config.AI_API_KEY,
        base_url=config.AI_BASE_URL.rstrip("/"),
        timeout=config.AI_TIMEOUT,
        max_retries=0,
    )
    response = client.chat.completions.create(
        model=config.AI_MODEL,
        messages=build_messages(question, sources),
        temperature=0.2,
        top_p=0.8,
        max_tokens=1000,
        stream=False,
    )
    try:
        return response.choices[0].message.content.strip()
    except (AttributeError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected model response: {response}") from exc


def call_openai_compatible_model(question: str, sources: list[HeritageItem]) -> str:
    payload = {
        "model": config.AI_MODEL,
        "messages": build_messages(question, sources),
        "temperature": 0.2,
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


def build_messages(question: str, sources: list[HeritageItem]) -> list[dict[str, str]]:
    context = build_context(sources, config.AI_MAX_CONTEXT_CHARS)
    return [
            {
                "role": "system",
                "content": (
                    "你是一个严谨的非物质文化遗产知识库助手。"
                    "只能依据给定资料回答；资料不足时要直接说明。"
                    "回答应使用中文，条理清晰，保留项目名称和类别。"
                ),
            },
            {
                "role": "user",
                "content": f"问题：{question}\n\n资料：\n{context}",
            },
    ]


def should_use_zhipu_sdk() -> bool:
    host = urllib.parse.urlparse(config.AI_BASE_URL).hostname or ""
    return host.endswith("bigmodel.cn")


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


def build_context(sources: list[HeritageItem], max_chars: int) -> str:
    chunks = []
    remaining = max_chars
    for index, item in enumerate(sources, start=1):
        text = item.summary or item.content
        text = normalize_text(text)
        chunk = f"[{index}] 标题：{item.title}\n类别：{item.category}\n资料：{text}"
        if len(chunk) > remaining:
            chunk = chunk[: max(0, remaining - 20)] + "..."
        chunks.append(chunk)
        remaining -= len(chunk)
        if remaining <= 0:
            break
    return "\n\n".join(chunks)


def build_local_answer(question: str, sources: list[HeritageItem]) -> str:
    lead = f"根据数据集中与“{question}”最相关的资料，可以先这样理解："
    bullets = []
    for item in sources[:3]:
        text = item.summary or item.content
        snippet = summarize_snippet(text)
        bullets.append(f"- {item.title}（{item.category}）：{snippet}")
    return "\n".join([lead, *bullets])


def summarize_snippet(text: str, max_chars: int = 180) -> str:
    text = normalize_text(text)
    if not text:
        return "暂无摘要。"
    sentences = [part.strip() for part in text.replace("；", "。").split("。") if part.strip()]
    snippet = "。".join(sentences[:2]) if sentences else text
    snippet = textwrap.shorten(snippet, width=max_chars, placeholder="...")
    return snippet.rstrip("。") + "。"


def source_payload(item: HeritageItem) -> dict[str, Any]:
    data = item_to_dict(item)
    data["excerpt"] = summarize_snippet(item.content, max_chars=120)
    return data
