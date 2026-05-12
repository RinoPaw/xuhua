"""Question answering over the heritage dataset."""

from __future__ import annotations

import logging
import re
import textwrap
from dataclasses import dataclass
from typing import Any

from .. import config
from ..dataset import HeritageItem, KnowledgeBase, item_to_dict, normalize_text
from ..search import normalize_search_query, search_items


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class Answer:
    answer: str
    mode: str
    sources: list[dict[str, Any]]
    speech: str = ""


def answer_question(kb: KnowledgeBase, question: str, category: str = "", include_speech: bool = True) -> Answer:
    from ..ai.client import call_chat_model, describe_model_error
    from ..ai.speech import build_spoken_answer

    question = normalize_text(question)
    category = normalize_text(category)
    if not question:
        answer = "请先输入问题。"
        return Answer(answer=answer, mode="empty", sources=[], speech=answer if include_speech else "")

    sources = fact_question_sources(kb, question=question, category=category, limit=5)
    if not sources:
        answer = "没有在数据集中找到足够相关的资料。"
        return Answer(answer=answer, mode="no_context", sources=[], speech=answer if include_speech else "")

    if config.AI_API_KEY:
        try:
            answer = call_chat_model(question, sources)
            return Answer(
                answer=answer,
                mode="llm",
                sources=[source_payload(item) for item in sources],
                speech=build_spoken_answer(answer, question=question, sources=sources) if include_speech else "",
            )
        except Exception as exc:  # noqa: BLE001 - API failures should gracefully fall back.
            LOGGER.warning("Chat model unavailable: %s", describe_model_error(exc))
            fallback = build_local_answer(question, sources)
            fallback += (
                "\n\n模型服务暂时不可用，已为你切换成本地依据式回答。"
            )
            return Answer(
                answer=fallback,
                mode="fallback",
                sources=[source_payload(item) for item in sources],
                speech=build_spoken_answer(fallback, question=question, sources=sources, prefer_model=False)
                if include_speech
                else "",
            )

    answer = build_local_answer(question, sources)
    return Answer(
        answer=answer,
        mode="local",
        sources=[source_payload(item) for item in sources],
        speech=build_spoken_answer(answer, question=question, sources=sources, prefer_model=False)
        if include_speech
        else "",
    )


def fact_question_sources(
    kb: KnowledgeBase,
    question: str,
    category: str = "",
    limit: int = 5,
) -> list[HeritageItem]:
    """Choose grounded sources for factual answers.

    Direct item questions like "汴绣是什么" should stay anchored to 汴绣 rather
    than using semantic search to fill the source list with loosely related items.
    """
    search_query = normalize_search_query(question)
    direct_matches = direct_item_matches(kb, search_query, category=category)
    if direct_matches:
        return direct_matches[:limit]

    sources, _ = search_items(kb, query=search_query or question, category=category, limit=limit)
    return sources


def direct_item_matches(
    kb: KnowledgeBase,
    search_query: str,
    category: str = "",
) -> list[HeritageItem]:
    search_query = normalize_text(search_query)
    category = normalize_text(category)
    if len(search_query) < 2:
        return []

    exact_title: list[HeritageItem] = []
    exact_family: list[HeritageItem] = []
    title_contains: list[HeritageItem] = []
    family_contains: list[HeritageItem] = []
    for item in kb.items:
        if category and item.category != category:
            continue
        title = normalize_text(item.title)
        family = normalize_text(item.family)

        if search_query == title:
            exact_title.append(item)
        elif title and (search_query in title or title in search_query):
            title_contains.append(item)
        elif family and search_query == family:
            exact_family.append(item)
        elif family and (search_query in family or family in search_query):
            family_contains.append(item)

    return _dedupe_items(exact_title) or _dedupe_items(title_contains + exact_family + family_contains)


def _dedupe_items(items: list[HeritageItem]) -> list[HeritageItem]:
    seen: set[str] = set()
    result: list[HeritageItem] = []
    for item in items:
        key = "|".join(
            normalize_text(part)
            for part in (
                item.title,
                item.family,
                item.category,
                item.province,
                item.city or item.district,
            )
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


def build_local_answer(question: str, sources: list[HeritageItem]) -> str:
    from ..ai.context import item_context_text

    lead = f"根据数据集中与“{question}”最相关的资料，可以先这样理解："
    bullets = []
    for item in sources[:3]:
        text = item_context_text(item) or item.summary or item.content
        snippet = summarize_snippet(text)
        bullets.append(f"- {item.title}（{item.category}）：{snippet}")
    return "\n".join([lead, *bullets])


def summarize_snippet(text: str, max_chars: int = 180) -> str:
    text = normalize_text(text)
    text = re.sub(r"^(介绍|历史|主要特色|重要价值|传承人)[:：]\s*", "", text)
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
