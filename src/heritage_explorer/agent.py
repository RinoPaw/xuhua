"""Intent router and task dispatcher for the heritage RAG agent."""

from __future__ import annotations

import enum
import json
import logging
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field, replace
from typing import Any

from . import config
from .dataset import KnowledgeBase, get_soft_labels, get_structured_meta, item_to_dict, normalize_text

LOGGER = logging.getLogger(__name__)


class TaskType(enum.Enum):
    CHITCHAT = "chitchat"
    FACT_QA = "fact_qa"
    BROWSE_QUERY = "browse_query"
    COMPARISON = "comparison"
    RECOMMENDATION = "recommendation"
    EXHIBITION_PLAN = "exhibition_plan"
    STUDY_TASK = "study_task"
    CONTENT_TRANSFORM = "content_transform"

    # backward-compat aliases
    FACTUAL_QA = FACT_QA
    CURRICULUM_DESIGN = STUDY_TASK
    CREATIVE_BRIEF = CONTENT_TRANSFORM
    DATA_EXPLORE = BROWSE_QUERY
    MULTI_FILTER = BROWSE_QUERY


_TRAILING_PARTICLES = "~？?！!。.，,、 \t\r\n"
_GREETING_TERMS = ("你好", "您好", "嗨", "哈喽", "hello", "hi", "在吗", "有人吗", "早上好", "下午好", "晚上好")
_THANKS_TERMS = ("谢谢", "感谢", "辛苦了")
_IDENTITY_TERMS = ("你是谁", "你叫什么", "你叫什么名字", "你的名字", "你是什么", "介绍你自己", "介绍一下你自己", "自我介绍")
_CAPABILITY_TERMS = (
    "你能做什么",
    "你会做什么",
    "你可以做什么",
    "你有什么功能",
    "你能帮我做什么",
    "你知道什么",
    "你了解什么",
    "你掌握什么",
    "你懂什么",
    "你能回答什么",
    "你会哪些",
    "资料库里有什么",
    "你有什么资料",
    "这里有什么",
    "你支持什么",
)
_CHITCHAT_TERMS = _GREETING_TERMS + _THANKS_TERMS + _IDENTITY_TERMS + _CAPABILITY_TERMS
_INTERNAL_PLANNER_TERMS = (
    "控制器",
    "内部规划器",
    "后台规划器",
    "planner",
    "计划器",
    "规划器",
    "决策层",
    "路由",
    "json",
    "工具选择",
    "agentdecision",
    "retrieval_tool",
    "rule_handler",
    "llm_generation",
)
_DOMAIN_HINT_TERMS = (
    "非遗", "非物质文化遗产", "文化遗产", "传统", "民间", "民俗", "传承", "传说", "项目", "名录",
    "国家级", "省级", "市级", "县级", "技艺", "戏剧", "戏曲", "皮影", "木偶", "曲艺", "音乐",
    "舞蹈", "美术", "医药", "体育", "杂技", "文学", "刺绣", "汴绣", "烙画", "木版年画",
    "太极", "少林", "唢呐", "剪纸", "泥塑", "面塑", "灯会", "庙会", "香包", "历史",
    "特色", "特点", "代表作品", "价值", "保护", "展示", "展览", "研学", "课程", "文创",
)
_INTENT_KEYWORDS: list[tuple[tuple[str, ...], TaskType]] = [
    (("比较", "对比", "区别", "差异", "异同", "哪个更", "哪个好", " vs ", "VS"), TaskType.COMPARISON),
    (("推荐", "适合", "帮我找", "帮我挑", "帮我选", "推介"), TaskType.RECOMMENDATION),
    (("策划", "展览", "展板", "展陈", "展示方案", "展示策划", "校园展", "展馆", "布展", "办展", "非遗展", "社区活动"), TaskType.EXHIBITION_PLAN),
    (("教案", "课程", "研学", "教学", "上课", "课件", "教学设计", "备课", "讲授", "上一堂", "上一节", "学习任务", "教学活动", "教案设计"), TaskType.STUDY_TASK),
    (("翻译", "英文", "双语", "年轻化", "朋友圈", "文创文案", "改写", "文创", "纹样", "包装", "配色", "创意产品", "文化创意", "周边产品", "联名", "IP"), TaskType.CONTENT_TRANSFORM),
    (("列举", "有哪些", "列出", "多少", "统计", "一共", "总共", "汇总", "搜集", "筛选", "过滤", "只看", "只要", "限定"), TaskType.BROWSE_QUERY),
]


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


class IntentRouter:
    """Classify user input into a task type.

    Uses regex keyword rules first (fast, zero-cost).  LLM-based
    classification is deferred to a future opt-in path.
    """

    def classify(self, query: str) -> tuple[TaskType, float]:
        if is_chitchat_query(query):
            return TaskType.CHITCHAT, 0.95
        for keywords, task_type in _INTENT_KEYWORDS:
            if contains_any(query, keywords):
                return task_type, 0.85
        return TaskType.FACT_QA, 0.5

    def decide(self, query: str, kb: KnowledgeBase, category: str = "") -> AgentDecision:
        """Plan the next action before retrieval/generation.

        This is the agentic boundary: the app decides whether it should talk,
        search, use a rule handler, call an LLM-backed path, or decline because
        the request is outside the heritage data domain.
        """
        if should_use_model_planner():
            try:
                return call_agent_planner_model(query, kb, category)
            except Exception as exc:  # noqa: BLE001 - planner must degrade gracefully.
                LOGGER.warning("Agent planner unavailable; using offline fallback: %s", exc)
                return self.decide_offline(query, kb, category)

        return self.decide_offline(query, kb, category)

    def decide_offline(self, query: str, kb: KnowledgeBase, category: str = "") -> AgentDecision:
        """Offline fallback for when no planner model is configured."""
        task_type, confidence = self.classify(query)

        if task_type is TaskType.CHITCHAT:
            return AgentDecision(
                task_type=task_type,
                confidence=confidence,
                needs_retrieval=False,
                needs_llm=False,
                reason="识别为身份、能力说明或寒暄类对话，直接回应。",
                direct_answer=build_chitchat_answer(query, kb),
            )

        if task_type is TaskType.FACT_QA and should_answer_out_of_scope(kb, query, category):
            return AgentDecision(
                task_type=task_type,
                confidence=0.9,
                needs_retrieval=False,
                needs_llm=False,
                reason="问题缺少非遗领域线索，且资料库检索没有命中，跳过模型生成。",
                direct_answer=build_out_of_scope_answer(),
                mode="no_context",
                warnings=["问题看起来不属于非遗资料库范围，已跳过模型生成。"],
            )

        pure_rule_tasks = {
            TaskType.BROWSE_QUERY,
            TaskType.COMPARISON,
            TaskType.RECOMMENDATION,
            TaskType.EXHIBITION_PLAN,
            TaskType.STUDY_TASK,
        }
        if task_type in pure_rule_tasks:
            return AgentDecision(
                task_type=task_type,
                confidence=confidence,
                needs_retrieval=True,
                needs_llm=False,
                reason=f"识别为「{task_type_label(task_type)}」任务，使用资料库检索和规则 handler 完成。",
            )

        if task_type is TaskType.CONTENT_TRANSFORM:
            return AgentDecision(
                task_type=task_type,
                confidence=confidence,
                needs_retrieval=True,
                needs_llm=True,
                reason="识别为内容转化任务，先匹配资料，再优先使用模型改写，失败时模板回退。",
            )

        return AgentDecision(
            task_type=TaskType.FACT_QA,
            confidence=confidence,
            needs_retrieval=True,
            needs_llm=True,
            reason="识别为非遗事实问答，先检索资料，再生成依据式回答。",
        )

    def plan(self, query: str, kb: KnowledgeBase, category: str = "") -> AgentDecision:
        """Alias for callers that want an explicit agent planning API."""
        return self.decide(query, kb, category)

    def needs_retrieval(self, query: str, kb: KnowledgeBase, category: str = "") -> bool:
        return self.decide(query, kb, category).needs_retrieval


