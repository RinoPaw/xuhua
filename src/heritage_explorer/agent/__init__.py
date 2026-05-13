"""Intent router and task dispatcher for the heritage RAG agent."""

from __future__ import annotations

import logging
import json
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader

from .. import config
from ..agent_models import (
    AgentDecision,
    AgentResult,
    TaskConfig,
    TaskResult,
    TaskType,
    task_type_from_str,
    task_type_label,
)
from ..agent_task_config import TASK_CONFIGS, _TASK_CONFIGS
from ..dataset import (
    get_structured_meta,
    KnowledgeBase,
    normalize_text,
)
from ..item_cards import _enriched_item_card, _source_payload, _title_with_family
from ..transform_config import (
    DEFAULT_TRANSFORM_TYPE,
    TRANSFORM_MAX_TOKENS,
    TRANSFORM_PROMPTS,
)
from .planner import (  # noqa: F401 - re-exported for backward compat
    agent_planner_extra_options,
    build_agent_planner_messages,
    call_agent_planner_model,
    clamp_float,
    decision_from_planner_payload,
    extract_json_object,
)

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
    "agent_planner_extra_options",
    "build_agent_planner_messages",
    "call_agent_planner_model",
    "clamp_float",
    "decision_from_planner_payload",
    "extract_json_object",
    "normalize_query_with_pinyin_anchor",
    "replace_homophone_span",
    "task_type_from_str",
    "task_type_label",
]

LOGGER = logging.getLogger(__name__)

_TEMPLATE_DIR = Path(__file__).resolve().parents[3] / "templates"
_JINJA_ENV = Environment(
    loader=FileSystemLoader(str(_TEMPLATE_DIR)),
    autoescape=False,
)

def _render_template(name, **kwargs):
    return _JINJA_ENV.get_template(name).render(**kwargs)

class IntentRouter:
    """Plan user input with the model planner."""

    def decide(
        self, query: str, kb: KnowledgeBase,
        category: str = "", context: dict | None = None,
    ) -> AgentDecision:
        return call_agent_planner_model(query, kb, category, context)

    def plan(
        self, query: str, kb: KnowledgeBase,
        category: str = "", context: dict | None = None,
    ) -> AgentDecision:
        return self.decide(query, kb, category, context)

    def needs_retrieval(
        self, query: str, kb: KnowledgeBase,
        category: str = "", context: dict | None = None,
    ) -> bool:
        return self.decide(query, kb, category, context).needs_retrieval


