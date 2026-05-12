"""Small dependency-free lexical search for the normalized dataset."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from functools import lru_cache

from . import config
from .dataset import HeritageItem, KnowledgeBase, normalize_text


LOGGER = logging.getLogger(__name__)
HYBRID_LEXICAL_CANDIDATES = 80
HYBRID_SEMANTIC_CANDIDATES = 80
RRF_K = 60
LEXICAL_RANK_WEIGHT = 1.3
SEMANTIC_RANK_WEIGHT = 1.35

# Pinyin fuzzy search constants
_PINYIN_MIN_QUERY_LEN = 2  # minimum query chars to try pinyin matching
_PINYIN_MATCH_BONUS = 0.3  # score for pinyin-exact match
_SEARCH_TRAILING_PUNCTUATION = "？?！!。.，,、 \t\r\n"
_SEARCH_QUERY_FILLERS = (
    "是什么",
    "是啥",
    "有哪些",
    "有那些",
    "有什么",
    "有啥",
    "生成讲解词",
    "生成讲解稿",
    "生成口播稿",
    "生成文案",
    "讲解词",
    "讲解稿",
    "口播稿",
    "解说词",
    "写一段",
    "写一个",
    "生成",
    "给",
    "请问",
    "请介绍一下",
    "请介绍",
    "介绍一下",
    "介绍",
    "讲讲",
    "说说",
    "帮我看看",
    "我想知道",
)


@lru_cache(maxsize=1)
def _build_pinyin_index(kb_hash: str) -> dict[str, list[str]]:
    """Build a pinyin-to-item-id index for all heritage items.

    Converts each item's title and family to pinyin and maps the
    resulting pinyin strings to item IDs for homophone fuzzy matching.
    kb_hash is a cache key derived from the dataset for thread safety.
    """
    try:
        from pypinyin import lazy_pinyin  # noqa: PLC0415 - optional dependency
        # We need kb inside the function but want the signature to accept
        # a cache key string.  Pull the singleton via dataset.
        from .dataset import load_dataset

        kb = load_dataset()
        index: dict[str, list[str]] = {}
        for item in kb.items:
            texts = [item.title]
            if item.family:
                texts.append(item.family)
            for text in texts:
                py = "".join(lazy_pinyin(text))
                py_compact = py.replace(" ", "")
                if py_compact:
                    index.setdefault(py_compact, []).append(item.id)
        LOGGER.info("Pinyin index built: %d entries", len(index))
        return index
    except ImportError:
        LOGGER.debug("pypinyin not installed, pinyin fuzzy search disabled")
        return {}


def search_items_pinyin(
    kb: KnowledgeBase,
    query: str,
) -> list[HeritageItem]:
    """Try pinyin-based homophone matching as a fallback.

    Converts the query characters to pinyin and looks for items whose
    title/family pinyin matches.  Returns [] when pypinyin is unavailable
    or no matches are found.
    """
    if not query or len(query) < _PINYIN_MIN_QUERY_LEN:
        return []

    index = _build_pinyin_index(kb.generated_at or str(len(kb.items)))
    if not index:
        return []

    try:
        from pypinyin import lazy_pinyin  # noqa: PLC0415 - optional dependency

        query_py = "".join(lazy_pinyin(query))
    except ImportError:
        return []

    matched_ids: list[str] = []

    # 1) Exact full-pinyin match
    if query_py in index:
        matched_ids.extend(index[query_py])

    # 2) Partial: query-pinyin and title-pinyin may contain each other.
    for py, ids in index.items():
        if py == query_py:
            continue
        if query_py in py or _is_substantial_pinyin_part(py, query_py):
            matched_ids.extend(ids)

    # Deduplicate and resolve
    seen: set[str] = set()
    result: list[HeritageItem] = []
    for item_id in matched_ids:
        if item_id in seen:
            continue
        seen.add(item_id)
        item = kb.get(item_id)
        if item is not None:
            result.append(item)

    return result


def _is_substantial_pinyin_part(candidate_py: str, query_py: str) -> bool:
    """Allow contained pinyin only when it covers a real chunk of the query."""
    if candidate_py not in query_py:
        return False
    if len(candidate_py) < 6:
        return False
    return len(candidate_py) >= len(query_py) * 0.45


def tokenize(query: str) -> list[str]:
    query = normalize_search_query(query)
    if not query:
        return []
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", query)
    if len(tokens) == 1:
        text = tokens[0]
        if len(text) > 2:
            tokens.extend(text[i : i + 2] for i in range(len(text) - 1))
        elif len(text) == 2:
            tokens.extend(ch for ch in text if "\u4e00" <= ch <= "\u9fff")
    return list(dict.fromkeys(tokens))


def normalize_search_query(query: str) -> str:
    """Reduce natural-language questions to the searchable subject terms."""
    text = normalize_text(query).lower().strip(_SEARCH_TRAILING_PUNCTUATION)
    if not text:
        return ""

    for filler in _SEARCH_QUERY_FILLERS:
        text = text.replace(filler, " ")
    text = re.sub(r"\s+", " ", text).strip(_SEARCH_TRAILING_PUNCTUATION)
    return text or normalize_text(query).lower().strip(_SEARCH_TRAILING_PUNCTUATION)


def search_items(
    kb: KnowledgeBase,
    query: str = "",
    category: str = "",
    province: str = "",
    level: str = "",
    district: str = "",
    keywords: str = "",
    limit: int = 30,
    offset: int = 0,
) -> tuple[list[HeritageItem], int]:
    query = normalize_text(query)
    category = normalize_text(category)
    province = normalize_text(province)
    level = normalize_text(level)
    district = normalize_text(district)
    keywords = normalize_text(keywords)
    candidates: Iterable[HeritageItem] = kb.items

    if category:
        candidates = (item for item in candidates if item.category == category)
    if province:
        candidates = (
            item for item in candidates
            if item.province == province
        )
    if level:
        candidates = (
            item for item in candidates
            if item.level == level
        )
    if district:
        candidates = (
            item for item in candidates
            if district in item.district
        )
    if keywords:
        query = f"{keywords} {query}".strip()

    candidates = list(candidates)

    if not query:
        result = sorted(candidates, key=lambda item: (item.category, item.title))
        return result[offset : offset + limit], len(result)

    search_query = normalize_search_query(query)
    tokens = tokenize(search_query)
    lowered_query = search_query or query.lower()
    ranked = rank_lexical(candidates, lowered_query, tokens)

    if config.SEARCH_USE_EMBEDDING:
        try:
            ranked = rank_hybrid(kb, candidates, lowered_query, tokens)
        except Exception:  # noqa: BLE001 - semantic retrieval should degrade to lexical search.
            pass

    result = [item for _, item in ranked]
    result = prepend_pinyin_matches(kb, result, search_query or query, candidates)
    return result[offset : offset + limit], len(result)


def search_items_lexical(
    kb: KnowledgeBase,
    query: str = "",
    category: str = "",
    province: str = "",
    level: str = "",
    district: str = "",
    keywords: str = "",
    limit: int = 30,
    offset: int = 0,
) -> tuple[list[HeritageItem], int]:
    """Fast lexical-only search that never calls the embedding API."""
    query = normalize_text(query)
    category = normalize_text(category)
    province = normalize_text(province)
    level = normalize_text(level)
    district = normalize_text(district)
    keywords = normalize_text(keywords)
    candidates: Iterable[HeritageItem] = kb.items

    if category:
        candidates = (item for item in candidates if item.category == category)
    if province:
        candidates = (
            item for item in candidates
            if item.province == province
        )
    if level:
        candidates = (
            item for item in candidates
            if item.level == level
        )
    if district:
        candidates = (
            item for item in candidates
            if district in item.district
        )
    if keywords:
        query = f"{keywords} {query}".strip()

    candidates = list(candidates)

    if not query:
        result = sorted(candidates, key=lambda item: (item.category, item.title))
        return result[offset : offset + limit], len(result)

    search_query = normalize_search_query(query)
    tokens = tokenize(search_query)
    lowered_query = search_query or query.lower()
    ranked = rank_lexical(candidates, lowered_query, tokens)

    result = [item for _, item in ranked]
    result = prepend_pinyin_matches(kb, result, search_query or query, candidates)

    return result[offset : offset + limit], len(result)


def prepend_pinyin_matches(
    kb: KnowledgeBase,
    ranked_items: list[HeritageItem],
    query: str,
    candidates: list[HeritageItem],
) -> list[HeritageItem]:
    """Place homophone title matches before normal ranked results.

    Pinyin matching is intentionally a lexical supplement: it helps misspelled
    or same-sound Chinese queries such as "落山" find "罗山", without feeding
    those same-sound tokens into embedding search.
    """
    if not query or len(query) < _PINYIN_MIN_QUERY_LEN:
        return ranked_items
    if has_title_substring_match(ranked_items, query):
        return ranked_items
    if has_location_token_match(ranked_items, query):
        return ranked_items

    candidate_ids = {item.id for item in candidates}
    pinyin_results = [
        item for item in search_items_pinyin(kb, query)
        if item.id in candidate_ids
    ]
    if not pinyin_results:
        return ranked_items

    pinyin_ids = {item.id for item in pinyin_results}
    return pinyin_results + [item for item in ranked_items if item.id not in pinyin_ids]


def has_title_substring_match(items: list[HeritageItem], query: str) -> bool:
    lowered_query = query.lower()
    return any(item.title and item.title.lower() in lowered_query for item in items)


def has_location_token_match(items: list[HeritageItem], query: str) -> bool:
    tokens = [token for token in tokenize(query) if len(token) >= 2]
    if not tokens:
        return False
    for item in items[:8]:
        location = f"{item.province} {item.city} {item.district}".lower()
        if any(token.lower() in location for token in tokens):
            return True
    return False


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
    family = item.family.lower()
    category = item.category.lower()
    bonus = 0.0

    if query == title:
        bonus += 0.7
    elif query in title:
        bonus += 0.35

    if query == family:
        bonus += 0.25
    elif family and query in family:
        bonus += 0.08

    if query == category:
        bonus += 0.2
    elif query in category:
        bonus += 0.1

    for token in tokens:
        if not token:
            continue
        if token == title:
            bonus += 0.06
        elif token in title:
            bonus += 0.004
        if token == family:
            bonus += 0.04
        elif family and token in family:
            bonus += 0.003
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
    family = item.family.lower()
    category = item.category.lower()
    province = item.province.lower()
    city = item.city.lower()
    district = item.district.lower()
    location = " ".join(part for part in (province, city, district) if part)
    summary = item.summary.lower()
    content = item.content.lower()
    search_text = item.search_text.lower()

    score = 0.0
    if query == title:
        score += 100
    if query and query in title:
        score += 40
    if query and query in family:
        score += 18
    if query and query in category:
        score += 16
    if query and query in location:
        score += 18
    if query and query in summary:
        score += 10
    if query and query in content:
        score += 5

    for token in tokens:
        if token in title:
            score += 12
        if token in family:
            score += 6
        if token in category:
            score += 5
        if token in province:
            score += 10
        elif token in city or token in district:
            score += 8
        if token in summary:
            score += 3
        if token in search_text:
            score += 1

    return score
