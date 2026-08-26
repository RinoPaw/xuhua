"""One small, deterministic retrieval core for the heritage knowledge base."""

from __future__ import annotations

import re
import logging
from collections.abc import Iterable, Sequence
from functools import lru_cache

from . import config
from .dataset import HeritageItem, KnowledgeBase, normalize_text


LOGGER = logging.getLogger(__name__)


_FILLERS = (
    "推荐适合", "适合做", "非物质文化遗产", "非遗项目", "策划一个", "生成讲解词",
    "生成讲解稿", "生成口播稿", "生成文案", "讲解词", "讲解稿", "口播稿", "解说词",
    "请介绍一下", "请介绍", "介绍一下", "是什么", "是啥", "值得了解", "想了解", "了解",
    "有哪些", "有那些", "有什么",
    "有啥", "写一段", "写一个", "帮我看看", "我想知道", "请问", "哪些", "讲讲", "说说",
    "推荐", "适合", "非遗", "项目", "介绍", "生成", "一下", "的", "给",
)
_PUNCTUATION = "？?！!。.，,、；;：:（）()[]【】{} \t\r\n"
_TOKEN_RE = re.compile(r"[\w\u4e00-\u9fff]+", re.UNICODE)
_MIN_LEXICAL_SCORE = 8.0
_PROVINCE_SUFFIX_RE = re.compile(
    r"(?:壮族自治区|回族自治区|维吾尔自治区|特别行政区|自治区|省|市)$"
)


def normalize_search_query(query: str) -> str:
    """Normalize a natural-language question to terms useful for retrieval."""
    text = normalize_text(str(query or "")).lower().strip(_PUNCTUATION)
    if not text:
        return ""
    for filler in _FILLERS:
        text = text.replace(filler, " ")
    text = re.sub(r"(?:\d{1,2}|[一二两三四五六七八九十]+)\s*(?:个|项|种|类)", " ", text)
    return re.sub(r"\s+", " ", text).strip(_PUNCTUATION + " ")


def tokenize(query: str) -> list[str]:
    """Return stable word/phrase tokens, including Chinese character bigrams."""
    text = normalize_search_query(query)
    tokens: list[str] = []
    for match in _TOKEN_RE.findall(text):
        if match not in tokens:
            tokens.append(match)
        # A Chinese phrase has no spaces, so bigrams make partial matching useful.
        if re.fullmatch(r"[\u4e00-\u9fff]+", match) and len(match) > 2:
            tokens.extend(match[i : i + 2] for i in range(len(match) - 1))
    return list(dict.fromkeys(tokens))


@lru_cache(maxsize=8)
def _province_aliases(kb: KnowledgeBase) -> tuple[tuple[str, str], ...]:
    names = {normalize_text(item.province) for item in kb.items if item.province}
    aliases: list[tuple[str, str]] = []
    for name in names:
        aliases.append((name, name))
        short = _PROVINCE_SUFFIX_RE.sub("", name)
        if short and short != name:
            aliases.append((short, name))
    return tuple(sorted(set(aliases), key=lambda pair: (-len(pair[0]), pair[0])))


def _resolve_province(kb: KnowledgeBase, value: str) -> tuple[str, str] | None:
    text = normalize_text(value)
    if not text:
        return None
    for alias, canonical in _province_aliases(kb):
        if text == alias or alias in text:
            return canonical, alias
    return None


@lru_cache(maxsize=8)
def _category_names(kb: KnowledgeBase) -> tuple[str, ...]:
    names = {normalize_text(category.name) for category in kb.categories if category.name}
    names.update(normalize_text(item.category) for item in kb.items if item.category)
    return tuple(sorted((name for name in names if name), key=lambda value: (-len(value), value)))


def _resolve_category(kb: KnowledgeBase, value: str) -> str:
    """Resolve a category stated in a natural-language question.

    A category phrase is a hard scope signal. Without this step a query such as
    ``有哪些传统音乐项目`` scores the word ``传统`` across almost the entire
    national catalogue and makes the first few results look arbitrary.
    """
    normalized = normalize_search_query(value)
    if not normalized:
        return ""
    matches = [
        name for name in _category_names(kb)
        if name == normalized or name in normalized
    ]
    if not matches:
        return ""
    longest = max(len(name) for name in matches)
    winners = [name for name in matches if len(name) == longest]
    return winners[0] if len(winners) == 1 else ""


@lru_cache(maxsize=8192)
def _aliases(item: HeritageItem) -> tuple[str, ...]:
    values = [item.family, *item.display_forms]
    return tuple(dict.fromkeys(normalize_text(value).lower() for value in values if value))


