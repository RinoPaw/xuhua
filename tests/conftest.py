import pytest

from heritage_explorer import config
from heritage_explorer.agent_models import AgentDecision, TaskType


@pytest.fixture(autouse=True)
def disable_embedding_search(monkeypatch):
    monkeypatch.setattr(config, "SEARCH_USE_EMBEDDING", False)


@pytest.fixture(autouse=True)
def fake_agent_planner(monkeypatch):
    """Keep tests deterministic while production planning is model-only."""

    def fake_planner(query: str, _kb, _category: str = "", _context: dict | None = None) -> AgentDecision:
        # Simulate context-based entity resolution (what the real LLM planner does)
        if _context and isinstance(_context, dict):
            items = _context.get("items") or []
            if items and isinstance(items, list):
                titles = [item.get("title", "") for item in items if isinstance(item, dict) and item.get("title")]
                if titles and not any(t in query for t in titles):
                    query = f"{titles[0]} {query}"

        if not query:
            task_type = TaskType.FACT_QA
        elif any(term in query for term in ("你好", "你是谁", "你叫什么", "你知道什么", "你能做什么", "资料库里有什么")):
            direct_answer = "我是叙华，一个面向河南非遗资料库的问答助手。我可以回答项目资料，也能筛选、对比和推荐非遗项目。"
            if "你好" in query:
                direct_answer = "你好，我在这里。你可以继续问我非遗项目、资料筛选或展示策划相关的问题。"
            return AgentDecision(
                task_type=TaskType.CHITCHAT,
                confidence=0.95,
                needs_retrieval=False,
                needs_llm=False,
                reason="测试 planner 判断为直接回应。",
                direct_answer=direct_answer,
                mode="local",
                planner="test",
            )
        elif "天气" in query:
            return AgentDecision(
                task_type=TaskType.FACT_QA,
                confidence=0.9,
                needs_retrieval=False,
                needs_llm=False,
                reason="测试 planner 判断为能力边界回应。",
                direct_answer="这个问题看起来不属于当前非遗资料库的范围。我更适合回答非遗项目资料。",
                mode="no_context",
                warnings=["测试 planner 判断问题不需要资料库或生成模型处理。"],
                planner="test",
            )
        elif any(term in query for term in ("比较", "对比", "区别", "差异", " vs ", "VS")):
            task_type = TaskType.COMPARISON
        elif any(term in query for term in ("推荐", "适合", "帮我找", "帮我挑", "帮我选")):
            task_type = TaskType.RECOMMENDATION
        elif any(term in query for term in ("教案", "课程", "研学", "学习任务", "教学活动")):
            task_type = TaskType.STUDY_TASK
        elif any(term in query for term in ("讲解词", "讲解稿", "口播稿", "解说词", "年轻化", "改写", "翻译", "双语", "文创", "纹样", "包装", "IP")):
            task_type = TaskType.CONTENT_TRANSFORM
        elif any(term in query for term in ("策划", "展览", "展板", "展陈", "展示方案", "校园展", "社区活动")):
            task_type = TaskType.EXHIBITION_PLAN
        elif any(term in query for term in ("列出", "有哪些", "多少", "筛选", "只看", "只要", "限定", "一共")):
            task_type = TaskType.BROWSE_QUERY
        else:
            task_type = TaskType.FACT_QA

        return AgentDecision(
            task_type=task_type,
            confidence=0.85,
            needs_retrieval=True,
            needs_llm=task_type in {TaskType.FACT_QA, TaskType.CONTENT_TRANSFORM},
            reason="测试 planner 已选择下一步行动。",
            planner="test",
        )

    monkeypatch.setattr("heritage_explorer.agent.call_agent_planner_model", fake_planner)