@dataclass(frozen=True)
class TaskConfig:
    task_type: TaskType
    retrieval_limit: int = 5
    require_diversity: bool = False
    context_schema: str = "fact_sheet"
    handler_name: str | None = None
    generate_detail: str = "正在请模型生成最终文字"


_TASK_CONFIGS: dict[TaskType, TaskConfig] = {
    TaskType.CHITCHAT: TaskConfig(
        task_type=TaskType.CHITCHAT,
        retrieval_limit=0,
        context_schema="none",
        generate_detail="正在组织简短回应",
    ),
    TaskType.FACT_QA: TaskConfig(
        task_type=TaskType.FACT_QA,
        retrieval_limit=5,
        context_schema="fact_sheet",
        generate_detail="正在请模型生成最终文字",
    ),
    TaskType.BROWSE_QUERY: TaskConfig(
        task_type=TaskType.BROWSE_QUERY,
        retrieval_limit=30,
        context_schema="fact_sheet",
        handler_name="_handle_browse",
        generate_detail="正在整理资料生成回答",
    ),
    TaskType.COMPARISON: TaskConfig(
        task_type=TaskType.COMPARISON,
        retrieval_limit=8,
        require_diversity=True,
        context_schema="comparison_table",
        handler_name="_handle_comparison",
        generate_detail="正在提取条目信息并生成对比表格",
    ),
    TaskType.RECOMMENDATION: TaskConfig(
        task_type=TaskType.RECOMMENDATION,
        retrieval_limit=10,
        require_diversity=True,
        context_schema="recommendation_cards",
        handler_name="_handle_recommend",
        generate_detail="正在按场景匹配和评分排序",
    ),
    TaskType.EXHIBITION_PLAN: TaskConfig(
        task_type=TaskType.EXHIBITION_PLAN,
        retrieval_limit=5,
        context_schema="exhibition_brief",
        handler_name="_handle_exhibition",
        generate_detail="正在匹配项目并生成策展方案",
    ),
    TaskType.STUDY_TASK: TaskConfig(
        task_type=TaskType.STUDY_TASK,
        retrieval_limit=5,
        context_schema="curriculum_brief",
        handler_name="_handle_study_task",
        generate_detail="正在匹配非遗项目并生成研学教案",
    ),
    TaskType.CONTENT_TRANSFORM: TaskConfig(
        task_type=TaskType.CONTENT_TRANSFORM,
        retrieval_limit=5,
        context_schema="creative_brief",
        handler_name="_handle_content_transform",
        generate_detail="正在匹配非遗项目并生成内容改稿",
    ),
}


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