class Agent:
    """Top-level agent: intent classification -> query analysis -> dispatch.

    MVP dispatches 3 TaskTypes with dedicated pipelines:
      - BROWSE_QUERY    -> structured filters + local listing (no LLM)
      - RECOMMENDATION  -> SoftLabels matching + rule scoring
      - EXHIBITION_PLAN -> recommendation sub-pipeline + template
    All other types fall through to the existing answer_question flow.
    """

    def __init__(self, kb: KnowledgeBase) -> None:
        self.kb = kb
        self.router = IntentRouter()

    # -- dispatch --------------------------------------------------------

    def dispatch(
        self, query: str, category: str = "",
        include_speech: bool = True, context: dict | None = None,
    ) -> AgentResult:
        """Backward-compat wrapper: consume stream and return final result."""
        result = None
        speech_text = ""
        for event in self.dispatch_stream(query, category, include_speech=include_speech, context=context):
            if isinstance(event, AgentResult):
                result = event
            elif isinstance(event, dict) and event.get("type") == "speech":
                speech_text = str(event.get("text") or "")
        if result and speech_text and not result.speech:
            result = replace(result, speech=speech_text)
        return result

    def dispatch_stream(
        self, query: str, category: str = "",
        include_speech: bool = True, context: dict | None = None,
    ):
        """Generator: yields progress dicts, then AgentResult."""
        from ..retriever import QueryAnalyzer

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
            decision = self.router.decide(query, self.kb, category, context)
        except Exception as exc:  # noqa: BLE001 - planner failure is reported as a user-visible error.
            from ..ai import describe_model_error

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
        analysis = analyzer.analyze(query, task_type, context)

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
        from ..ai import Answer, answer_question

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
        # If handler already filled speech, yield result as-is
        if not include_speech or result.speech:
            yield with_agent_decision(result, decision, include_speech)
            return

        # No speech yet — yield answer immediately, speech event follows
        yield with_agent_decision(replace(result, speech=""), decision, include_speech)
        if result.answer:
            result = self._ensure_speech(result, query=query)
            yield {"type": "speech", "text": result.speech}

    def _ensure_speech(self, result: AgentResult, query: str = "") -> AgentResult:
        if result.speech:
            return result
        from ..ai import build_spoken_answer

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

    # -- MVP handlers -----------------------------------------------------

    def _handle_comparison(self, analysis) -> AgentResult:
        """COMPARISON: multi-entity structured comparison, no LLM."""
        from ..agent_comparison import handle_comparison

        return handle_comparison(self.kb, analysis)

    def _handle_study_task(self, analysis) -> AgentResult:
        """STUDY_TASK: curriculum/teaching plan generation, no LLM."""
        from ..search import search_items_lexical

        target_item = None
        # Try to resolve a specific target entity
        if analysis.entities:
            entity = analysis.entities[0]
            result, _ = search_items_lexical(self.kb, query=entity, limit=1)
            if result:
                target_item = result[0]

        # If no specific entity found, fall back to recommendation
        if target_item is None:
            rec_result = self._handle_recommend(analysis)
            if rec_result.items:
                # Use the first recommended item
                target_item = self.kb.get(rec_result.items[0]["id"])

        if target_item is None:
            # Nothing to work with -- fall through to LLM
            from ..ai import Answer, answer_question

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

        features = target_item.features[:200] if target_item.features else summary
        history = target_item.history[:200] if target_item.history else ""
        display = "、".join(target_item.display_forms) if target_item.display_forms else "展板 + 讲解"
        cultural_value = target_item.cultural_value[:200] if target_item.cultural_value else ""

        answer = _render_template(
            "study_task.md.j2",
            title=title,
            audience_label=audience_label,
            time_budget=time_budget,
            scenario=scenario,
            category=category,
            display=display,
            features=features,
            history=history,
            cultural_value=cultural_value,
        ).strip()

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
            answer=answer,
            items=items,
            sources=sources,
            evidence=evidence,
            mode="local",
            confidence=0.8,
            warnings=["教案为模板生成，建议教师根据实际学情调整教学环节和时间分配。"],
        )

    def _handle_content_transform(self, analysis) -> AgentResult:
        """CONTENT_TRANSFORM: translate / rewrite / creative brief."""
        from ..search import search_items_lexical
        from ..ai import Answer, answer_question

        # Resolve target entity
        target_item = None
        if analysis.entities:
            entity = analysis.entities[0]
            result, _ = search_items_lexical(self.kb, query=entity, limit=1)
            if result:
                target_item = result[0]

        if target_item is None:
            # No entity found -- fall through
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

        meta = get_structured_meta(target_item.id)
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
        context_lines = [
            f"标题：{target_item.title}",
            f"类别：{target_item.category}",
        ]
        if target_item.province:
            context_lines.append(f"省份：{target_item.province}")
        if target_item.city:
            context_lines.append(f"城市：{target_item.city}")
        if target_item.level:
            context_lines.append(f"级别：{target_item.level}")
        if target_item.features:
            context_lines.append(f"主要特色：{target_item.features}")
        if target_item.history:
            context_lines.append(f"历史背景：{target_item.history}")
        if target_item.cultural_value:
            context_lines.append(f"重要价值：{target_item.cultural_value}")
        context_lines.append(f"简介：{target_item.summary}")
        context_lines.append(f"正文片段：{target_item.content[:800]}")
        context = "\n".join(context_lines)

        if config.AI_API_KEY:
            if transform_type == "翻译":
                return self._handle_bilingual_transform(
                    context=context,
                    query=analysis.original_query,
                    target_item=target_item,
                )
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

        # Local fallback
        if transform_type == "翻译":
            return AgentResult(
                task_type=TaskType.CONTENT_TRANSFORM,
                answer="双语翻译需要配置 API Key。请在环境变量中设置 AI_API_KEY 后重试。",
                items=[_enriched_item_card(target_item)],
                sources=[_source_payload(target_item)],
                mode="unavailable",
                confidence=0.0,
            )
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

    def _handle_bilingual_transform(self, context: str, query: str, target_item) -> AgentResult:
        """Handle bilingual (翻译) transform using LLM JSON output."""
        try:
            raw = _call_transform_model(
                transform_type="翻译",
                context=context,
                query=query,
            )
        except Exception:
            return AgentResult(
                task_type=TaskType.CONTENT_TRANSFORM,
                answer="双语翻译请求失败，请稍后重试。",
                items=[_enriched_item_card(target_item)],
                sources=[_source_payload(target_item)],
                mode="llm",
                confidence=0.0,
                warnings=["LLM 调用失败"],
            )

        parsed = _parse_bilingual_json(raw)
        if parsed is None:
            return AgentResult(
                task_type=TaskType.CONTENT_TRANSFORM,
                answer=raw,
                items=[_enriched_item_card(target_item)],
                sources=[_source_payload(target_item)],
                mode="llm",
                confidence=0.5,
                warnings=["双语解析失败，已显示原始模型输出。格式为 JSON 时效果最佳。"],
            )

        field_order = [
            ("名称", "Name"),
            ("类别", "Category"),
            ("简介", "Summary"),
            ("主要特色", "Key Features"),
        ]
        bilingual_fields = [
            {
                "label_cn": label_cn,
                "label_en": label_en,
                "value_cn": parsed["fields"].get(label_cn, {}).get("zh", ""),
                "value_en": parsed["fields"].get(label_cn, {}).get("en", ""),
            }
            for label_cn, label_en in field_order
        ]
        speech = str(parsed.get("speech_en") or "").strip()

        return AgentResult(
            task_type=TaskType.CONTENT_TRANSFORM,
            answer=parsed.get("answer", ""),
            speech=speech,
            bilingual_fields=bilingual_fields,
            items=[_enriched_item_card(target_item)],
            sources=[_source_payload(target_item)],
            mode="llm",
            confidence=0.8,
        )

    def _handle_browse(self, analysis) -> AgentResult:
        """BROWSE_QUERY: structured filters + local listing, no LLM."""
        from ..search import search_items_lexical

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
            level_str = f" | {item.level}" if item.level else ""
            city_str = f" | {item.city}" if item.city else ""
            lines.append(f"{i}. {_title_with_family(item)} -- {item.category}{level_str}{city_str}")

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

        scored: list[tuple[int, Any]] = []
        for item in self.kb.items:
            # Scenario filter (soft -- skip if scenario specified and not matched)
            if scenario and scenario not in item.suitable_scenarios:
                continue
            # Audience filter (soft)
            if audience and audience not in item.target_audience:
                continue
            score = _score_for_recommendation(item, constraints)
            scored.append((score, item))

        scored.sort(key=lambda x: -x[0])
        top = scored[:limit]

        # Build answer
        parts: list[str] = []
        scene_desc = scenario or "通用"
        parts.append(f"为您推荐 {len(top)} 个适合「{scene_desc}」的非遗项目：\n")

        for i, (score, item) in enumerate(top, 1):
            parts.append(f"**{i}. {_title_with_family(item)}**")
            parts.append(f"  - 类别：{item.category} | 级别：{item.level}")
            if item.display_forms:
                parts.append(f"  - 展示形式：{'、'.join(item.display_forms)}")
            parts.append(f"  - 教育价值：{item.education_value} | 互动潜力：{item.interaction_potential}")
            parts.append(f"  - 简介：{item.summary[:120]}")
            parts.append("")

        selection_reason = _build_selection_reason(scenario, audience, constraints, len(top))

        evidence: list[dict[str, Any]] = []
        for _, item in top:
            evidence.append({
                "type": "inferred",
                "claim": "推荐排序",
                "basis": f"scenario={scenario}, education={item.education_value}",
                "item_id": item.id,
            })

        return AgentResult(
            task_type=TaskType.RECOMMENDATION,
            answer="\n".join(parts),
            items=[_enriched_item_card(item) for _, item in top],
            evidence=evidence,
            selection_reason=selection_reason,
            mode="fallback",
            confidence=0.7,
            warnings=[] if top else [f"未找到适合「{scene_desc}」的项目，建议放宽条件"],
        )

    def _handle_exhibition(self, analysis) -> AgentResult:
        """EXHIBITION_PLAN: recommendation sub-pipeline + exhibition template."""
        # For "一个小展", first gather a small candidate pool, then pick one core item.
        rec_analysis = analysis
        if analysis.item_count == 1:
            rec_analysis = replace(analysis, retrieval_count=max(analysis.retrieval_count, 5))

        # Reuse recommendation
        rec = self._handle_recommend(rec_analysis)
        if analysis.item_count == 1 and rec.items:
            selected_index, selected_reason = _select_exhibition_core_item(
                rec.items,
                scene=analysis.scenario or "非遗展示",
                audience=analysis.audience or "公众",
                time_budget=analysis.time_budget or "待定",
            )
            rec.items = [rec.items[selected_index]]
            if rec.evidence:
                rec.evidence = [rec.evidence[min(selected_index, len(rec.evidence) - 1)]]
            rec.selection_reason = selected_reason or f"先筛出 {len(rec_analysis.items) if hasattr(rec_analysis, 'items') else max(analysis.retrieval_count, 5)} 个候选，再确定 1 个核心项目"

        rec.task_type = TaskType.EXHIBITION_PLAN

        scene = analysis.scenario or "非遗展示"
        audience = analysis.audience or "公众"
        time_budget = analysis.time_budget or "待定"

        template_items = []
        for item_data in rec.items:
            display_str = "、".join(item_data.get("display_forms", ["展板"]))
            item_title = item_data["title"]
            family = item_data.get("family") or ""
            if family and family not in item_title:
                display_title = f"{item_title}（{family}）"
            else:
                display_title = item_title
            template_items.append({
                "display_title": display_title,
                "display_str": display_str,
                "summary": item_data["summary"],
            })

        rec.answer = _render_template(
            "exhibition_plan.md.j2",
            scene=scene,
            audience=audience,
            time_budget=time_budget,
            items=template_items,
        ).strip()
        rec.warnings.append("展示方案为模板生成，互动环节与物料建议待人工补充。")
        return rec


