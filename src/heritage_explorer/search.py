"""Small dependency-free lexical search for the normalized dataset."""

from __future__ import annotations

import re
from collections.abc import Iterable

from . import config
from .dataset import HeritageItem, KnowledgeBase, normalize_text


HYBRID_LEXICAL_CANDIDATES = 80
HYBRID_SEMANTIC_CANDIDATES = 80
RRF_K = 60
LEXICAL_RANK_WEIGHT = 1.0
SEMANTIC_RANK_WEIGHT = 1.35


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
    candidates = list(candidates)

    if not query:
        result = sorted(candidates, key=lambda item: (item.category, item.title))
        return result[offset : offset + limit], len(result)

    tokens = tokenize(query)
    lowered_query = query.lower()
    ranked = rank_lexical(candidates, lowered_query, tokens)

    if config.SEARCH_USE_EMBEDDING:
        try:
            ranked = rank_hybrid(kb, candidates, lowered_query, tokens)
        except Exception:  # noqa: BLE001 - semantic retrieval should degrade to lexical search.
            pass

    result = [item for _, item in ranked]
    return result[offset : offset + limit], len(result)


def rank_lexical(
    candidates: Iterable[HeritageItem],
    lowered_query: str,
    tokens: list[str],
) -> list[tuple[float, HeritageItem]]:
    ranked: list[tuple[float, HeritageItem]] = []

    for item in candidates:
        score = score_item(item, lowered_query, tokens)
        if score > 0:
            ranked.append((score, item))

    ranked.sort(key=lambda pair: (-pair[0], pair[1].title))
    return ranked


def rank_hybrid(
    kb: KnowledgeBase,
    candidates: list[HeritageItem],
    lowered_query: str,
    tokens: list[str],
) -> list[tuple[float, HeritageItem]]:
    from .embeddings import embedding_scores

    semantic_scores = embedding_scores(kb, lowered_query, candidates, min_score=0.0)
    lexical_ranked = rank_lexical(candidates, lowered_query, tokens)
    lexical_scores = {item.id: score for score, item in lexical_ranked}
    items_by_id = {item.id: item for item in candidates}
    candidate_ids: set[str] = set()
    rank_scores: dict[str, float] = {}

    add_rank_signal(
        rank_scores,
        lexical_ranked[:HYBRID_LEXICAL_CANDIDATES],
        LEXICAL_RANK_WEIGHT,
    )
    candidate_ids.update(item.id for _, item in lexical_ranked[:HYBRID_LEXICAL_CANDIDATES])

    semantic_ranked = [
        (score, item)
        for item_id, score in semantic_scores.items()
        if (item := items_by_id.get(item_id)) is not None
    ]
    semantic_ranked.sort(key=lambda pair: (-pair[0], pair[1].title))
    add_rank_signal(
        rank_scores,
        semantic_ranked[:HYBRID_SEMANTIC_CANDIDATES],
        SEMANTIC_RANK_WEIGHT,
    )
    candidate_ids.update(item.id for _, item in semantic_ranked[:HYBRID_SEMANTIC_CANDIDATES])

    for item in candidates:
        if strong_match_bonus(item, lowered_query, tokens) > 0:
            candidate_ids.add(item.id)

    ranked: list[tuple[float, HeritageItem]] = []
    for item_id in candidate_ids:
        item = items_by_id[item_id]
        score = rank_scores.get(item_id, 0.0)
        score += strong_match_bonus(item, lowered_query, tokens)
        score += lexical_tiebreak(lexical_scores.get(item_id, 0.0))
        ranked.append((score, item))

    ranked.sort(key=lambda pair: (-pair[0], pair[1].title))
    return ranked


def add_rank_signal(
    rank_scores: dict[str, float],
    ranked: list[tuple[float, HeritageItem]],
    weight: float,
) -> None:
    for rank, (_, item) in enumerate(ranked, start=1):
        rank_scores[item.id] = rank_scores.get(item.id, 0.0) + weight / (RRF_K + rank)


def strong_match_bonus(item: HeritageItem, query: str, tokens: list[str]) -> float:
    if not query:
        return 0.0

    title = item.title.lower()
    category = item.category.lower()
    aliases = [alias.lower() for alias in item.aliases]
    bonus = 0.0

    if query == title or query in aliases:
        bonus += 0.7
    elif query in title or any(query in alias for alias in aliases):
        bonus += 0.35

    if query == category:
        bonus += 0.2
    elif query in category:
        bonus += 0.1

    for token in tokens:
        if not token:
            continue
        if token == title or token in aliases:
            bonus += 0.06
        elif token in title or any(token in alias for alias in aliases):
            bonus += 0.004
        if token == category:
            bonus += 0.08
        elif token in category:
            bonus += 0.003

    return bonus


def lexical_tiebreak(score: float) -> float:
    if score <= 0:
        return 0.0
    return min(score, 100.0) / 10000.0


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