class Agent:
    """Top-level agent: intent classification → query analysis → dispatch.

    MVP dispatches 3 TaskTypes with dedicated pipelines:
      - BROWSE_QUERY    → structured filters + local listing (no LLM)
      - RECOMMENDATION  → SoftLabels matching + rule scoring
      - EXHIBITION_PLAN → recommendation sub-pipeline + template
    All other types fall through to the existing answer_question flow.
    """

    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb
        self.router = IntentRouter()

    # ── dispatch ──────────────────────────────────────────────────────

    def dispatch(self, query: str, category: str = "", include_speech: bool = True) -> AgentResult:
        """Backward-compat wrapper: consume stream and return final result."""
        result = None
        for event in self.dispatch_stream(query, category, include_speech=include_speech):
            if isinstance(event, AgentResult):
                result = event
        return result

    def dispatch_stream(self, query: str, category: str = "", include_speech: bool = True):
        """Generator: yields progress dicts, then AgentResult."""
        from .retriever import QueryAnalyzer

        query = query.strip()
        if not query:
            yield AgentResult(
                task_type=TaskType.FACT_QA,
                answer="请先输入问题。",
                speech="请先输入问题。" if include_speech else "",
                mode="empty",
            )
            return

        # Step 1: classify + analyze
        yield self._progress_event("classify", "理解问题", "正在分析问题意图与资料条件")
        decision = self.router.decide(query, self.kb, category)
        task_type = decision.task_type
        yield self._progress_event("classify", "规划任务", decision.reason)
        if decision.direct_answer:
            yield from self._stream_direct_answer(decision, include_speech)
            return

        analyzer = QueryAnalyzer(self.kb)
        analysis = analyzer.analyze(query, task_type)

        # Step 2: search
        yield self._progress_event("search", "检索资料", "正在从非遗数据库中查找匹配条目")

        task_config = _TASK_CONFIGS.get(task_type, _TASK_CONFIGS[TaskType.FACT_QA])
        yield self._progress_event("generate", "生成回答", task_config.generate_detail)
        if task_config.handler_name:
            result = self._run_configured_handler(task_config, analysis)
        else:
            result = self._build_fact_result(analysis, query, category, decision)
        yield from self._stream_completed_result(result, decision, include_speech)

    def _progress_event(self, step: str, title: str, detail: str) -> dict[str, str]:
        return {
            "type": "progress",
            "step": step,
            "title": title,
            "detail": detail,
        }

    def _stream_direct_answer(self, decision: AgentDecision, include_speech: bool):
        response_title = "智能体回应" if decision.planner == "model" else "直接回应"
        yield self._progress_event("search", "直接回应", "智能体决策为直接回应，已跳过资料库检索。")
        yield self._progress_event("generate", response_title, _TASK_CONFIGS[TaskType.CHITCHAT].generate_detail)
        result = AgentResult(
            task_type=decision.task_type,
            answer=decision.direct_answer,
            speech=decision.direct_answer,
            mode=decision.mode,
            confidence=decision.confidence,
            warnings=list(decision.warnings),
        )
        yield from self._stream_completed_result(result, decision, include_speech)

    def _run_configured_handler(self, task_config: TaskConfig, analysis) -> AgentResult:
        if not task_config.handler_name:
            raise ValueError(f"Task config for {task_config.task_type.value} does not declare a handler.")
        handler = getattr(self, task_config.handler_name)
        return handler(analysis)

    def _build_fact_result(self, analysis, query: str, category: str, decision: AgentDecision) -> AgentResult:
        from .ai import Answer, answer_question

        answer_query = normalize_query_with_pinyin_anchor(
            self.kb,
            analysis.rewritten_query or query,
            analysis.metadata_filters.get("category", category),
        )
        answer: Answer = answer_question(
            self.kb,
            question=answer_query,
            category=analysis.metadata_filters.get("category", category),
        )
        return AgentResult(
            task_type=decision.task_type,
            answer=answer.answer,
            speech=answer.speech,
            sources=answer.sources,
            confidence=0.85 if decision.confidence > 0.7 else 0.5,
            mode=answer.mode,
        )

    def _stream_completed_result(
        self,
        result: AgentResult,
        decision: AgentDecision,
        include_speech: bool,
    ):
        if include_speech and result.speech:
            yield self._progress_event("speech", "润色播报", "正在准备更适合朗读的版本")
        yield with_agent_decision(result, decision, include_speech)

    # ── MVP handlers ───────────────────────────────────────────────────

    def _handle_comparison(self, analysis) -> AgentResult:
        """COMPARISON: multi-entity structured comparison, no LLM."""
        from .search import search_items_lexical

        # Resolve target entities — try explicit entities first, fall back to splitting
        _ENTITY_SUFFIX_RE = re.compile(
            r"(?:有什么区别|有什么不同|的区别|的差异|哪个更受欢迎|哪个更|哪个好|的比较|的对比|对比一下)$"
        )
        targets: list[str] = []
        if analysis.entities:
            targets = [_ENTITY_SUFFIX_RE.sub("", e) for e in analysis.entities]
        else:
            # Fallback: split rewritten query on common separators
            parts = re.split(r"\s+", analysis.rewritten_query)
            targets = [_ENTITY_SUFFIX_RE.sub("", p) for p in parts if len(p) >= 2]

        if len(targets) < 2:
            # Not enough entities to compare — fall through to LLM
            from .ai import Answer, answer_question

            answer: Answer = answer_question(
                self.kb,
                question=analysis.rewritten_query or analysis.original_query,
            )
            return AgentResult(
                task_type=TaskType.COMPARISON,
                answer=answer.answer,
                speech=answer.speech,
                sources=answer.sources,
                mode=answer.mode,
                confidence=0.7,
            )

        # Search each target entity in the KB
        resolved: list[tuple[str, Any, Any, Any]] = []  # (entity_name, item, meta, labels)
        unmatched: list[str] = []

        for t in targets:
            result, _ = search_items_lexical(self.kb, query=t, limit=1)
            if result:
                item = result[0]
                meta = get_structured_meta(item.id)
                labels = get_soft_labels(item.id)
                resolved.append((t, item, meta, labels))
            else:
                unmatched.append(t)

        if len(resolved) < 2:
            # Insufficient matches — fall through to LLM
            from .ai import Answer, answer_question

            answer: Answer = answer_question(
                self.kb,
                question=analysis.rewritten_query or analysis.original_query,
            )
            return AgentResult(
                task_type=TaskType.COMPARISON,
                answer=answer.answer,
                speech=answer.speech,
                sources=answer.sources,
                mode=answer.mode,
                confidence=0.6,
                warnings=[f"仅匹配到 {len(resolved)} 个项目" + (f"，未找到：{'、'.join(unmatched)}" if unmatched else "")],
            )

        # Build comparison answer
        lines: list[str] = []
        lines.append(f"## {' vs '.join(name for name, _, _, _ in resolved)} 对比\n")

        # ── Table header ──
        col_width = 18
        header = f"| {'维度':<{col_width - 4}}" + "".join(
            f" | {name[:col_width - 2]:<{col_width - 2}}" for name, _, _, _ in resolved
        ) + " |"
        sep = "|" + "-" * (col_width - 1) + "|" + "|".join("-" * (col_width - 1) for _ in resolved) + "|"
        lines.append(header)
        lines.append(sep)

        def _row(label: str, *values: str) -> str:
            return f"| {label:<{col_width - 4}}" + "".join(
                f" | {v[:col_width - 2]:<{col_width - 2}}" for v in values
            ) + " |"

        # Category row
        lines.append(_row("类别", *(item.category for _, item, _, _ in resolved)))

        # Level row
        lines.append(_row("级别", *(meta.level if meta else "—" for _, _, meta, _ in resolved)))

        # Province row
        lines.append(_row("省份", *(meta.province if meta else "—" for _, _, meta, _ in resolved)))

        # City row
        lines.append(_row("城市", *(meta.city if meta and meta.city else "—" for _, _, meta, _ in resolved)))

        # Display forms
        lines.append(_row(
            "展示形式",
            *("、".join(meta.display_forms) if meta and meta.display_forms else "—" for _, _, meta, _ in resolved),
        ))

        # Education value
        lines.append(_row(
            "教育价值",
            *(labels.education_value if labels else "—" for _, _, _, labels in resolved),
        ))

        # Interaction potential
        lines.append(_row(
            "互动潜力",
            *(labels.interaction_potential if labels else "—" for _, _, _, labels in resolved),
        ))

        # ── Narrative sections ──
        lines.append("")
        for entity_name, item, meta, labels in resolved:
            lines.append(f"### {entity_name}")
            if meta and meta.features:
                lines.append(f"**技艺特点：**{meta.features[:200]}")
            if meta and meta.history:
                lines.append(f"**历史背景：**{meta.history[:200]}")
            if meta and meta.cultural_value:
                lines.append(f"**文化价值：**{meta.cultural_value[:200]}")
            if not (meta and (meta.features or meta.history or meta.cultural_value)):
                lines.append(f"{item.summary[:300]}")
            lines.append("")

        # Comparison summary
        lines.append("### 对比小结")
        summary_parts: list[str] = []

        # Level comparison
        levels = [meta.level if meta else "" for _, _, meta, _ in resolved]
        unique_levels = list(dict.fromkeys(levels))
        if len(unique_levels) > 1:
            summary_parts.append(f"级别上，{'、'.join(f'{name}为{lv}' for (name, _, _, _), lv in zip(resolved, levels))}")
        else:
            summary_parts.append(f"两项均为{unique_levels[0]}非遗项目")

        # Category comparison
        cats = [item.category for _, item, _, _ in resolved]
        unique_cats = list(dict.fromkeys(cats))
        if len(unique_cats) > 1:
            summary_parts.append(f"分属{'和'.join(unique_cats)}不同类别")
        else:
            summary_parts.append(f"同属{unique_cats[0]}类别")

        # Education comparison
        if labels_data := [(name, labels) for name, _, _, labels in resolved if labels]:
            edu_values = [l.education_value for _, l in labels_data]
            if len(set(edu_values)) > 1:
                summary_parts.append("教育价值存在差异")
            else:
                summary_parts.append(f"教育价值均为{edu_values[0]}")

        lines.append("；".join(summary_parts) + "。")

        # Build evidence
        evidence: list[dict[str, Any]] = []
        for entity_name, item, _, _ in resolved:
            evidence.append({
                "type": "source",
                "claim": f"对比项：{entity_name}",
                "basis": f"lexical_search query={entity_name!r}",
                "item_id": item.id,
            })

        sources = [{"id": item.id, "title": item.title, "category": item.category}
                    for _, item, _, _ in resolved]
        items = [_enriched_item_card(item) for _, item, _, _ in resolved]

        warnings: list[str] = []
        if unmatched:
            warnings.append(f"未在资料库中找到：{'、'.join(unmatched)}")

        return AgentResult(
            task_type=TaskType.COMPARISON,
            answer="\n".join(lines),
            items=items,
            sources=sources,
            evidence=evidence,
            mode="local",
            confidence=0.85 if not unmatched else 0.6,
            warnings=warnings,
        )

    def _handle_study_task(self, analysis) -> AgentResult:
        """STUDY_TASK: curriculum/teaching plan generation, no LLM."""
        from .search import search_items_lexical

        target_item = None
        target_meta = None
        target_labels = None

        # Try to resolve a specific target entity
        if analysis.entities:
            entity = analysis.entities[0]
            result, _ = search_items_lexical(self.kb, query=entity, limit=1)
            if result:
                target_item = result[0]
                target_meta = get_structured_meta(target_item.id)
                target_labels = get_soft_labels(target_item.id)

        # If no specific entity found, fall back to recommendation
        if target_item is None:
            rec_result = self._handle_recommend(analysis)
            if rec_result.items:
                # Use the first recommended item
                target_item = self.kb.get(rec_result.items[0]["id"])
                if target_item:
                    target_meta = get_structured_meta(target_item.id)
                    target_labels = get_soft_labels(target_item.id)

        if target_item is None:
            # Nothing to work with — fall through to LLM
            from .ai import Answer, answer_question

            answer: Answer = answer_question(
                self.kb,
                question=analysis.rewritten_query or analysis.original_query,
            )
            return AgentResult(
                task_type=TaskType.STUDY_TASK,
                answer=answer.answer,
                speech=answer.speech,
                sources=answer.sources,
                mode=answer.mode,
                confidence=0.5,
                warnings=["未找到可用的非遗项目，已退回通用问答"],
            )

        audience = analysis.audience or "中小学生"
        time_budget = analysis.time_budget or "45分钟"
        scenario = analysis.scenario or "研学体验"

        # Audience-specific adaptations
        audience_label: str
        if audience in ("儿童", "小学生"):
            audience_label = "小学中高年级"
        elif audience in ("青少年", "中学生"):
            audience_label = "初中生"
        elif audience == "大学生":
            audience_label = "大学生"
        elif audience == "家庭":
            audience_label = "亲子家庭"
        else:
            audience_label = "中小学生"

        title = target_item.title
        category = target_item.category
        summary = target_item.summary[:200]

        features = target_meta.features[:200] if target_meta and target_meta.features else summary
        history = target_meta.history[:200] if target_meta and target_meta.history else ""
        display = "、".join(target_meta.display_forms) if target_meta and target_meta.display_forms else "展板 + 讲解"

        lines = [
            f"## 非遗研学教案：{title}",
            "",
            f"**适用对象：**{audience_label}",
            f"**课时安排：**{time_budget}",
            f"**所属类别：**{category}",
            f"**展示形式：**{display}",
            "",
            "### 一、教学目标",
            "",
            f"1. **知识目标：**了解{title}的历史渊源、技艺特点和代表性作品。",
            f"2. **能力目标：**通过观察、讨论和实践体验，培养学生对传统{category}项目的感知和分析能力。",
            f"3. **情感目标：**激发对非遗文化的兴趣和认同感，理解保护传承的意义。",
            "",
            "### 二、教学重点与难点",
            "",
            f"- **重点：**{title}的核心技艺特点和历史文化价值。",
            "- **难点：**引导学生理解非遗传承与当代生活的关联。",
            "",
            "### 三、教学准备",
            "",
            "- 多媒体课件（含项目图片或视频资料）",
            "- 实物展示或模型（如条件允许）",
            "- 学习任务单 / 观察记录表",
            "- 互动体验材料（根据项目特点准备）",
            "",
            "### 四、教学过程",
            "",
            "#### 环节一：情境导入（5分钟）",
            "",
            f"展示{title}的图片或短视频，提问：「你们见过这种技艺/艺术形式吗？它来自哪个地方？」",
            "引导学生分享已有认知，引出课题。",
            "",
            "#### 环节二：知识讲解（15分钟）",
            "",
        ]

        if history:
            lines.append(f"**历史背景：**{history}")
            lines.append("")
        lines.append(f"**技艺特点：**{features}")
        lines.append("")

        if target_meta and target_meta.cultural_value:
            lines.append(f"**文化价值：**{target_meta.cultural_value[:200]}")
            lines.append("")

        lines.extend([
            "#### 环节三：小组探究（15分钟）",
            "",
            "将学生分为 3-4 组，每组领取一个探究任务：",
            f"- **第1组：**研究{title}的历史发展脉络，画出时间轴。",
            f"- **第2组：**分析{title}的主要技艺特点，用思维导图整理。",
            f"- **第3组：**讨论{title}在当代社会的价值和面临的挑战。",
            "各组派代表汇报，教师点评补充。",
            "",
            "#### 环节四：实践体验（8分钟）",
            "",
            "根据项目特点选择以下一种或多种方式：",
            "- 动手模仿：让学生尝试简单的技艺操作步骤。",
            "- 创意设计：基于项目元素进行简单的文创设计。",
            "- 角色扮演：模拟传承人向观众介绍项目。",
            "",
            "#### 环节五：总结评价（2分钟）",
            "",
            "- 回顾本节课的核心知识点。",
            "- 请学生分享「今天印象最深的一个发现」。",
            "- 布置课后拓展任务（如：向家人介绍一项非遗）。",
            "",
            "### 五、评价方式",
            "",
            "- 课堂参与度：小组讨论和汇报表现。",
            "- 探究任务成果：时间轴 / 思维导图完成质量。",
            "- 实践体验：动手环节的投入程度。",
            "",
            "### 六、拓展建议",
            "",
            f"- 组织实地参观{title}传习所或传承人工作室。",
            f"- 与美术课、历史课、语文课进行跨学科联动。",
            "- 鼓励学生制作非遗主题手抄报或短视频介绍。",
            "",
            "---",
            "*本教案由 Xuhua AI 基于非遗数据自动生成，建议教师根据实际学情调整。*",
        ])

        sources = [{"id": target_item.id, "title": target_item.title, "category": target_item.category}]
        items = [_enriched_item_card(target_item)]
        evidence: list[dict[str, Any]] = [{
            "type": "source",
            "claim": "教案主体",
            "basis": f"entity={analysis.entities[0] if analysis.entities else '推荐'}",
            "item_id": target_item.id,
        }]

        return AgentResult(
            task_type=TaskType.STUDY_TASK,
            answer="\n".join(lines),
            items=items,
            sources=sources,
            evidence=evidence,
            mode="local",
            confidence=0.8,
            warnings=["教案为模板生成，建议教师根据实际学情调整教学环节和时间分配。"],
        )

    def _handle_content_transform(self, analysis) -> AgentResult:
        """CONTENT_TRANSFORM: translate / rewrite / creative brief."""
        from .search import search_items_lexical
        from .ai import Answer, answer_question

        # Resolve target entity
        target_item = None
        if analysis.entities:
            entity = analysis.entities[0]
            result, _ = search_items_lexical(self.kb, query=entity, limit=1)
            if result:
                target_item = result[0]

        if target_item is None:
            # No entity found — fall through
            answer: Answer = answer_question(
                self.kb,
                question=analysis.original_query,
            )
            return AgentResult(
                task_type=TaskType.CONTENT_TRANSFORM,
                answer=answer.answer,
                speech=answer.speech,
                sources=answer.sources,
                mode=answer.mode,
                confidence=0.5,
                warnings=["未识别到具体非遗项目，已退回通用问答"],
            )

        transform_type = analysis.transform_type

        # Determine transform type if not detected by QueryAnalyzer
        if not transform_type:
            q = analysis.original_query
            if re.search(r"翻译|英文|英语|双语|translate", q):
                transform_type = "翻译"
            elif re.search(r"年轻化|朋友圈|口语化|轻松", q):
                transform_type = "年轻化"
            elif re.search(r"文创|设计.*产品|纹样|包装|IP|联名|周边|创意", q):
                transform_type = "文创文案"
            else:
                transform_type = "改写"

        # Build context from the item
        meta = get_structured_meta(target_item.id)
        context_lines = [
            f"标题：{target_item.title}",
            f"类别：{target_item.category}",
        ]
        if meta:
            if meta.province:
                context_lines.append(f"省份：{meta.province}")
            if meta.city:
                context_lines.append(f"城市：{meta.city}")
            if meta.level:
                context_lines.append(f"级别：{meta.level}")
            if meta.features:
                context_lines.append(f"主要特色：{meta.features}")
            if meta.history:
                context_lines.append(f"历史背景：{meta.history}")
            if meta.cultural_value:
                context_lines.append(f"重要价值：{meta.cultural_value}")
        context_lines.append(f"简介：{target_item.summary}")
        context_lines.append(f"正文片段：{target_item.content[:800]}")
        context = "\n".join(context_lines)

        if config.AI_API_KEY:
            try:
                answer_text = self._call_transform_model(
                    transform_type=transform_type,
                    context=context,
                    query=analysis.original_query,
                )
                sources = [{"id": target_item.id, "title": target_item.title, "category": target_item.category}]
                from .ai import build_speech_text

                speech_text = build_speech_text(answer_text, question=analysis.original_query, sources=[target_item])

                return AgentResult(
                    task_type=TaskType.CONTENT_TRANSFORM,
                    answer=answer_text,
                    speech=speech_text,
                    sources=sources,
                    items=[_enriched_item_card(target_item)],
                    mode="llm",
                    confidence=0.8,
                )
            except Exception:
                pass  # fall through to local

        # Local fallback: template-based answer
        local_answer = _build_transform_local(transform_type, target_item, meta)
        return AgentResult(
            task_type=TaskType.CONTENT_TRANSFORM,
            answer=local_answer,
            items=[_enriched_item_card(target_item)],
            sources=[{"id": target_item.id, "title": target_item.title, "category": target_item.category}],
            mode="local",
            confidence=0.5,
            warnings=["模型接口不可用，已切回本地模板。如需更丰富的内容，请配置 API Key。"],
        )

    def _handle_browse(self, analysis) -> AgentResult:
        """BROWSE_QUERY: structured filters + local listing, no LLM."""
        from .search import search_items_lexical

        province = analysis.metadata_filters.get("province", "")
        level = analysis.metadata_filters.get("level", "")
        category = analysis.metadata_filters.get("category", "")

        limit = analysis.retrieval_count
        result, total = search_items_lexical(
            self.kb,
            query=analysis.rewritten_query,
            category=category,
            province=province,
            level=level,
            limit=limit,
        )

        items = [_enriched_item_card(item) for item in result]

        # Build structured answer
        filter_desc = _describe_filters(category, province, level)
        header = f"找到 {total} 项{filter_desc}非遗：\n" if total else f"未找到匹配的{filter_desc}非遗。"
        lines = [header]
        for i, item in enumerate(result, 1):
            meta = get_structured_meta(item.id)
            level_str = f" | {meta.level}" if meta else ""
            city_str = f" | {meta.city}" if meta and meta.city else ""
            lines.append(f"{i}. {item.title} — {item.category}{level_str}{city_str}")

        evidence: list[dict[str, Any]] = []
        for item in result:
            evidence.append({
                "type": "source",
                "claim": "筛选命中",
                "basis": f"province={province}, category={category}, level={level}",
                "item_id": item.id,
            })

        warnings: list[str] = []
        if not total:
            warnings.append(f"未找到{filter_desc}相关的非遗项目")
        elif total > limit:
            warnings.append(f"共匹配 {total} 项，当前仅展示前 {limit} 项。可通过筛选条件缩小范围或调整展示数量。")

        return AgentResult(
            task_type=TaskType.BROWSE_QUERY,
            answer="\n".join(lines),
            items=items,
            sources=[{"id": item.id, "title": item.title, "category": item.category} for item in result],
            evidence=evidence,
            mode="local",
            confidence=0.95,
            total_count=total,
            warnings=warnings,
        )

    def _handle_recommend(self, analysis) -> AgentResult:
        """RECOMMENDATION: SoftLabels matching + rule-based scoring."""
        scenario = analysis.scenario
        audience = analysis.audience
        constraints = analysis.constraints
        limit = analysis.retrieval_count

        scored: list[tuple[int, Any, Any, Any]] = []
        for item in self.kb.items:
            labels = get_soft_labels(item.id)
            meta = get_structured_meta(item.id)
            if labels is None or meta is None:
                continue
            # Scenario filter (soft — skip if scenario specified and not matched)
            if scenario and scenario not in labels.suitable_scenarios:
                continue
            # Audience filter (soft)
            if audience and audience not in labels.target_audience:
                continue
            score = _score_for_recommendation(meta, labels, constraints)
            scored.append((score, item, meta, labels))

        scored.sort(key=lambda x: -x[0])
        top = scored[:limit]

        # Build answer
        parts: list[str] = []
        scene_desc = scenario or "通用"
        parts.append(f"为您推荐 {len(top)} 个适合「{scene_desc}」的非遗项目：\n")

        for i, (score, item, meta, labels) in enumerate(top, 1):
            parts.append(f"**{i}. {item.title}**")
            parts.append(f"  - 类别：{item.category} | 级别：{meta.level}")
            if meta.display_forms:
                parts.append(f"  - 展示形式：{'、'.join(meta.display_forms)}")
            parts.append(f"  - 教育价值：{labels.education_value} | 互动潜力：{labels.interaction_potential}")
            parts.append(f"  - 简介：{item.summary[:120]}")
            parts.append("")

        selection_reason = _build_selection_reason(scenario, audience, constraints, len(top))

        evidence: list[dict[str, Any]] = []
        for _, item, _, labels in top:
            evidence.append({
                "type": "inferred",
                "claim": "推荐排序",
                "basis": f"scenario={scenario}, education={labels.education_value}",
                "item_id": item.id,
            })

        return AgentResult(
            task_type=TaskType.RECOMMENDATION,
            answer="\n".join(parts),
            items=[_enriched_item_card(item) for _, item, _, _ in top],
            evidence=evidence,
            selection_reason=selection_reason,
            mode="fallback",
            confidence=0.7,
            warnings=[] if top else [f"未找到适合「{scene_desc}」的项目，建议放宽条件"],
        )

    def _handle_exhibition(self, analysis) -> AgentResult:
        """EXHIBITION_PLAN: recommendation sub-pipeline + exhibition template."""
        # Ensure a reasonable minimum — "策划一个展" means 1 exhibition, not 1 item
        if analysis.retrieval_count < 5:
            analysis.retrieval_count = 5

        # Reuse recommendation
        rec = self._handle_recommend(analysis)

        rec.task_type = TaskType.EXHIBITION_PLAN

        scene = analysis.scenario or "非遗展示"
        audience = analysis.audience or "公众"
        time_budget = analysis.time_budget or "待定"

        lines = [
            "## 非遗展示策划方案",
            "",
            f"- **场景：**{scene}",
            f"- **受众：**{audience}",
            f"- **时长：**{time_budget}",
            "",
            "### 推荐展项",
            "",
        ]

        for i, item_data in enumerate(rec.items, 1):
            display = "、".join(item_data.get("display_forms", ["展板"]))
            lines.append(f"#### {i}. {item_data['title']}")
            lines.append(f"- **展示形式：**{display}")
            lines.append(f"- **核心讲解：**{item_data['summary'][:100]}……")
            lines.append(f"- **互动环节：**[建议：知识问答 / 手工体验 / VR 展示]")
            lines.append(f"- **所需物料：**[建议：展板×2 / 实物×1 / 多媒体设备]")
            lines.append("")

        lines.append("---")
        lines.append("*本方案由 Xuhua AI 基于非遗数据自动生成，互动环节与物料建议仅供参考。*")

        rec.answer = "\n".join(lines)
        rec.warnings.append("展示方案为模板生成，互动环节与物料建议待人工补充。")
        return rec


