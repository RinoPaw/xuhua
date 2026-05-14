"""Task execution settings for the heritage agent."""

from __future__ import annotations

from .agent_models import TaskConfig, TaskType


TASK_CONFIGS: dict[TaskType, TaskConfig] = {
    TaskType.CHITCHAT: TaskConfig(
        task_type=TaskType.CHITCHAT,
        retrieval_limit=0,
        context_schema="none",
        generate_detail="正在整理上下文，生成简短回应",
    ),
    TaskType.FACT_QA: TaskConfig(
        task_type=TaskType.FACT_QA,
        retrieval_limit=5,
        context_schema="fact_sheet",
        generate_detail="正在组织证据并生成依据式回答",
    ),
    TaskType.BROWSE_QUERY: TaskConfig(
        task_type=TaskType.BROWSE_QUERY,
        retrieval_limit=30,
        context_schema="fact_sheet",
        handler_name="_handle_browse",
        generate_detail="正在汇总条目，整理成可浏览清单",
    ),
    TaskType.COMPARISON: TaskConfig(
        task_type=TaskType.COMPARISON,
        retrieval_limit=8,
        require_diversity=True,
        context_schema="comparison_table",
        handler_name="_handle_comparison",
        generate_detail="正在提取差异点并生成对比表格",
    ),
    TaskType.RECOMMENDATION: TaskConfig(
        task_type=TaskType.RECOMMENDATION,
        retrieval_limit=10,
        require_diversity=True,
        context_schema="recommendation_cards",
        handler_name="_handle_recommend",
        generate_detail="正在按场景筛选、排序并写推荐理由",
    ),
    TaskType.EXHIBITION_PLAN: TaskConfig(
        task_type=TaskType.EXHIBITION_PLAN,
        retrieval_limit=5,
        context_schema="exhibition_brief",
        handler_name="_handle_exhibition",
        generate_detail="正在选取合适项目并编排展示流程",
    ),
    TaskType.STUDY_TASK: TaskConfig(
        task_type=TaskType.STUDY_TASK,
        retrieval_limit=5,
        context_schema="curriculum_brief",
        handler_name="_handle_study_task",
        generate_detail="正在把项目资料转成课堂任务",
    ),
    TaskType.CONTENT_TRANSFORM: TaskConfig(
        task_type=TaskType.CONTENT_TRANSFORM,
        retrieval_limit=5,
        context_schema="creative_brief",
        handler_name="_handle_content_transform",
        generate_detail="正在围绕目标项目改写成指定文体",
    ),
}

# Backward-compatible name used by existing tests/imports.
_TASK_CONFIGS = TASK_CONFIGS
