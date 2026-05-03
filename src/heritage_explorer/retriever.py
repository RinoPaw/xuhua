"""Query understanding, multi-stage retrieval, and re-ranking."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .agent import TaskType
from .dataset import HeritageItem, KnowledgeBase


_PROVINCE_PATTERN = re.compile(
    r"("
    r"北京市|天津市|上海市|重庆市|"
    r"香港特别行政区|澳门特别行政区|"
    r"内蒙古自治区|广西壮族自治区|西藏自治区|宁夏回族自治区|新疆维吾尔自治区|"
    r"黑龙江省|吉林省|辽宁省|河北省|河南省|山东省|山西省|"
    r"陕西省|甘肃省|青海省|四川省|贵州省|云南省|海南省|"
    r"广东省|湖南省|湖北省|安徽省|江苏省|浙江省|福建省|"
    r"江西省|台湾省"
    r")"
)

_LEVEL_TERMS = {"国家级", "省级", "人类", "联合国教科文组织", "世界级", "市级", "县级"}

_AUDIENCE_MAP: dict[str, str] = {
    "中小学": "青少年",
    "小学生": "儿童",
    "中学生": "青少年",
    "大学生": "成人",
    "青少年": "青少年",
    "儿童": "儿童",
    "幼儿": "儿童",
    "成人": "成人",
    "老年人": "老年",
    "亲子": "家庭",
}

_SCENARIO_MAP: dict[str, str] = {
    "校园": "校园展览",
    "社区": "社区活动",
    "旅游": "文旅推广",
    "景区": "文旅推广",
    "商场": "商业展示",
    "博物馆": "文博展览",
    "线上": "线上展示",
    "数字": "线上展示",
}

_COUNT_PATTERN = re.compile(r"(\d+)\s*[个项条种]")

_COMPARISON_SPLIT_PATTERN = re.compile(
    r"(?:比较|对比|和|与|跟|同|以及|还有|VS\.?)\s*",
    re.IGNORECASE,
)


@dataclass
class QueryPlan:
    original_query: str
    rewritten_query: str = ""
    entities: dict[str, list[str]] = field(default_factory=dict)
    metadata_filters: dict[str, str] = field(default_factory=dict)
    expansion_terms: list[str] = field(default_factory=list)
    soft_constraints: dict[str, str] = field(default_factory=dict)
    retrieval_count: int = 5
    task_type: TaskType | None = None


@dataclass
class ScoredItem:
    item: HeritageItem
    lexical_score: float = 0.0
    semantic_score: float = 0.0
    final_score: float = 0.0
    rerank_reason: str = ""


class QueryAnalyzer:
    """Analyze a raw user query into a structured QueryPlan.

    Extracts explicit entities (province, category, level, count),
    rewrites the query for better retrieval, and expands synonyms.
    """

    def __init__(self, kb: KnowledgeBase) -> None:
        self._category_names = [c.name for c in kb.categories]

    def analyze(self, query: str, task_type: TaskType | None = None) -> QueryPlan:
        entities: dict[str, list[str]] = {}
        soft: dict[str, str] = {}
        filters: dict[str, str] = {}

        province = self._extract_province(query)
        if province:
            entities["province"] = [province]
            filters["province"] = province

        category = self._extract_category(query)
        if category:
            entities["category"] = [category]
            filters["category"] = category

        levels = self._extract_levels(query)
        if levels:
            entities["level"] = levels
            filters["level"] = levels[0]

        audience = self._extract_audience(query)
        if audience:
            entities["audience"] = list({v for k, v in _AUDIENCE_MAP.items() if k in audience})
            soft["audience"] = entities["audience"][0]

        scenario = self._extract_scenario(query)
        if scenario:
            entities["scenario"] = list({v for k, v in _SCENARIO_MAP.items() if k in scenario})
            soft["scenario"] = entities["scenario"][0]

        count = self._extract_count(query)
        retrieval_count = count if count else self._default_retrieval_count(task_type)

        rewritten = self._rewrite_query(query, task_type)

        expansion = self._build_expansions(entities, rewritten)

        comparison_entities: list[str] = []
        if task_type is TaskType.COMPARISON:
            comparison_entities = self._extract_comparison_entities(query)
            if comparison_entities:
                entities["comparison_targets"] = comparison_entities
                rewritten = " ".join(comparison_entities)

        return QueryPlan(
            original_query=query,
            rewritten_query=rewritten,
            entities=entities,
            metadata_filters=filters,
            expansion_terms=expansion,
            soft_constraints=soft,
            retrieval_count=retrieval_count,
            task_type=task_type,
        )

    def _extract_province(self, query: str) -> str:
        match = _PROVINCE_PATTERN.search(query)
        return match.group(1) if match else ""

    def _extract_category(self, query: str) -> str:
        match = re.search(
            r"(传统戏剧|传统音乐|传统美术|传统舞蹈|传统医药|民俗|传统技艺|曲艺|传统体育|民间文学)",
            query,
        )
        if match:
            name = match.group(1)
            if name == "传统体育":
                return "传统体育、游艺与杂技"
            return name
        for name in self._category_names:
            if name in query:
                return name
        return ""

    def _extract_levels(self, query: str) -> list[str]:
        return [term for term in _LEVEL_TERMS if term in query]

    def _extract_audience(self, query: str) -> list[str]:
        return [k for k in _AUDIENCE_MAP if k in query]

    def _extract_scenario(self, query: str) -> list[str]:
        return [k for k in _SCENARIO_MAP if k in query]

    def _extract_count(self, query: str) -> int:
        match = _COUNT_PATTERN.search(query)
        return int(match.group(1)) if match else 0

    def _extract_comparison_entities(self, original: str) -> list[str]:
        cleaned = original.strip()
        cleaned = _COMPARISON_SPLIT_PATTERN.sub(" | ", cleaned)
        cleaned = _COUNT_PATTERN.sub("", cleaned)
        cleaned = re.sub(
            r"推荐|适合|哪些|帮我找|有哪些|列出|筛选|过滤|哪个更",
            "",
            cleaned,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        parts = [p.strip() for p in cleaned.split("|")]
        names = [p for p in parts if p and len(p) >= 2]
        return names or parts

    @staticmethod
    def _default_retrieval_count(task_type: TaskType | None) -> int:
        if task_type is None:
            return 5
        limits: dict[TaskType, int] = {
            TaskType.FACTUAL_QA: 5,
            TaskType.COMPARISON: 8,
            TaskType.RECOMMENDATION: 10,
            TaskType.EXHIBITION_PLAN: 5,
            TaskType.CURRICULUM_DESIGN: 5,
            TaskType.CREATIVE_BRIEF: 5,
            TaskType.DATA_EXPLORE: 20,
            TaskType.MULTI_FILTER: 30,
        }
        return limits.get(task_type, 5)

    def _rewrite_query(self, query: str, task_type: TaskType | None) -> str:
        cleaned = query
        cleaned = _PROVINCE_PATTERN.sub("", cleaned)
        for term in _LEVEL_TERMS:
            cleaned = cleaned.replace(term, "")
        for k in _AUDIENCE_MAP:
            cleaned = cleaned.replace(k, "")
        for k in _SCENARIO_MAP:
            cleaned = cleaned.replace(k, "")
        cleaned = _COUNT_PATTERN.sub("", cleaned)
        cleaned = re.sub(
            r"推荐|适合|哪些|帮我找|比较|对比|有哪些|列出|筛选|过滤|限定|只看|只要",
            "",
            cleaned,
        )
        if task_type is TaskType.COMPARISON:
            cleaned = _COMPARISON_SPLIT_PATTERN.sub(" ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned or query

    def _build_expansions(
        self, entities: dict[str, list[str]], rewritten: str
    ) -> list[str]:
        terms: list[str] = []
        for entity in entities.get("province", []):
            short = entity.rstrip("省市自治区").replace("壮族", "").replace("回族", "").replace("维吾尔", "")
            if len(short) >= 2 and short != entity:
                terms.append(short)
        expanded_query = " ".join([rewritten, *terms])
        from .search import tokenize

        return tokenize(expanded_query)