def task_type_label(task_type: TaskType) -> str:
    labels: dict[TaskType, str] = {
        TaskType.CHITCHAT: "对话回应",
        TaskType.FACT_QA: "事实问答",
        TaskType.BROWSE_QUERY: "浏览查询",
        TaskType.COMPARISON: "项目对比",
        TaskType.RECOMMENDATION: "项目推荐",
        TaskType.EXHIBITION_PLAN: "展览策划",
        TaskType.STUDY_TASK: "研学教案",
        TaskType.CONTENT_TRANSFORM: "内容转化",
    }
    return labels.get(task_type, task_type.value)


def task_type_from_str(value: str) -> TaskType:
    try:
        return TaskType(value)
    except ValueError:
        return TaskType.FACT_QA


# ── MVP helper functions ──────────────────────────────────────────────


def is_chitchat_query(query: str) -> bool:
    return clean_direct_query(query) in _CHITCHAT_TERMS


def clean_direct_query(query: str) -> str:
    return normalize_text(query).strip(_TRAILING_PARTICLES).lower()


def contains_any(query: str, terms: tuple[str, ...]) -> bool:
    lowered = query.lower()
    return any(term.lower() in lowered for term in terms)


def leaks_internal_planner_identity(text: str) -> bool:
    return contains_any(text, _INTERNAL_PLANNER_TERMS)