@lru_cache(maxsize=8192)
def _fields(item: HeritageItem) -> dict[str, str]:
    return {
        "title": normalize_text(item.title).lower(),
        "alias": " ".join(_aliases(item)),
        "category": normalize_text(item.category).lower(),
        "scenario": " ".join(
            normalize_text(value).lower() for value in item.suitable_scenarios if value
        ),
        "region": " ".join(
            normalize_text(value).lower()
            for value in (item.province, item.city, item.district)
            if value
        ),
        "summary": normalize_text(item.summary).lower(),
        "content": normalize_text(item.search_text or item.content).lower(),
    }


def _lexical_score(item: HeritageItem, query: str, tokens: Sequence[str]) -> float:
    if not query:
        return 0.0
    fields = _fields(item)
    score = 0.0
    # Exact/phrase matches carry the signal that users generally expect most.
    for name, weight in (
        ("title", 100.0), ("alias", 55.0), ("category", 32.0), ("scenario", 28.0),
        ("region", 24.0), ("summary", 18.0), ("content", 10.0),
    ):
        value = fields[name]
        if not value:
            continue
        if query == value:
            score += weight
        elif query in value:
            score += weight * 0.58

    # Token hits reward the same fields with smaller, additive weights.
    token_weights = {
        "title": 18.0, "alias": 11.0, "category": 8.0, "scenario": 8.0,
        "region": 7.0, "summary": 4.0, "content": 2.0,
    }
    for token in tokens:
        if len(token) < 2 and len(tokens) > 1:
            continue
        for name, weight in token_weights.items():
            value = fields[name]
            if token == value:
                score += weight * 1.25
            elif token in value:
                score += weight
    return score


def _sort_scored(scored: Iterable[tuple[float, HeritageItem]]) -> list[tuple[float, HeritageItem]]:
    return sorted(scored, key=lambda pair: (-pair[0], pair[1].title.casefold(), pair[1].id))


def _diversity_key(item: HeritageItem) -> tuple[str, str]:
    family = normalize_text(item.family or item.title).casefold()
    region = normalize_text(item.province or item.city or item.district or "未知地区").casefold()
    return family, region


def _diversify_scored(
    scored: Iterable[tuple[float, HeritageItem]],
    *,
    prefix_size: int = 40,
) -> list[tuple[float, HeritageItem]]:
    """Diversify only near-tied top results while preserving relevance.

    The algorithm is deterministic: within a relevance band it prefers a new
    family and region, then falls back to score/title/id. Strong exact matches
    remain ahead of the band, so this is not random exploration.
    """
    pairs = list(scored)
    # Preserve the source order for ties. The source order is deterministic,
    # while title sorting here would reintroduce the same alphabetical bias
    # that diversification is meant to remove.
    ordered = [
        pair
        for _index, pair in sorted(enumerate(pairs), key=lambda indexed: (-indexed[1][0], indexed[0]))
    ]
    if len(ordered) <= 1:
        return ordered
    prefix_length = min(prefix_size, len(ordered))
    remaining = ordered[:prefix_length]
    selected: list[tuple[float, HeritageItem]] = []
    while remaining:
        if not selected:
            selected.append(remaining.pop(0))
            continue
        best_score = remaining[0][0]
        tolerance = max(5.0, abs(best_score) * 0.18)
        eligible = [pair for pair in remaining if pair[0] >= best_score - tolerance]
        if not eligible:
            eligible = [remaining[0]]

        def preference(pair: tuple[float, HeritageItem]) -> tuple[int, int, float, str, str]:
            family, region = _diversity_key(pair[1])
            same_family = sum(_diversity_key(item)[0] == family for _, item in selected)
            same_region = sum(_diversity_key(item)[1] == region for _, item in selected)
            return (same_family, same_region, -pair[0], pair[1].title.casefold(), pair[1].id)

        picked = min(eligible, key=preference)
        remaining.remove(picked)
        selected.append(picked)
    return selected + ordered[prefix_length:]


def _pinyin_forms(text: str) -> list[str]:
    if not text:
        return []
    try:
        from pypinyin import lazy_pinyin
    except ImportError:
        return []
    return ["".join(lazy_pinyin(text)).lower()]


def _pinyin_score(item: HeritageItem, query: str) -> float:
    if len(query) < 2:
        return 0.0
    query_forms = _pinyin_forms(query)
    if not query_forms:
        return 0.0
    query_py = query_forms[0]
    title = _pinyin_forms(item.title)
    aliases = [form for alias in _aliases(item) for form in _pinyin_forms(alias)]
    if any(query_py == form for form in title):
        return 42.0
    if any(query_py in form for form in title):
        return 28.0
    if any(query_py == form for form in aliases):
        return 24.0
    if any(query_py in form for form in aliases):
        return 16.0
    return 0.0


