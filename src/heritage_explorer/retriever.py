"""Query understanding, multi-stage retrieval, and re-ranking."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .agent_models import TaskType
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
    "校园": "校园展示",
    "展览": "校园展示",
    "社区": "社区活动",
    "展馆": "展馆讲解",
    "讲解": "展馆讲解",
    "研学": "研学体验",
    "体验": "研学体验",
    "文创": "文创设计",
    "设计": "文创设计",
}

_COUNT_PATTERN = re.compile(r"(\d+|[一二两三四五六七八九十])\s*[个项条种]")

_CN_NUM_MAP: dict[str, int] = {
    "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
    "六": 6, "七": 7, "八": 8, "九": 9, "十": 10,
}
_CITY_PATTERN = re.compile(r"([一-鿿]{2,4}(?:市|地区|州|盟|自治州))")

_SHORT_PROVINCE_MAP: dict[str, str] = {
    "河南": "河南省", "河北": "河北省", "山东": "山东省", "山西": "山西省",
    "陕西": "陕西省", "甘肃": "甘肃省", "青海": "青海省", "四川": "四川省",
    "贵州": "贵州省", "云南": "云南省", "海南": "海南省", "广东": "广东省",
    "湖南": "湖南省", "湖北": "湖北省", "安徽": "安徽省", "江苏": "江苏省",
    "浙江": "浙江省", "福建": "福建省", "江西": "江西省", "台湾": "台湾省",
    "辽宁": "辽宁省", "吉林": "吉林省", "黑龙江": "黑龙江省",
}

_CONSTRAINT_KEYWORDS: dict[str, str] = {
    "展示难度低": "展示难度低",
    "容易展示": "展示难度低",
    "适合短时间": "适合短时间",
    "短时间": "适合短时间",
    "互动性强": "互动性强",
    "互动": "互动性强",
    "趣味性": "趣味性强",
    "适合户外": "适合户外",
    "户外": "适合户外",
    "成本低": "成本低",
    "低成本": "成本低",
    "便于运输": "便于运输",
}

_TIME_BUDGET_PATTERN = re.compile(
    r"(\d+)\s*(?:分钟|小时|天)|半天|一小时|两小时|三小时|一上午|一下午|全天"
)

_TONE_KEYWORDS: dict[str, str] = {
    "正式": "正式",
    "年轻化": "年轻化",
    "展板风": "展板风",
    "展板": "展板风",
    "讲解风": "讲解风",
    "讲解": "讲解风",
    "朋友圈": "朋友圈",
    "口语化": "口语化",
    "学术": "学术",
}

_OUTPUT_FORMAT_KEYWORDS: dict[str, str] = {
    "列表": "列表",
    "表格": "表格",
    "方案": "方案文档",
    "文档": "方案文档",
    "策划案": "方案文档",
    "文案": "文案",
}

_TRANSFORM_TYPE_KEYWORDS: dict[str, str] = {
    "翻译": "翻译",
    "英文": "翻译",
    "英语": "翻译",
    "中英": "翻译",
    "双语": "翻译",
    "translate": "翻译",
    "讲解词": "讲解词",
    "讲解稿": "讲解词",
    "口播稿": "讲解词",
    "解说词": "讲解词",
    "年轻化": "年轻化",
    "朋友圈": "朋友圈",
    "文创": "文创文案",
    "科普": "科普文案",
}

_COMPARISON_SPLIT_PATTERN = re.compile(
    r"(?:比较|对比|和|与|跟|同|以及|还有|VS\.?)\s*",
    re.IGNORECASE,
)
_COMPARISON_TRAILING_PATTERN = re.compile(
    r"(?:有什么区别|有什么不同|有何区别|有何不同|的区别|的差异|哪个更好|哪个更适合|哪个更|哪个好|区别在哪|差异在哪|比较一下|对比一下)$"
)
_TRAILING_PUNCTUATION = "，,。！？?、；：:~～ \t\r\n"


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
class QueryAnalysis:
    """Structured query understanding result matching the Agent design spec."""

    # ── user intent ──
    original_query: str = ""
    primary_task: str = ""  # TaskType 名 (FACT_QA / BROWSE_QUERY / ...)
    secondary_tasks: list[str] = field(default_factory=list)

    # ── entity & location extraction ──
    entities: list[str] = field(default_factory=list)  # 匹配到的项目名
    categories: list[str] = field(default_factory=list)  # 非遗类别
    provinces: list[str] = field(default_factory=list)  # 省份
    cities: list[str] = field(default_factory=list)  # 城市
    levels: list[str] = field(default_factory=list)  # 级别

    # ── retrieval ──
    rewritten_query: str = ""  # 清洗后的检索用 query
    item_count: int = 0  # 用户要求的数量
    expansion_terms: list[str] = field(default_factory=list)

    # ── scenario attributes ──
    scenario: str = ""  # 校园展示 / 社区活动 / 展馆讲解 / 文创设计 / 研学活动
    audience: str = ""  # 中小学生 / 大学生 / 社区居民 / 游客 / 设计师
    constraints: list[str] = field(default_factory=list)  # ["展示难度低", "适合短时间"]
    time_budget: str = ""  # "30分钟" / "半天"
    tone: str = ""  # 正式 / 年轻化 / 展板风 / 讲解风

    # ── output preference ──
    output_format: str = ""  # 列表 / 表格 / 方案文档 / 文案

    # ── content transform ──
    transform_type: str = ""  # 翻译 / 年轻化 / 讲解词 / 文创文案

    # ── backward-compat (used by agent.py) ──
    metadata_filters: dict[str, str] = field(default_factory=dict)
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
        self.kb = kb
        self._category_names = [c.name for c in kb.categories]

    def analyze(
        self, query: str, task_type: TaskType | None = None, context: dict | None = None,
        planner_queries: list[str] | None = None,
    ) -> QueryAnalysis:
        # ── task identity supplied by the model planner ──
        primary_task = task_type.name if task_type else TaskType.FACT_QA.name

        # ── entity & location extraction ──
        # Use planner's search queries if available (LLM-driven, no regex)
        if planner_queries:
            entities = list(planner_queries)
            rewritten = " ".join(planner_queries)
        else:
            entities = self._extract_entities(query)
            # Boost with context item titles when query has no entities
            if not entities and context and isinstance(context, dict):
                context_items = context.get("items") or []
                if isinstance(context_items, list):
                    for item in context_items:
                        if not isinstance(item, dict):
                            continue
                        title = str(item.get("title") or "").strip()
                        if title and title not in entities:
                            entities.append(title)
                            break
            rewritten = self._rewrite_query(query, task_type)
        categories = self._extract_categories(query)
        provinces = self._extract_provinces(query)
        cities = self._extract_cities(query)
        levels = self._extract_levels(query)

        # ── scenario attributes ──
        scenario = self._extract_scenario_str(query)
        audience = self._extract_audience_str(query)
        constraints = self._extract_constraints(query)
        time_budget = self._extract_time_budget(query)
        tone = self._extract_tone(query)

        # ── output ──
        output_format = self._extract_output_format(query)
        transform_type = self._extract_transform_type(query)

        # ── count ──
        count = self._extract_count(query)
        item_count = count
        retrieval_count = count if count else self._default_retrieval_count(task_type)

        # ── query rewrite ──
        rewritten = self._rewrite_query(query, task_type)

        # ── expansion ──
        expansion = self._build_expansions_for_analysis(provinces, rewritten)

        # ── backward-compat metadata_filters & soft_constraints ──
        metadata_filters: dict[str, str] = {}
        if provinces:
            metadata_filters["province"] = provinces[0]
        if categories:
            metadata_filters["category"] = categories[0]
        if levels:
            metadata_filters["level"] = levels[0]

        soft_constraints: dict[str, str] = {}
        if audience:
            soft_constraints["audience"] = audience
        if scenario:
            soft_constraints["scenario"] = scenario

        # ── expansion ──
        expansion = self._build_expansions_for_analysis(provinces, rewritten)

        return QueryAnalysis(
            original_query=query,
            primary_task=primary_task,
            entities=entities,
            categories=categories,
            provinces=provinces,
            cities=cities,
            levels=levels,
            rewritten_query=rewritten,
            item_count=item_count,
            expansion_terms=expansion,
            scenario=scenario,
            audience=audience,
            constraints=constraints,
            time_budget=time_budget,
            tone=tone,
            output_format=output_format,
            transform_type=transform_type,
            metadata_filters=metadata_filters,
            soft_constraints=soft_constraints,
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
        if not match:
            return 0
        raw = match.group(1)
        if raw.isdigit():
            return int(raw)
        return _CN_NUM_MAP.get(raw, 0)

    def _extract_comparison_entities(self, original: str) -> list[str]:
        cleaned = original.strip()
        # Strip leading noise words (may be stacked: "对比一下")
        while True:
            new_cleaned = re.sub(r"^(比较|对比|一下下|一下|帮我|来看看|请问)\s*", "", cleaned)
            if new_cleaned == cleaned:
                break
            cleaned = new_cleaned
        cleaned = _COMPARISON_SPLIT_PATTERN.sub(" | ", cleaned)
        cleaned = _COUNT_PATTERN.sub("", cleaned)
        cleaned = re.sub(
            r"推荐|适合|哪些|帮我找|有哪些|列出|筛选|过滤|哪个更",
            "",
            cleaned,
        )
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        # Split on both "|" and "、"
        raw_parts = []
        for chunk in cleaned.split("|"):
            for sub in chunk.split("、"):
                raw_parts.append(sub.strip())
        parts = [p for p in raw_parts if p]
        names = []
        for part in parts:
            candidate = part.strip(_TRAILING_PUNCTUATION)
            candidate = _COMPARISON_TRAILING_PATTERN.sub("", candidate).strip(_TRAILING_PUNCTUATION)
            # Also strip common trailing noise patterns not caught by the regex
            candidate = re.sub(r"(的风格?差异|有何异同|的异同|有什么不同)\s*$", "", candidate)
            candidate = candidate.strip(_TRAILING_PUNCTUATION)
            if candidate and len(candidate) >= 2:
                names.append(candidate)
        return names or parts

    # ── extraction methods ──

    def _extract_entities(self, query: str) -> list[str]:
        """Link query substrings to HeritageItem titles and families."""
        if not query:
            return []
        title_matches: list[str] = []
        base_matches: list[str] = []
        family_matches: list[str] = []
        for item in self.kb.items:
            title = item.title
            if title in query:
                title_matches.append(title)
                continue
            # Try base title without parenthetical annotation
            base_title = title.split("（")[0].split("(")[0].strip()
            if len(base_title) >= 2 and base_title in query:
                base_matches.append(base_title)
                continue
            if len(item.family) >= 2 and item.family in query:
                family_matches.append(item.family)
        return list(dict.fromkeys(title_matches + base_matches + family_matches))

    def _extract_categories(self, query: str) -> list[str]:
        """Extract all matching ICH categories from query."""
        if not query:
            return []
        match = re.search(
            r"(传统戏剧|传统音乐|传统美术|传统舞蹈|传统医药|民俗|传统技艺|曲艺|传统体育|民间文学)",
            query,
        )
        if match:
            name = match.group(1)
            if name == "传统体育":
                return ["传统体育、游艺与杂技"]
            return [name]
        result: list[str] = []
        for name in self._category_names:
            if name in query:
                result.append(name)
        return result

    def _extract_provinces(self, query: str) -> list[str]:
        """Extract all matching provinces from query (full names + short names)."""
        if not query:
            return []
        matches = _PROVINCE_PATTERN.findall(query)
        result = list(dict.fromkeys(matches))
        for short, full in _SHORT_PROVINCE_MAP.items():
            if short in query and full not in result:
                result.append(full)
        return result

    def _extract_cities(self, query: str) -> list[str]:
        """Extract city names from query using StructuredMeta and regex."""
        if not query:
            return []
        found: list[str] = []
        # Regex-based city matching
        for m in _CITY_PATTERN.finditer(query):
            found.append(m.group(1))
        # Also check against known cities from extraction cache
        known: set[str] = set()
        for item in self.kb.items:
            if item.city:
                known.add(item.city)
        for city in sorted(known, key=len, reverse=True):
            if city not in found and city in query:
                found.append(city)
        return found

    def _extract_scenario_str(self, query: str) -> str:
        """Extract scenario as a single canonical value."""
        for kw, canonical in _SCENARIO_MAP.items():
            if kw in query:
                return canonical
        return ""

    def _extract_audience_str(self, query: str) -> str:
        """Extract audience as a single canonical value."""
        for kw, canonical in _AUDIENCE_MAP.items():
            if kw in query:
                return canonical
        return ""

    def _extract_constraints(self, query: str) -> list[str]:
        """Extract display/activity constraints from query."""
        found: list[str] = []
        for kw, canonical in _CONSTRAINT_KEYWORDS.items():
            if kw in query and canonical not in found:
                found.append(canonical)
        return found

    def _extract_time_budget(self, query: str) -> str:
        """Extract time budget from query."""
        m = _TIME_BUDGET_PATTERN.search(query)
        return m.group(0) if m else ""

    def _extract_tone(self, query: str) -> str:
        """Extract desired tone from query."""
        for kw, canonical in _TONE_KEYWORDS.items():
            if kw in query:
                return canonical
        return ""

    def _extract_output_format(self, query: str) -> str:
        """Extract desired output format from query."""
        for kw, canonical in _OUTPUT_FORMAT_KEYWORDS.items():
            if kw in query:
                return canonical
        return ""

    def _extract_transform_type(self, query: str) -> str:
        """Extract content transform type from query."""
        for kw, canonical in _TRANSFORM_TYPE_KEYWORDS.items():
            if kw in query:
                return canonical
        return ""

    def _build_expansions_for_analysis(
        self, provinces: list[str], rewritten: str
    ) -> list[str]:
        """Build expansion terms from province list and rewritten query."""
        terms: list[str] = []
        for entity in provinces:
            short = (
                entity.rstrip("省市自治区")
                .replace("壮族", "")
                .replace("回族", "")
                .replace("维吾尔", "")
            )
            if len(short) >= 2 and short != entity:
                terms.append(short)
        expanded_query = " ".join([rewritten, *terms])
        from .search import tokenize

        return tokenize(expanded_query)

    @staticmethod
    def _default_retrieval_count(task_type: TaskType | None) -> int:
        if task_type is None:
            return 5
        limits: dict[TaskType, int] = {
            TaskType.FACT_QA: 5,
            TaskType.COMPARISON: 8,
            TaskType.RECOMMENDATION: 10,
            TaskType.EXHIBITION_PLAN: 5,
            TaskType.STUDY_TASK: 5,
            TaskType.CONTENT_TRANSFORM: 5,
            TaskType.BROWSE_QUERY: 30,
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
            r"推荐|适合|哪些|帮我找|比较|对比|有哪些|列出|筛选|过滤|限定|只看|只要|生成讲解词|生成讲解稿|生成口播稿|生成文案|生成词|讲解词|讲解稿|口播稿|解说词|生成|给",
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