def should_use_model_planner() -> bool:
    if not config.AI_AGENT_PLANNER:
        return False
    if os.getenv("PYTEST_CURRENT_TEST"):
        return False
    if not config.AI_API_KEY or config.AI_API_KEY in {"test-key", "should-not-be-needed"}:
        return False
    return True


def call_agent_planner_model(query: str, kb: KnowledgeBase, category: str = "") -> AgentDecision:
    payload = {
        "model": config.AI_MODEL,
        "messages": build_agent_planner_messages(query, kb, category),
        "temperature": 0,
        **agent_planner_extra_options(),
    }
    request = urllib.request.Request(
        config.AI_BASE_URL.rstrip("/") + "/chat/completions",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {config.AI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=min(config.AI_TIMEOUT, 20)) as response:
        body = json.loads(response.read().decode("utf-8"))

    content = body["choices"][0]["message"]["content"]
    plan = json.loads(extract_json_object(content))
    return decision_from_planner_payload(plan, query, kb, category)


def build_agent_planner_messages(query: str, kb: KnowledgeBase, category: str = "") -> list[dict[str, str]]:
    categories = "、".join(category.name for category in kb.categories[:12])
    return [
        {
            "role": "system",
            "content": (
                "你是叙华智能体的内部规划器，用户不可见，不直接编造资料。"
                "你的任务只是在后台决定下一步行动，不是扮演最终回答者。"
                "可选任务类型：chitchat, fact_qa, browse_query, comparison, recommendation, "
                "exhibition_plan, study_task, content_transform。"
                "可选动作：direct_answer（身份/能力/寒暄/越界说明）、retrieval_tool（查资料库）、"
                "rule_handler（筛选/对比/推荐/策划/教案）、llm_generation（基于检索资料生成）。"
                "身份、能力、'你知道什么'、'你懂什么'、寒暄感谢，必须选 chitchat，"
                "needs_retrieval=false，needs_llm=false，并给出 direct_answer。"
                "direct_answer 必须使用用户可见角色“叙华”的口吻回答；"
                "身份问题应回答“我是叙华，一个面向河南非遗资料库的问答助手”。"
                "不要在 direct_answer 中提到内部规划器、后台、决策层、路由、JSON、工具选择等实现细节。"
                "明显不属于非遗资料库的问题，needs_retrieval=false，needs_llm=false，mode=no_context，"
                "给出能力边界说明。"
                "只输出 JSON，不要输出 markdown，不要解释。"
            ),
        },
        {
            "role": "user",
            "content": (
                f"用户问题：{query}\n"
                f"显式分类筛选：{category or '无'}\n"
                f"资料库概况：{len(kb.items)} 个非遗项目，{len(kb.categories)} 类，类别包括：{categories}\n\n"
                "请输出 JSON："
                '{"task_type":"...", "confidence":0.0, "needs_retrieval":true, '
                '"needs_llm":true, "reason":"...", "direct_answer":"", '
                '"mode":"local", "warnings":[]}'
            ),
        },
    ]


def agent_planner_extra_options() -> dict[str, Any]:
    model = config.AI_MODEL.lower()
    if any(name in model for name in ("glm-4.5", "glm-4.6", "glm-4.7", "glm-5")):
        return {"thinking": {"type": "disabled"}}
    return {}


def extract_json_object(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.lower().startswith("json"):
            text = text[4:].strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        raise ValueError(f"Planner did not return JSON: {text[:120]}")
    return text[start : end + 1]


def decision_from_planner_payload(
    payload: dict[str, Any],
    query: str,
    kb: KnowledgeBase,
    category: str = "",
) -> AgentDecision:
    task_type = task_type_from_str(str(payload.get("task_type") or "fact_qa"))
    confidence = clamp_float(payload.get("confidence"), default=0.7)
    needs_retrieval = bool(payload.get("needs_retrieval", task_type is not TaskType.CHITCHAT))
    needs_llm = bool(payload.get("needs_llm", task_type in {TaskType.FACT_QA, TaskType.CONTENT_TRANSFORM}))
    reason = normalize_text(payload.get("reason") or "模型 planner 已选择下一步行动。")
    direct_answer = normalize_text(payload.get("direct_answer") or "")
    mode = str(payload.get("mode") or "local")
    warnings = payload.get("warnings") or []
    if not isinstance(warnings, list):
        warnings = [str(warnings)]

    if task_type is TaskType.CHITCHAT:
        needs_retrieval = False
        needs_llm = False
        mode = "local"
        if clean_direct_query(query) in _CHITCHAT_TERMS:
            direct_answer = build_chitchat_answer(query, kb)
        elif not direct_answer or leaks_internal_planner_identity(direct_answer):
            direct_answer = build_chitchat_answer(query, kb)
    elif not needs_retrieval and not needs_llm and not direct_answer:
        mode = "no_context"
        direct_answer = build_out_of_scope_answer()
        if not warnings:
            warnings = ["模型 planner 判断问题不需要资料库或生成模型处理。"]

    return AgentDecision(
        task_type=task_type,
        confidence=confidence,
        needs_retrieval=needs_retrieval,
        needs_llm=needs_llm,
        reason=reason,
        direct_answer=direct_answer,
        mode=mode,
        warnings=[str(item) for item in warnings],
        planner="model",
    )


def clamp_float(value: Any, default: float = 0.7) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, number))


