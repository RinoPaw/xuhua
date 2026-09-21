"""Conversation retrieval intent and catalogue window policy."""

from __future__ import annotations

import hashlib
import re
from functools import lru_cache

from .dataset import KnowledgeBase, normalize_text
from .language import DEFAULT_LOCALE
from .search import normalize_search_query, tokenize

ITEM_COUNT_WORDS = {
    "一": 1,
    "两": 2,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}
CATALOGUE_BROWSE_ACTIONS = (
    "推荐",
    "有哪些",
    "哪些",
    "列举",
    "浏览",
    "查找",
    "搜索",
    "找几个",
    "找一些",
)
CATALOGUE_BROWSE_OBJECTS = ("项目", "资料", "类别", "门类")
HERITAGE_DOMAIN_TERMS = (
    "非物质文化遗产",
    "非遗",
    "民间文学",
    "传统音乐",
    "传统舞蹈",
    "传统戏剧",
    "曲艺",
    "传统体育",
    "游艺",
    "杂技",
    "传统美术",
    "传统技艺",
    "传统医药",
    "民俗",
    "戏曲",
    "舞蹈",
    "音乐",
    "美术",
    "技艺",
    "医药",
)
MULTILINGUAL_HERITAGE_TERMS = {
    "en-US": (
        "intangible cultural heritage",
        "cultural heritage",
        "heritage project",
        "heritage projects",
        "traditional craft",
        "traditional art",
    ),
    "ja-JP": ("無形文化遺産", "無形文化財", "伝統工芸", "伝統芸能"),
    "ko-KR": ("무형문화유산", "무형문화재", "전통 공예", "전통 예술"),
}
MULTILINGUAL_SEARCH_GLOSSES = {
    "en-US": (
        (("paper cutting",), "剪纸"),
        (("shadow puppetry", "shadow play"), "皮影戏"),
        (("kunqu opera", "kunqu", "kunku opera", "kunku"), "昆曲"),
        (("peking opera", "beijing opera"), "京剧"),
        (("dragon dance",), "龙舞"),
        (("lion dance",), "舞狮"),
        (("embroidery",), "刺绣"),
        (("traditional music",), "传统音乐"),
        (("traditional dance",), "传统舞蹈"),
        (("traditional theatre", "traditional theater", "opera"), "传统戏剧"),
        (("folk literature",), "民间文学"),
        (("folk customs", "customs", "festivals"), "民俗"),
        (("traditional medicine",), "传统医药"),
        (("traditional art", "fine arts"), "传统美术"),
        (("traditional craft", "craftsmanship", "crafts"), "传统技艺"),
    ),
    "ja-JP": (
        (("昆曲", "崑曲", "根極"), "昆曲"),
        (("伝統音楽",), "传统音乐"),
        (("伝統舞踊",), "传统舞蹈"),
        (("伝統演劇",), "传统戏剧"),
        (("民俗",), "民俗"),
        (("伝統美術",), "传统美术"),
        (("伝統工芸",), "传统技艺"),
    ),
    "ko-KR": (
        (("곤곡", "곤국"), "昆曲"),
        (("전통 음악",), "传统音乐"),
        (("전통 무용",), "传统舞蹈"),
        (("전통 연극",), "传统戏剧"),
        (("민속",), "民俗"),
        (("전통 미술",), "传统美术"),
        (("전통 공예",), "传统技艺"),
    ),
}
REGION_SUFFIX_RE = re.compile(
    r"(?:壮族自治区|回族自治区|维吾尔自治区|特别行政区|自治州|自治区|省|市|区|县|旗)$"
)


def requested_item_count(question: str) -> int | None:
    match = re.search(r"(\d{1,2}|[一二两三四五六七八九十])\s*(?:个|项|种|类)", question)
    if not match:
        match = re.search(
            r"\b(\d{1,2})\s*(?:projects?|items?|types?|traditions?|examples?)\b",
            question,
            flags=re.IGNORECASE,
        )
    if not match:
        return None
    token = match.group(1)
    return int(token) if token.isdigit() else ITEM_COUNT_WORDS[token]


@lru_cache(maxsize=8)
def catalogue_anchors(
    knowledge_base: KnowledgeBase,
) -> tuple[frozenset[str], frozenset[str], frozenset[str]]:
    item_names: set[str] = set()
    categories: set[str] = set()
    regions: set[str] = set()
    for item in knowledge_base.items:
        for value in (item.title, item.family, *item.display_forms):
            normalized = normalize_text(value).casefold()
            if len(normalized) >= 2:
                item_names.add(normalized)
        normalized_category = normalize_text(item.category).casefold()
        if len(normalized_category) >= 2:
            categories.add(normalized_category)
        for value in (item.province, item.city, item.district):
            normalized_region = normalize_text(value).casefold()
            if len(normalized_region) >= 2:
                regions.add(normalized_region)
            short_region = REGION_SUFFIX_RE.sub("", normalized_region)
            if len(short_region) >= 2:
                regions.add(short_region)
    return frozenset(item_names), frozenset(categories), frozenset(regions)