def normalize_query_with_pinyin_anchor(kb: KnowledgeBase, query: str, category: str = "") -> str:
    """Rewrite same-sound user text to the canonical dataset title when possible."""
    query = normalize_text(query)
    if not query:
        return query

    from ..search import search_items_pinyin

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


def _score_for_recommendation(item, constraints: list[str]) -> int:
    """Score an item for recommendation. Higher = better fit."""
    score = 0

    # Education value
    edu = item.education_value
    if edu == "高":
        score += 4
    elif edu == "中":
        score += 2

    # Interaction potential
    inter = item.interaction_potential
    if inter == "高":
        score += 3
    elif inter == "中":
        score += 1

    # Level bonus
    lvl = item.level
    if lvl == "人类":
        score += 5
    elif lvl == "国家级":
        score += 3
    elif lvl == "省级":
        score += 1

    # Constraint matching
    if "展示难度低" in constraints and item.display_difficulty == "低":
        score += 3
    if "互动性强" in constraints and item.interaction_potential == "高":
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


_TRANSFORM_PROMPTS = TRANSFORM_PROMPTS
_TRANSFORM_MAX_TOKENS = TRANSFORM_MAX_TOKENS


def _call_transform_model(transform_type: str, context: str, query: str) -> str:
    """Call LLM with a task-specific system prompt for content transformation."""
    from ..http_client import chat_completion

    system_prompt = _TRANSFORM_PROMPTS.get(transform_type, _TRANSFORM_PROMPTS[DEFAULT_TRANSFORM_TYPE])
    max_tokens = _TRANSFORM_MAX_TOKENS.get(transform_type, _TRANSFORM_MAX_TOKENS[DEFAULT_TRANSFORM_TYPE])
    return chat_completion(
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"任务要求：{query}\n\n非遗项目资料：\n{context}"},
        ],
        temperature=0.7,
        max_tokens=max_tokens,
    )


