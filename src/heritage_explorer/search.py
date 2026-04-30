"""Small dependency-free lexical search for the normalized dataset."""

from __future__ import annotations

import re
from collections.abc import Iterable

from .dataset import HeritageItem, KnowledgeBase, normalize_text


def tokenize(query: str) -> list[str]:
    query = normalize_text(query).lower()
    if not query:
        return []
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", query)
    if len(tokens) == 1 and len(tokens[0]) > 2:
        text = tokens[0]
        tokens.extend(text[i : i + 2] for i in range(len(text) - 1))
    return list(dict.fromkeys(tokens))


def search_items(
    kb: KnowledgeBase,
    query: str = "",
    category: str = "",
    limit: int = 30,
    offset: int = 0,
) -> tuple[list[HeritageItem], int]:
    query = normalize_text(query)
    category = normalize_text(category)
    candidates: Iterable[HeritageItem] = kb.items

    if category:
        candidates = (item for item in candidates if item.category == category)

    if not query:
        result = sorted(candidates, key=lambda item: (item.category, item.title))
        return result[offset : offset + limit], len(result)

    tokens = tokenize(query)
    ranked: list[tuple[float, HeritageItem]] = []
    lowered_query = query.lower()

    for item in candidates:
        score = score_item(item, lowered_query, tokens)
        if score > 0:
            ranked.append((score, item))

    ranked.sort(key=lambda pair: (-pair[0], pair[1].title))
    result = [item for _, item in ranked]
    return result[offset : offset + limit], len(result)


def score_item(item: HeritageItem, query: str, tokens: list[str]) -> float:
    title = item.title.lower()
    category = item.category.lower()
    summary = item.summary.lower()
    content = item.content.lower()
    search_text = item.search_text.lower()

    score = 0.0
    if query == title:
        score += 100
    if query and query in title:
        score += 40
    if query and query in category:
        score += 16
    if query and query in summary:
        score += 10
    if query and query in content:
        score += 5

    for token in tokens:
        if token in title:
            score += 12
        if token in category:
            score += 5
        if token in summary:
            score += 3
        if token in search_text:
            score += 1

    return score
