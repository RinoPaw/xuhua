"""Intent router and task dispatcher for the heritage RAG agent."""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Any

from .dataset import KnowledgeBase


class TaskType(enum.Enum):
    FACTUAL_QA = "factual_qa"
    COMPARISON = "comparison"
    RECOMMENDATION = "recommendation"
    EXHIBITION_PLAN = "exhibition_plan"
    CURRICULUM_DESIGN = "curriculum_design"
    CREATIVE_BRIEF = "creative_brief"
    DATA_EXPLORE = "data_explore"
    MULTI_FILTER = "multi_filter"


_INTENT_RULES: list[tuple[re.Pattern[str], TaskType]] = [
    (
        re.compile(
            r"比较|对比|区别|差异|异同|有什么(?:不同|一样)|哪个更|vs\.?\s",
        ),
        TaskType.COMPARISON,
    ),
    (
        re.compile(
            r"推荐|适合|哪些.*适合|帮我找|找.*适合|推荐几个|推介|推选",
        ),
        TaskType.RECOMMENDATION,
    ),
    (
        re.compile(
            r"展览|展板|展陈|展示方案|策划展|布展|办展|办一个.*展|非遗展",
        ),
        TaskType.EXHIBITION_PLAN,
    ),
    (
        re.compile(
            r"教案|课程|研学|教学|上课|课件|教学设计|备课|讲授|上一堂|上一节",
        ),
        TaskType.CURRICULUM_DESIGN,
    ),
    (
        re.compile(
            r"文创|设计.*产品|纹样|包装|配色|主题.*设计|创意产品"
            r"|文化创意|周边产品|联名|IP",
        ),
        TaskType.CREATIVE_BRIEF,
    ),
    (
        re.compile(
            r"有哪些|列出|多少|哪些.*省|哪些.*市|几个.*项目"
            r"|统计|一共|总共|汇总|搜集",
        ),
        TaskType.DATA_EXPLORE,
    ),
    (
        re.compile(
            r"筛选|过滤|找.*省的|找.*级的|按.*筛选|只看|只要|限定",
        ),
        TaskType.MULTI_FILTER,
    ),
]


class IntentRouter:
    """Classify user input into a task type.

    Uses regex keyword rules first (fast, zero-cost).  LLM-based
    classification is deferred to a future opt-in path.
    """

    def classify(self, query: str) -> tuple[TaskType, float]:
        for pattern, task_type in _INTENT_RULES:
            if pattern.search(query):
                return task_type, 0.85
        return TaskType.FACTUAL_QA, 0.5


@dataclass(frozen=True)
class TaskConfig:
    task_type: TaskType
    retrieval_limit: int = 5
    require_diversity: bool = False
    context_schema: str = "fact_sheet"


_TASK_CONFIGS: dict[TaskType, TaskConfig] = {
    TaskType.FACTUAL_QA: TaskConfig(
        task_type=TaskType.FACTUAL_QA,
        retrieval_limit=5,
        context_schema="fact_sheet",
    ),
    TaskType.COMPARISON: TaskConfig(
        task_type=TaskType.COMPARISON,
        retrieval_limit=8,
        require_diversity=True,
        context_schema="comparison_table",
    ),
    TaskType.RECOMMENDATION: TaskConfig(
        task_type=TaskType.RECOMMENDATION,
        retrieval_limit=10,
        require_diversity=True,
        context_schema="recommendation_cards",
    ),
    TaskType.EXHIBITION_PLAN: TaskConfig(
        task_type=TaskType.EXHIBITION_PLAN,
        retrieval_limit=5,
        context_schema="exhibition_brief",
    ),
    TaskType.CURRICULUM_DESIGN: TaskConfig(
        task_type=TaskType.CURRICULUM_DESIGN,
        retrieval_limit=5,
        context_schema="curriculum_brief",
    ),
    TaskType.CREATIVE_BRIEF: TaskConfig(
        task_type=TaskType.CREATIVE_BRIEF,
        retrieval_limit=5,
        context_schema="creative_brief",
    ),
    TaskType.DATA_EXPLORE: TaskConfig(
        task_type=TaskType.DATA_EXPLORE,
        retrieval_limit=20,
        context_schema="fact_sheet",
    ),
    TaskType.MULTI_FILTER: TaskConfig(
        task_type=TaskType.MULTI_FILTER,
        retrieval_limit=30,
        context_schema="fact_sheet",
    ),
}


@dataclass
class TaskResult:
    task_type: TaskType
    answer: str
    raw_answer: str = ""
    speech: str = ""
    sources: list[dict[str, Any]] = field(default_factory=list)
    confidence: str = "medium"
    mode: str = "local"


class Agent:
    """Top-level agent that routes a user query through intent classification,
    query analysis, retrieval, and generation.

    For MVP-2 the retrieval and generation stages still delegate to the
    existing ``search_items`` / ``answer_question`` pipeline.
    """

    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb
        self.router = IntentRouter()

    def dispatch(self, query: str, category: str = "") -> TaskResult:
        query = query.strip()
        if not query:
            return TaskResult(
                task_type=TaskType.FACTUAL_QA,
                answer="请先输入问题。",
                speech="请先输入问题。",
                mode="empty",
            )

        task_type, _confidence = self.router.classify(query)

        from .retriever import QueryAnalyzer

        analyzer = QueryAnalyzer(self.kb)
        plan = analyzer.analyze(query, task_type)

        from .ai import Answer, answer_question

        answer: Answer = answer_question(
            self.kb,
            question=plan.rewritten_query or query,
            category=plan.metadata_filters.get("category", category),
        )

        return TaskResult(
            task_type=task_type,
            answer=answer.answer,
            raw_answer=answer.answer,
            speech=answer.speech,
            sources=answer.sources,
            confidence="high" if _confidence > 0.7 else "medium",
            mode=answer.mode,
        )


def task_type_label(task_type: TaskType) -> str:
    labels: dict[TaskType, str] = {
        TaskType.FACTUAL_QA: "事实问答",
        TaskType.COMPARISON: "项目对比",
        TaskType.RECOMMENDATION: "项目推荐",
        TaskType.EXHIBITION_PLAN: "展览策划",
        TaskType.CURRICULUM_DESIGN: "研学教案",
        TaskType.CREATIVE_BRIEF: "文创方向",
        TaskType.DATA_EXPLORE: "数据探索",
        TaskType.MULTI_FILTER: "多维筛选",
    }
    return labels.get(task_type, task_type.value)


def task_type_from_str(value: str) -> TaskType:
    try:
        return TaskType(value)
    except ValueError:
        return TaskType.FACTUAL_QA