def build_chitchat_answer(query: str, kb: KnowledgeBase | None = None) -> str:
    normalized = query.strip().lower()
    if contains_any(normalized, _IDENTITY_TERMS):
        return (
            "我是叙华，一个面向河南非遗资料库的问答助手。"
            "我可以帮你解释某个非遗项目的历史、技艺特点、代表作品和传承价值，"
            "也可以按场景推荐项目，或辅助策划非遗展示方案。"
        )
    if contains_any(normalized, _CAPABILITY_TERMS):
        return build_capability_answer(kb)
    if contains_any(normalized, _THANKS_TERMS):
        return "不客气，我在这里。你可以继续问我非遗项目、资料筛选或展示策划相关的问题。"
    return "你好，我在这里。你可以问我某个非遗项目的历史、技艺特点、代表作品，也可以让我推荐项目或策划展示方案。"


def build_capability_answer(kb: KnowledgeBase | None = None) -> str:
    if kb is None:
        return (
            "我主要知道非遗资料库里的项目资料，可以回答历史、技艺特点、代表作品和传承价值，"
            "也能做筛选、对比、推荐、展示策划、研学教案和内容改写。"
        )

    categories = [category.name for category in kb.categories[:8]]
    category_text = "、".join(categories)
    more = "等" if len(kb.categories) > len(categories) else ""
    examples = "例如可以问：“汴绣有什么特点？”“河南有哪些传统美术？”“推荐3个适合校园展示的项目？”"
    return (
        f"我掌握当前资料库中的 {len(kb.items)} 个非遗项目，覆盖 {len(kb.categories)} 类，"
        f"包括{category_text}{more}。我能做的不只是回答单个项目：还可以按地区、类别、级别筛选，"
        "比较两个项目，按校园展示或社区活动等场景推荐项目，生成展示方案、研学教案，"
        f"也能把资料改写成更适合传播的文案。{examples}"
    )