def translated_search_anchor(question: str, locale: str) -> str:
    folded = normalize_text(question).casefold()
    for phrases, canonical in MULTILINGUAL_SEARCH_GLOSSES.get(locale, ()):
        if any(phrase.casefold() in folded for phrase in phrases):
            return canonical
    return ""


def localized_search_query(question: str, locale: str, retrieval_basis: str) -> str:
    canonical = translated_search_anchor(question, locale)
    if canonical:
        return canonical
    if retrieval_basis == "multilingual_catalogue":
        return ""
    return question


def retrieval_basis(
    search: object,
    question: str,
    category: str = "",
    *,
    locale: str = DEFAULT_LOCALE,
) -> str:
    if normalize_text(category):
        return "ui_category"
    text = normalize_text(question).casefold()
    if not text:
        return "none"
    knowledge_base = getattr(search, "knowledge_base", None)
    if knowledge_base is not None:
        item_names, categories, regions = catalogue_anchors(knowledge_base)
        if any(name in text for name in item_names):
            return "item_name"
        if any(name in text for name in categories):
            return "category"
        if any(name in text for name in regions):
            return "region"
    if any(term in text for term in HERITAGE_DOMAIN_TERMS):
        return "heritage_domain"
    if translated_search_anchor(question, locale):
        return "translated_term"
    if any(term.casefold() in text for term in MULTILINGUAL_HERITAGE_TERMS.get(locale, ())):
        return "multilingual_catalogue"
    if any(action in text for action in CATALOGUE_BROWSE_ACTIONS) and any(
        target in text for target in CATALOGUE_BROWSE_OBJECTS
    ):
        return "catalogue_browse"
    return "none"


def is_scope_browse(search: object, question: str, category: str) -> bool:
    if not category and not any(
        marker in question for marker in ("哪些", "有哪些", "推荐", "值得", "想了解", "各类")
    ):
        return False
    residual = normalize_search_query(question)
    knowledge_base = getattr(search, "knowledge_base", None)
    category_names = [category]
    category_names.extend(
        category_item.name for category_item in getattr(knowledge_base, "categories", ())
    )
    for name in sorted(set(category_names), key=len, reverse=True):
        normalized = normalize_search_query(name)
        if normalized:
            residual = residual.replace(normalized, " ")
    return not normalize_text(residual).strip()


def exploration_offset(
    session_id: str,
    turn_id: str,
    question: str,
    total: int,
    limit: int,
) -> int:
    max_start = max(0, total - limit)
    if max_start == 0:
        return 0
    digest = hashlib.blake2s(
        f"{session_id}\0{turn_id}\0{normalize_search_query(question)}".encode("utf-8"),
        digest_size=8,
    ).digest()
    return 1 + int.from_bytes(digest, "big") % max_start


def candidate_limit(search: object, question: str, category: str, max_candidates: int) -> int:
    normalized = normalize_search_query(question).lower()
    knowledge_base = getattr(search, "knowledge_base", None)
    source_items = getattr(knowledge_base, "items", ())
    titles = {normalize_search_query(item.title).lower() for item in source_items if item.title}
    exact_titles = [title for title in titles if title and title in normalized]
    categories = {
        normalize_search_query(item.category).lower() for item in source_items if item.category
    }
    category_match = any(category_name and category_name in normalized for category_name in categories)
    broad_markers = (
        "哪些",
        "有哪些",
        "推荐",
        "值得了解",
        "想了解",
        "各类",
        "比较",
        "分别",
        "适合",
        "了解",
    )
    requested = requested_item_count(question)
    if exact_titles and not category_match and requested is None:
        return 1
    if requested is not None:
        return min(max_candidates, max(requested + 2, requested))
    if category.strip() or any(marker in question for marker in broad_markers):
        return max_candidates
    return min(max_candidates, max(2, len(tokenize(question)) + 1))


__all__ = [
    "candidate_limit",
    "catalogue_anchors",
    "exploration_offset",
    "is_scope_browse",
    "localized_search_query",
    "requested_item_count",
    "retrieval_basis",
    "translated_search_anchor",
]
