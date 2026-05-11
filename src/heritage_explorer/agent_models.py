"""Shared contracts for the heritage task agent.

Keep these light-weight data structures separate from orchestration so search,
web, and task modules can depend on the same vocabulary without importing the
large dispatcher module.
"""

from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Any


class TaskType(enum.Enum):
    CHITCHAT = "chitchat"
    FACT_QA = "fact_qa"
    BROWSE_QUERY = "browse_query"
    COMPARISON = "comparison"
    RECOMMENDATION = "recommendation"
    EXHIBITION_PLAN = "exhibition_plan"
    STUDY_TASK = "study_task"
    CONTENT_TRANSFORM = "content_transform"

    # backward-compat enum names
    FACTUAL_QA = FACT_QA
    CURRICULUM_DESIGN = STUDY_TASK
    CREATIVE_BRIEF = CONTENT_TRANSFORM
    DATA_EXPLORE = BROWSE_QUERY
    MULTI_FILTER = BROWSE_QUERY


@dataclass(frozen=True)
class AgentDecision:
    """A small, explicit plan for what the agent should do next."""

    task_type: TaskType
    confidence: float
    needs_retrieval: bool
    needs_llm: bool
    reason: str
    direct_answer: str = ""
    mode: str = "local"
    warnings: list[str] = field(default_factory=list)
    planner: str = "offline"

    def to_payload(self) -> dict[str, Any]:
        return {
            "task_type": self.task_type.value,
            "confidence": self.confidence,
            "needs_retrieval": self.needs_retrieval,
            "needs_llm": self.needs_llm,
            "reason": self.reason,
            "mode": self.mode,
            "warnings": list(self.warnings),
            "planner": self.planner,
        }


@dataclass(frozen=True)
class TaskConfig:
    task_type: TaskType
    retrieval_limit: int = 5
    require_diversity: bool = False
    context_schema: str = "fact_sheet"
    handler_name: str | None = None
    generate_detail: str = "正在请模型生成最终文字"


@dataclass
class AgentResult:
    task_type: TaskType
    answer: str = ""
    items: list[dict[str, Any]] = field(default_factory=list)
    sources: list[dict[str, Any]] = field(default_factory=list)
    evidence: list[dict[str, Any]] = field(default_factory=list)
    selection_reason: str = ""
    mode: str = "local"
    confidence: float = 0.0
    warnings: list[str] = field(default_factory=list)
    total_count: int = 0
    decision: dict[str, Any] = field(default_factory=dict)
    # backward-compat
    speech: str = ""


# backward-compat alias
TaskResult = AgentResult


_TASK_TYPE_LABELS = {
    TaskType.CHITCHAT: "对话回应",
    TaskType.FACT_QA: "事实问答",
    TaskType.BROWSE_QUERY: "资料筛选",
    TaskType.COMPARISON: "项目对比",
    TaskType.RECOMMENDATION: "项目推荐",
    TaskType.EXHIBITION_PLAN: "展示策划",
    TaskType.STUDY_TASK: "研学任务",
    TaskType.CONTENT_TRANSFORM: "内容转化",
}


def task_type_label(task_type: TaskType) -> str:
    return _TASK_TYPE_LABELS.get(task_type, "事实问答")


def task_type_from_str(value: str) -> TaskType:
    try:
        return TaskType(value)
    except ValueError:
        return TaskType.FACT_QA
