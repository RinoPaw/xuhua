"""Intent router and task dispatcher for the heritage RAG agent."""

from __future__ import annotations

import json
import logging
import re
import urllib.error
import urllib.request
from dataclasses import replace
from typing import Any

from . import config
from .agent_models import (
    AgentDecision,
    AgentResult,
    TaskConfig,
    TaskResult,
    TaskType,
    task_type_from_str,
    task_type_label,
)
from .agent_task_config import TASK_CONFIGS, _TASK_CONFIGS
from .dataset import (
    KnowledgeBase,
    get_soft_labels,
    get_structured_meta,
    normalize_text,
)
from .item_cards import _enriched_item_card, _source_payload, _title_with_family

__all__ = [
    "Agent",
    "AgentDecision",
    "AgentResult",
    "IntentRouter",
    "TaskConfig",
    "TaskResult",
    "TaskType",
    "TASK_CONFIGS",
    "_TASK_CONFIGS",
    "task_type_from_str",
    "task_type_label",
]

LOGGER = logging.getLogger(__name__)

class IntentRouter:
    """Plan user input with the model planner."""

    def decide(self, query: str, kb: KnowledgeBase, category: str = "") -> AgentDecision:
        """Plan the next action before retrieval/generation.

        This is the agentic boundary: the app decides whether it should talk,
        search, use a rule handler, call an LLM-backed path, or decline because
        the request is outside the heritage data domain.
        """
        return call_agent_planner_model(query, kb, category)

    def plan(self, query: str, kb: KnowledgeBase, category: str = "") -> AgentDecision:
        """Alias for callers that want an explicit agent planning API."""
        return self.decide(query, kb, category)

    def needs_retrieval(self, query: str, kb: KnowledgeBase, category: str = "") -> bool:
        return self.decide(query, kb, category).needs_retrieval


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
        yield self._progress_event("classify", "理解问题", "正在判断任务类型，并识别项目名称、地区和输出要求")
        try:
            decision = self.router.decide(query, self.kb, category)
        except Exception as exc:  # noqa: BLE001 - planner failure is reported as a user-visible error.
            from .ai import describe_model_error

            warning = describe_model_error(exc)
            LOGGER.warning("Agent planner unavailable: %s", warning)
            yield AgentResult(
                task_type=TaskType.FACT_QA,
                answer="模型规划暂时不可用，无法判断这次应该执行哪类任务。请检查模型配置或稍后再试。",
                speech="模型规划暂时不可用，请稍后再试。" if include_speech else "",
                mode="planner_error",
                confidence=0.0,
                warnings=[warning],
                decision={
                    "task_type": TaskType.FACT_QA.value,
                    "confidence": 0.0,
                    "needs_retrieval": False,
                    "needs_llm": False,
                    "reason": "模型 planner 调用失败。",
                    "mode": "planner_error",
                    "warnings": [warning],
                    "planner": "model",
                },
            )
            return
        task_type = decision.task_type
        yield self._progress_event("classify", "理解问题", decision.reason)
        if decision.direct_answer:
            yield from self._stream_direct_answer(decision, include_speech)
            return

        analyzer = QueryAnalyzer(self.kb)
        analysis = analyzer.analyze(query, task_type)

        # Step 2: search
        yield self._progress_event("search", "检索资料", "正在检索资料库，优先匹配明确标题和结构化字段")

        task_config = TASK_CONFIGS.get(task_type, TASK_CONFIGS[TaskType.FACT_QA])
        yield self._progress_event("generate", "思考回答", task_config.generate_detail)
        if task_config.handler_name:
            result = self._run_configured_handler(task_config, analysis)
        else:
            result = self._build_fact_result(analysis, query, category, decision)
        yield from self._stream_completed_result(result, decision, include_speech, query=query)

    def _progress_event(self, step: str, title: str, detail: str) -> dict[str, str]:
        return {
            "type": "progress",
            "step": step,
            "title": title,
            "detail": detail,
        }

    def _stream_direct_answer(self, decision: AgentDecision, include_speech: bool):
        yield self._progress_event("search", "检索资料", "智能体决策为直接回应，已跳过资料库检索。")
        yield self._progress_event("generate", "思考回答", TASK_CONFIGS[TaskType.CHITCHAT].generate_detail)
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
            include_speech=False,
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
        query: str = "",
    ):
        if include_speech and result.answer:
            yield self._progress_event("speech", "润色播报", "正在把最终回答压缩成更适合朗读的版本")
            result = self._ensure_speech(result, query=query)
        yield with_agent_decision(result, decision, include_speech)

    def _ensure_speech(self, result: AgentResult, query: str = "") -> AgentResult:
        if result.speech:
            return result
        from .ai import build_spoken_answer

        speech = build_spoken_answer(
            result.answer,
            question=query,
            sources=self._speech_source_items(result),
        )
        return replace(result, speech=speech)

    def _speech_source_items(self, result: AgentResult) -> list[Any]:
        source_items: list[Any] = []
        seen: set[str] = set()
        for payload in [*result.sources, *result.items]:
            item_id = payload.get("id") if isinstance(payload, dict) else ""
            if not item_id or item_id in seen:
                continue
            item = self.kb.get(item_id)
            if item is None:
                continue
            seen.add(item_id)
            source_items.append(item)
        return source_items

    # ── MVP handlers ───────────────────────────────────────────────────

    def _handle_comparison(self, analysis) -> AgentResult:
        """COMPARISON: multi-entity structured comparison, no LLM."""
        from .agent_comparison import handle_comparison

        return handle_comparison(self.kb, analysis)

    def _handle_study_task(self, analysis) -> AgentResult:
        """STUDY_TASK: curriculum/teaching plan generation, no LLM."""
        from .search import search_items_lexical

        target_item = None
        target_meta = None
        # Try to resolve a specific target entity
        if analysis.entities:
            entity = analysis.entities[0]
            result, _ = search_items_lexical(self.kb, query=entity, limit=1)
            if result:
                target_item = result[0]
                target_meta = get_structured_meta(target_item.id)

        # If no specific entity found, fall back to recommendation
        if target_item is None:
            rec_result = self._handle_recommend(analysis)
            if rec_result.items:
                # Use the first recommended item
                target_item = self.kb.get(rec_result.items[0]["id"])
                if target_item:
                    target_meta = get_structured_meta(target_item.id)

        if target_item is None:
            # Nothing to work with — fall through to LLM
            from .ai import Answer, answer_question

            answer: Answer = answer_question(
                self.kb,
                question=analysis.rewritten_query or analysis.original_query,
                include_speech=False,
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

        title = _title_with_family(target_item)
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
            f"**研学场景：**{scenario}",
            f"**所属类别：**{category}",
            f"**展示形式：**{display}",
            "",
            "### 一、教学目标",
            "",
            f"1. **知识目标：**了解{title}的历史渊源、技艺特点和代表性作品。",
            f"2. **能力目标：**通过观察、讨论和实践体验，培养学生对传统{category}项目的感知和分析能力。",
            "3. **情感目标：**激发对非遗文化的兴趣和认同感，理解保护传承的意义。",
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
            "- 与美术课、历史课、语文课进行跨学科联动。",
            "- 鼓励学生制作非遗主题手抄报或短视频介绍。",
            "",
            "---",
            "*本教案由 Xuhua AI 基于非遗数据自动生成，建议教师根据实际学情调整。*",
        ])

        sources = [_source_payload(target_item)]
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
                include_speech=False,
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
            elif re.search(r"讲解词|讲解稿|口播稿|解说词", q):
                transform_type = "讲解词"
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
                answer_text = _call_transform_model(
                    transform_type=transform_type,
                    context=context,
                    query=analysis.original_query,
                )
                return AgentResult(
                    task_type=TaskType.CONTENT_TRANSFORM,
                    answer=answer_text,
                    sources=[_source_payload(target_item)],
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
            sources=[_source_payload(target_item)],
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
            lines.append(f"{i}. {_title_with_family(item)} — {item.category}{level_str}{city_str}")

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
            sources=[_source_payload(item) for item in result],
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
            parts.append(f"**{i}. {_title_with_family(item)}**")
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
            title = item_data["title"]
            family = item_data.get("family") or ""
            if family and family not in title:
                title = f"{title}（{family}）"
            lines.append(f"#### {i}. {title}")
            lines.append(f"- **展示形式：**{display}")
            lines.append(f"- **核心讲解：**{item_data['summary'][:100]}……")
            lines.append("- **互动环节：**[建议：知识问答 / 手工体验 / VR 展示]")
            lines.append("- **所需物料：**[建议：展板×2 / 实物×1 / 多媒体设备]")
            lines.append("")

        lines.append("---")
        lines.append("*本方案由 Xuhua AI 基于非遗数据自动生成，互动环节与物料建议仅供参考。*")

        rec.answer = "\n".join(lines)
        rec.warnings.append("展示方案为模板生成，互动环节与物料建议待人工补充。")
        return rec


def call_agent_planner_model(query: str, kb: KnowledgeBase, category: str = "") -> AgentDecision:
    if not config.AI_AGENT_PLANNER:
        raise RuntimeError("AI_AGENT_PLANNER is disabled")
    if not config.AI_API_KEY:
        raise RuntimeError("AI_API_KEY is not configured")
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
                "请根据用户最终意图自主选择最合适的任务类型和动作。"
                "direct_answer 必须使用用户可见角色“叙华”的口吻回答。"
                "不要在 direct_answer 中提到内部规划器、后台、决策层、路由、JSON、工具选择等实现细节。"
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
    elif not needs_retrieval and not needs_llm:
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


def with_agent_decision(
    result: AgentResult,
    decision: AgentDecision,
    include_speech: bool,
) -> AgentResult:
    result = replace(result, decision=decision.to_payload())
    if not include_speech:
        result = replace(result, speech="")
    return result



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
    "讲解词": (
        "你是一个非遗展馆讲解员。请基于以下非遗项目资料生成面向公众的讲解词，"
        "语言清楚、有画面感，适合现场或视频口播，避免编造资料外事实。"
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
    title = _title_with_family(target_item)
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
    if transform_type == "讲解词":
        return (
            f"## {title} · 讲解词\n\n"
            f"各位朋友，大家好。今天我们认识的项目是{title}，它属于{category}。"
            f"{summary}\n\n"
            f"它最值得关注的地方，是这些经过长期传承留下来的技艺和审美：{features[:220]}……\n\n"
            "如果把它放到展览或课堂里，可以从历史来源、制作流程、视觉特色和当代传承四个角度展开，"
            "让观众既能看到作品，也能理解作品背后的生活记忆。\n\n"
            "*本地模板生成，配置 API Key 可获得更完整的讲解词。*"
        )
    # Generic rewrite
    return (
        f"## {title} · 内容改写\n\n"
        f"{summary}\n\n"
        f"**核心特色：**{features[:200]}\n\n"
        "*本地模板生成，配置 API Key 可获得更优化的改写内容。*"
    )