def has_domain_hint(query: str) -> bool:
    return contains_any(query, _DOMAIN_HINT_TERMS)


def should_answer_out_of_scope(kb: KnowledgeBase, query: str, category: str = "") -> bool:
    """Return true when a default fact question is outside the heritage assistant's scope."""
    if has_domain_hint(query):
        return False

    return not has_dataset_anchor(kb, query, category)


def has_dataset_anchor(kb: KnowledgeBase, query: str, category: str = "") -> bool:
    """Check for a strong item/category anchor without accepting weak body-text hits."""
    query = normalize_text(query)
    category = normalize_text(category)
    if not query:
        return False

    if category and category in query:
        return True

    for item in kb.items:
        if category and item.category != category:
            continue
        names = [item.title, *item.aliases]
        base_title = item.title.split("（")[0].split("(")[0].strip()
        if base_title and base_title != item.title:
            names.append(base_title)
        for name in names:
            name = normalize_text(name)
            if len(name) >= 2 and (name in query or query in name):
                return True

    from .search import search_items_pinyin

    return any(
        not category or item.category == category
        for item in search_items_pinyin(kb, query)
    )


def normalize_query_with_pinyin_anchor(kb: KnowledgeBase, query: str, category: str = "") -> str:
    """Rewrite same-sound user text to the canonical dataset title when possible."""
    query = normalize_text(query)
    if not query:
        return query

    from .search import search_items_pinyin

    for item in search_items_pinyin(kb, query):
        if category and item.category != category:
            continue
        corrected = replace_homophone_span(query, item.title)
        if corrected != query:
            return corrected
    return query