def _select_exhibition_core_item(
    candidate_items: list[dict[str, Any]],
    scene: str,
    audience: str,
    time_budget: str,
) -> tuple[int, str]:
    if not candidate_items:
        return 0, ""
    if len(candidate_items) == 1:
        return 0, "用户要求 1 个核心项目，当前候选仅 1 个。"
    if not config.AI_API_KEY:
        return 0, f"先筛出 {len(candidate_items)} 个候选，再按当前排序取第 1 个核心项目。"

    from ..http_client import chat_completion

    candidate_lines: list[str] = []
    for index, item in enumerate(candidate_items, 1):
        meta = " · ".join(
            part for part in [
                str(item.get("category") or ""),
                str(item.get("level") or ""),
                str(item.get("province") or ""),
                str(item.get("city") or ""),
            ] if part
        )
        display_forms = "、".join(item.get("display_forms") or [])
        summary = str(item.get("summary") or "").strip()
        candidate_lines.append(
            f"{index}. {item.get('title', '')}\n"
            f"   信息：{meta or '无'}\n"
            f"   展示形式：{display_forms or '未标注'}\n"
            f"   简介：{summary[:120]}"
        )

    system_prompt = (
        "你是非遗展示策划顾问。现在有 5 个候选项目，需要为一个小展只选出 1 个最适合作为核心项目。"
        "请综合场景、受众、时间预算、可展示性、教育价值和互动潜力判断。"
        "只输出 JSON，不要输出解释文字，不要输出 Markdown。\n"
        '{\"selected_index\": 1, \"reason\": \"一句中文理由\"}'
    )
    user_prompt = (
        f"场景：{scene}\n"
        f"受众：{audience}\n"
        f"时间预算：{time_budget}\n\n"
        "候选项目：\n"
        + "\n\n".join(candidate_lines)
    )
    try:
        raw = chat_completion(
            [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.2,
            max_tokens=220,
        )
        match = re.search(r"\{[\s\S]*\}", raw or "")
        if not match:
            raise ValueError("no json")
        data = json.loads(match.group(0))
        selected_index = int(data.get("selected_index", 1)) - 1
        if not 0 <= selected_index < len(candidate_items):
            raise ValueError("index out of range")
        reason = str(data.get("reason") or "").strip()
        if reason:
            reason = f"先筛出 {len(candidate_items)} 个候选，再由模型选定 1 个核心项目：{reason}"
        else:
            reason = f"先筛出 {len(candidate_items)} 个候选，再由模型选定 1 个核心项目。"
        return selected_index, reason
    except Exception:
        return 0, f"先筛出 {len(candidate_items)} 个候选，再按当前排序取第 1 个核心项目。"


def _parse_bilingual_json(raw_text: str) -> dict | None:
    """Extract bilingual fields JSON from LLM output.

    Handles markdown code fences and extra text around the JSON block.
    Returns None if parsing fails or required keys are missing.
    """
    import json as _json

    text = (raw_text or "").strip()
    if not text:
        return None

    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    else:
        obj_start = text.find("{")
        obj_end = text.rfind("}")
        if obj_start == -1 or obj_end == -1 or obj_start >= obj_end:
            return None
        text = text[obj_start:obj_end + 1]

    try:
        data = _json.loads(text)
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    required_fields = ("名称", "类别", "简介", "主要特色")
    fields = data.get("fields")
    if not isinstance(fields, dict):
        return None
    if not all(key in fields for key in required_fields):
        return None
    normalized_fields: dict[str, dict[str, str]] = {}
    for key in required_fields:
        normalized = _coerce_bilingual_field(fields.get(key))
        if normalized is None:
            return None
        normalized_fields[key] = normalized

    data["fields"] = normalized_fields
    if "speech_en" in data and not isinstance(data.get("speech_en"), str):
        return None
    return data


def _coerce_bilingual_field(value: Any) -> dict[str, str] | None:
    if isinstance(value, dict):
        zh = str(value.get("zh") or "").strip()
        en = str(value.get("en") or "").strip()
        if zh and en:
            return {"zh": zh, "en": en}
        return None
    return None


def _build_transform_local(transform_type: str, target_item, meta) -> str:
    """Build a template-based local answer for content transformation."""
    title = _title_with_family(target_item)
    category = target_item.category
    summary = target_item.summary
    features = meta.features if meta and meta.features else summary
    level = meta.level if meta else ""

    return _render_template(
        "transform_local.md.j2",
        transform_type=transform_type,
        title=title,
        category=category,
        summary=summary,
        features=features,
        level=level,
    ).strip()