def embedding_scores(
    kb: KnowledgeBase,
    query: str,
    candidates: Sequence[HeritageItem],
    min_score: float = 0.0,
) -> dict[str, float]:
    """Lazy proxy kept patchable for offline callers and optional embeddings."""
    from .embeddings import embedding_scores as score_embeddings

    return score_embeddings(kb, query, candidates, min_score=min_score)


def _semantic_scores(
    kb: KnowledgeBase,
    query: str,
    candidates: Sequence[HeritageItem],
) -> dict[str, float]:
    try:
        return embedding_scores(
            kb,
            query,
            candidates,
            min_score=config.EMBEDDING_MIN_SCORE,
        )
    except Exception as exc:  # noqa: BLE001 - semantic retrieval must degrade gracefully.
        LOGGER.info("retrieval.semantic.fallback reason=%s", type(exc).__name__)
        return {}


def _rank(
    kb: KnowledgeBase,
    candidates: Sequence[HeritageItem],
    query: str,
    use_pinyin: bool,
) -> list[HeritageItem]:
    tokens = tokenize(query)
    lexical = {item.id: _lexical_score(item, query, tokens) for item in candidates}
    pinyin = {item.id: _pinyin_score(item, query) for item in candidates} if use_pinyin else {}

    # Pinyin is a fallback signal, while a real lexical hit remains stronger.
    scores = {item.id: max(lexical[item.id], pinyin.get(item.id, 0.0)) for item in candidates}
    has_lexical_results = any(score >= _MIN_LEXICAL_SCORE for score in scores.values())
    if config.SEARCH_USE_EMBEDDING and query and not has_lexical_results:
        semantic = _semantic_scores(kb, query, candidates)
        if semantic:
            lexical_max = max(scores.values(), default=0.0) or 1.0
            semantic_max = max(semantic.values(), default=0.0) or 1.0
            for item in candidates:
                lexical_part = scores[item.id] / lexical_max if scores[item.id] else 0.0
                semantic_part = max(semantic.get(item.id, 0.0), 0.0) / semantic_max
                scores[item.id] = 0.7 * lexical_part + 0.3 * semantic_part
            return [
                item
                for score, item in _diversify_scored((scores[item.id], item) for item in candidates)
                if score > 0
                and (lexical[item.id] >= _MIN_LEXICAL_SCORE or item.id in semantic)
            ]

    return [
        item for score, item in _diversify_scored((scores[item.id], item) for item in candidates)
        if score >= _MIN_LEXICAL_SCORE
    ]


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
    use_pinyin: bool = True,
) -> tuple[list[HeritageItem], int]:
    """Filter, rank, and paginate heritage items with deterministic ordering."""
    category, province, level, district = (
        normalize_text(str(value or "")) for value in (category, province, level, district)
    )
    implicit_category = _resolve_category(kb, f"{query} {keywords}") if not category else ""
    if implicit_category:
        category = implicit_category
    raw_terms = normalize_text(f"{query} {keywords}")
    resolved_province = _resolve_province(kb, province) or _resolve_province(kb, raw_terms)
    province = resolved_province[0] if resolved_province else province
    candidates = [
        item for item in kb.items
        if (not category or item.category == category)
        and (not province or item.province == province)
        and (not level or item.level == level)
        and (not district or district in item.district)
    ]

    normalized_query = normalize_search_query(query)
    normalized_keywords = normalize_search_query(keywords)
    combined_query = " ".join(part for part in (normalized_query, normalized_keywords) if part)
    if resolved_province:
        canonical, alias = resolved_province
        combined_query = normalize_text(
            combined_query.replace(canonical.lower(), " ").replace(alias.lower(), " ")
        )
    if implicit_category:
        combined_query = normalize_text(
            combined_query.replace(normalize_search_query(implicit_category), " ")
        )
    if combined_query:
        ranked = _rank(kb, candidates, combined_query, use_pinyin)
    elif raw_terms and not resolved_province and not implicit_category:
        ranked = []
    else:
        ranked = [
            item
            for _score, item in _diversify_scored(
                (0.0, item)
                for item in sorted(
                    candidates,
                    key=lambda item: (item.category.casefold(), item.title.casefold(), item.id),
                )
            )
        ]

    start = max(int(offset), 0)
    size = max(int(limit), 0)
    return ranked[start : start + size], len(ranked)