def replace_homophone_span(text: str, canonical: str) -> str:
    if canonical in text:
        return text
    try:
        from pypinyin import lazy_pinyin  # noqa: PLC0415 - optional dependency
    except ImportError:
        return text

    canonical_py = "".join(lazy_pinyin(canonical))
    if not canonical_py:
        return text

    for start in range(len(text)):
        for end in range(start + 2, len(text) + 1):
            span = text[start:end]
            if "".join(lazy_pinyin(span)) == canonical_py:
                return f"{text[:start]}{canonical}{text[end:]}"
    return text


def build_out_of_scope_answer() -> str:
    return (
        "这个问题看起来不属于当前非遗资料库的范围。"
        "我更适合回答非遗项目的历史、技艺特点、代表作品、传承价值，"
        "也可以帮你按地区、类别、级别筛选资料，或推荐适合展示、研学、社区活动的非遗项目。"
    )


def with_agent_decision(
    result: AgentResult,
    decision: AgentDecision,
    include_speech: bool,
) -> AgentResult:
    result = replace(result, decision=decision.to_payload())
    if not include_speech:
        result = replace(result, speech="")
    return result


def _enriched_item_card(item) -> dict[str, Any]:
    """item_to_dict enriched with StructuredMeta fields."""
    card = item_to_dict(item)
    meta = get_structured_meta(item.id)
    if meta:
        card["level"] = meta.level
        card["province"] = meta.province
        card["city"] = meta.city
        card["district"] = meta.district
        card["display_forms"] = list(meta.display_forms)
    return card


def _describe_filters(category: str, province: str, level: str) -> str:
    parts: list[str] = []
    if province:
        parts.append(province)
    if level:
        parts.append(level)
    if category:
        parts.append(category)
    return "".join(parts) if parts else ""


def _score_for_recommendation(meta, labels, constraints: list[str]) -> int:
    """Score an item for recommendation. Higher = better fit."""
    score = 0

    # Education value
    edu = labels.education_value
    if edu == "高":
        score += 4
    elif edu == "中":
        score += 2

    # Interaction potential
    inter = labels.interaction_potential
    if inter == "高":
        score += 3
    elif inter == "中":
        score += 1

    # Level bonus
    lvl = meta.level
    if lvl == "人类":
        score += 5
    elif lvl == "国家级":
        score += 3
    elif lvl == "省级":
        score += 1

    # Constraint matching
    if "展示难度低" in constraints and labels.display_difficulty == "低":
        score += 3
    if "互动性强" in constraints and labels.interaction_potential == "高":
        score += 3

    return score


def _build_selection_reason(scenario: str, audience: str, constraints: list[str], count: int) -> str:
    parts = [f"共推荐 {count} 个项目"]
    if scenario:
        parts.append(f"匹配场景「{scenario}」")
    if audience:
        parts.append(f"适合「{audience}」受众")
    parts.append("排序依据：教育价值 + 互动潜力 + 非遗级别")
    return "，".join(parts)


_TRANSFORM_PROMPTS: dict[str, str] = {
    "翻译": (
        "你是一个非遗资料翻译助手。请将以下非遗项目的中文介绍翻译为英文，"
        "保持专业术语的准确性，格式清晰易读。"
    ),
    "年轻化": (
        "你是一个面向年轻受众的非遗科普写手。请将以下非遗项目用轻松、"
        "口语化的语言重新介绍，适合发在社交媒体上，保留关键信息但语气活泼。"
    ),
    "朋友圈": (
        "你是一个非遗文化传播者。请将以下非遗项目用适合发朋友圈的风格改写，"
        "200字以内，带 emoji，有趣有料，结尾可以加话题标签。"
    ),
    "文创文案": (
        "你是一个非遗文创设计师。基于以下非遗项目的核心元素，"
        "生成一份文创设计方案概要，包括：设计灵感来源、可提取的视觉/技艺元素、"
        "建议的产品类型（文具/家居/服饰/数字产品等）、目标受众和产品调性。"
    ),
    "改写": (
        "你是一个非遗内容编辑。请将以下非遗项目的介绍进行改写优化，"
        "使内容更适合一般公众阅读，语言流畅有感染力，突出文化价值。"
    ),
}


def _call_transform_model(transform_type: str, context: str, query: str) -> str:
    """Call LLM with a task-specific system prompt for content transformation."""
    import json
    import urllib.error
    import urllib.request

    from . import config

    system_prompt = _TRANSFORM_PROMPTS.get(transform_type, _TRANSFORM_PROMPTS["改写"])
    payload = {
        "model": config.AI_MODEL,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"任务要求：{query}\n\n非遗项目资料：\n{context}"},
        ],
        "temperature": 0.7,
    }
    url = config.AI_BASE_URL.rstrip("/") + "/chat/completions"
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Authorization": f"Bearer {config.AI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=config.AI_TIMEOUT) as response:
        body = json.loads(response.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"].strip()


def _build_transform_local(transform_type: str, target_item, meta) -> str:
    """Build a template-based local answer for content transformation."""
    title = target_item.title
    category = target_item.category
    summary = target_item.summary
    features = meta.features if meta and meta.features else summary

    if transform_type == "翻译":
        return (
            f"## English Translation: {title}\n\n"
            f"**Category:** {category}\n\n"
            f"{summary}\n\n"
            "*This is a local template. Configure an LLM API key for a full translation.*"
        )
    if transform_type in ("年轻化", "朋友圈"):
        return (
            f"## {title} · 轻松版介绍\n\n"
            f"🎨 你知道吗？{title}可是{meta.level if meta else ''}非遗项目！\n\n"
            f"{features[:200]}……\n\n"
            f"想了解更多？来看看这个传承了数百年的技艺吧！\n\n"
            "*本地模板生成，配置 API Key 可获得更生动的改写。*"
        )
    if transform_type == "文创文案":
        return (
            f"## 文创设计概要：{title}\n\n"
            f"### 灵感来源\n"
            f"从 {title} 的核心技艺和视觉元素中提取设计语言。\n\n"
            f"### 可提取元素\n"
            f"- 技艺特点：{features[:100]}……\n"
            f"- 色彩与纹样：[建议：从项目中提取代表性图案和配色方案]\n"
            f"- 文化符号：[建议：整理项目的标志性视觉元素]\n\n"
            f"### 产品类型建议\n"
            f"- 文具类：笔记本封面、书签、明信片\n"
            f"- 家居类：装饰画、杯垫、抱枕\n"
            f"- 数字类：表情包、手机壁纸、H5互动\n\n"
            f"### 目标受众\n"
            f"- 对传统文化感兴趣的年轻人（18-35岁）\n"
            f"- 旅游纪念品消费者\n"
            f"- 文化教育产品用户\n\n"
            "*本地模板生成，配置 API Key 可获得更详细的创意方案。*"
        )
    # Generic rewrite
    return (
        f"## {title} · 内容改写\n\n"
        f"{summary}\n\n"
        f"**核心特色：**{features[:200]}\n\n"
        "*本地模板生成，配置 API Key 可获得更优化的改写内容。*"
    )
