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
    get_ai_fields,
    get_structured_meta,
    KnowledgeBase,
    normalize_text,
)
from ..item_cards import _enriched_item_card, _source_payload, _title_with_family
from ..scenario_evidence import scenario_is_hard_match, scenario_match_score
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
MAX_SEARCH_ROUNDS_PER_TURN = 2
INITIAL_TITLE_CANDIDATE_LIMIT = 100
INITIAL_TITLE_CONTEXT_LIMIT = 100
DETAIL_SEARCH_LIMIT_PER_QUERY = 8
INITIAL_HIGH_RELEVANCE_MIN_SCORE = 35.0
INITIAL_HIGH_RELEVANCE_TOP_RATIO = 0.55

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

    # -- first-turn RAG --------------------------------------------------

    def _dispatch_first_turn(
        self, query: str, category: str, include_speech: bool,
    ):
        yield from self._dispatch_subsequent_turn(
            query,
            category,
            include_speech,
            context=None,
        )

    # -- dispatch (subsequent turns) ------------------------------------

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
        """Generator: yields progress dicts, then AgentResult.

        Each turn uses the same model decision loop: answer from available
        context, or request another search.  The server caps each
        turn at two consecutive searches.
        """
        query = query.strip()
        if not query:
            yield AgentResult(
                task_type=TaskType.FACT_QA,
                answer="请先输入问题。",
                speech="请先输入问题。" if include_speech else "",
                mode="empty",
            )
            return

        # ── First turn: search-first RAG ──
        has_legacy_context = bool(context and (context.get("question") or context.get("items") or context.get("answer")))
        is_first = not context or (context.get("turn_count", 0) == 0 and not has_legacy_context)
        if is_first:
            yield from self._dispatch_first_turn(query, category, include_speech)
            return

        # ── Subsequent turns: same initial candidate search + LLM decision loop ──
        yield from self._dispatch_subsequent_turn(query, category, include_speech, context)

    def _dispatch_subsequent_turn(
        self,
        query: str,
        category: str,
        include_speech: bool,
        context: dict | None,
    ):
        """Use the answer model as the per-turn search/answer decider."""
        from ..ai import describe_model_error

        context = context or {}
        yield self._progress_event(
            "search", "检索资料",
            "按原问题筛选候选标题。",
        )
        title_candidates, initial_total_count, initial_note = self._search_initial_candidates(
            query,
            category,
            context,
        )
        search_rounds_used = 1
        used_queries: list[str] = [query]
        detailed_items: list[Any] = []
        collected_items: list[Any] = self._merge_items(title_candidates, detailed_items)
        total_count = initial_total_count
        retrieval_note = initial_note
        warnings: list[str] = []

        while True:
            if search_rounds_used >= MAX_SEARCH_ROUNDS_PER_TURN:
                yield self._progress_event("generate", "思考回答", "资料已齐，正在生成回答。")
            else:
                yield self._progress_event(
                    "classify",
                    "理解问题",
                    "结合上下文和候选标题，判断是否需要精查。",
                )

            try:
                payload = self._call_subsequent_turn_model(
                    query=query,
                    context=context,
                    title_candidates=title_candidates,
                    detailed_items=detailed_items,
                    search_rounds_used=search_rounds_used,
                    retrieval_note=retrieval_note,
                )
            except Exception as exc:  # noqa: BLE001 - model failures degrade to a user-facing answer.
                warning = describe_model_error(exc)
                LOGGER.warning("Subsequent-turn LLM decision unavailable: %s", warning)
                warnings.append(warning)
                result, decision = self._subsequent_fallback_result(
                    query=query,
                    context=context,
                    collected_items=collected_items,
                    used_queries=used_queries,
                    total_count=total_count,
                    warnings=warnings,
                )
                yield from self._stream_completed_result(result, decision, include_speech, query=query)
                return

            action = self._payload_action(payload)
            answer = _normalize_answer_text(payload.get("answer") or "")
            search_queries = self._payload_str_list(payload.get("search_queries"))

            if action == "answer" and answer:
                yield self._progress_event("generate", "思考回答", "资料已齐，正在生成回答。")
                result, decision = self._subsequent_answer_result(
                    payload=payload,
                    answer=answer,
                    context=context,
                    collected_items=collected_items,
                    used_queries=used_queries,
                    total_count=total_count,
                    warnings=warnings,
                )
                yield from self._stream_completed_result(result, decision, include_speech, query=query)
                return

            if search_rounds_used >= MAX_SEARCH_ROUNDS_PER_TURN:
                warnings.append("搜索预算已用尽，已基于现有上下文兜底回答。")
                result, decision = self._subsequent_fallback_result(
                    query=query,
                    context=context,
                    collected_items=collected_items,
                    used_queries=used_queries,
                    total_count=total_count,
                    warnings=warnings,
                )
                yield from self._stream_completed_result(result, decision, include_speech, query=query)
                return

            if not search_queries:
                search_queries = self._fallback_queries_from_context(context)

            if not search_queries:
                warnings.append("模型未给出答案或检索词，且上下文中没有可兜底检索的项目。")
                result, decision = self._subsequent_fallback_result(
                    query=query,
                    context=context,
                    collected_items=collected_items,
                    used_queries=used_queries,
                    total_count=total_count,
                    warnings=warnings,
                )
                yield from self._stream_completed_result(result, decision, include_speech, query=query)
                return

            search_rounds_used += 1
            used_queries.extend(q for q in search_queries if q not in used_queries)
            yield self._progress_event(
                "search",
                "检索资料",
                "精查资料："
                f"{'、'.join(search_queries[:4])}",
            )
            new_items, total = self._search_subsequent_items(search_queries, category)
            total_count += total
            if total == 0:
                warnings.append(f"检索词未命中资料库：{'、'.join(search_queries)}")
            detailed_items = self._merge_items(detailed_items, new_items)
            collected_items = self._merge_items(title_candidates, detailed_items)
            retrieval_note = (
                f"服务器已根据模型查询词补充详情检索：{'、'.join(search_queries)}。"
                if new_items
                else f"服务器根据模型查询词没有查询到高相关结果：{'、'.join(search_queries)}。"
            )

    def _call_subsequent_turn_model(
        self,
        query: str,
        context: dict,
        title_candidates: list[Any],
        detailed_items: list[Any],
        search_rounds_used: int,
        retrieval_note: str = "",
    ) -> dict[str, Any]:
        from ..http_client import chat_completion

        raw = chat_completion(
            self._build_subsequent_turn_messages(
                query=query,
                context=context,
                title_candidates=title_candidates,
                detailed_items=detailed_items,
                search_rounds_used=search_rounds_used,
                retrieval_note=retrieval_note,
            ),
            temperature=0.2,
            max_tokens=2200,
            extra_options=agent_planner_extra_options(),
        )
        payload = json.loads(extract_json_object(raw))
        if not isinstance(payload, dict):
            raise ValueError("Subsequent-turn model did not return a JSON object")
        return payload

    def _build_subsequent_turn_messages(
        self,
        query: str,
        context: dict,
        title_candidates: list[Any],
        detailed_items: list[Any],
        search_rounds_used: int,
        retrieval_note: str = "",
    ) -> list[dict[str, str]]:
        remaining = max(MAX_SEARCH_ROUNDS_PER_TURN - search_rounds_used, 0)
        history_text = self._format_history_for_llm(context)
        title_text = (
            _items_to_title_context(title_candidates[:INITIAL_TITLE_CONTEXT_LIMIT], len(title_candidates))
            if title_candidates else "无"
        )
        detail_text = (
            _items_to_llm_context(detailed_items[:30], len(detailed_items))
            if detailed_items else "无"
        )

        system_prompt = (
            "你是叙华非遗助手。你能看到最近五轮对话历史，也能看到本轮服务器已经检索到的候选资料。\n"
            "本轮采用两段式检索：第 1 轮服务器会按原问题提供较多候选标题和基础元数据；"
            "第 2 轮由你决定是否用 search_queries 精查若干项目或主题的详细资料。\n"
            "每一轮你必须先决定：直接回答，还是请求服务器继续检索资料库。"
            "请你根据对话历史自行判断当前问题是否在承接上一轮；如果是，就优先沿用历史中的项目、类别和回答目标；"
            "如果不是，就忽略历史候选，按当前问题处理。\n"
            "如果历史资料或详情资料足够回答，就输出 action=\"answer\" 并填写 answer。\n"
            "如果只有标题候选，还需要事实依据、推荐理由、讲解词、对比细节或正文信息，且 search_rounds_remaining 大于 0，"
            "输出 action=\"search\"，在 search_queries 中给出一个列表；列表中的每一项都是一个可直接检索资料库的中文查询字符串，服务器会逐项执行。\n"
            "search_queries 可包含项目标题、同义标题、类别+地区+场景等组合，建议 1-6 项，最多 8 项。"
            "本轮最多允许 2 次连续搜索，服务器已经执行过的标题候选检索也会计入 search_rounds_used。"
            "search_rounds_remaining 为 0 时，必须输出 action=\"answer\"；如果仍不确定，要说明不确定点，不能继续请求搜索。\n"
            "display_items 由你决定：只选择答案真正围绕、用户需要看到的项目；单项目问题通常只选 1 个；推荐、列表、对比才选择多个，最多 8 个；不需要展示卡片时输出空列表。\n"
            "answer 字符串就是前端直接渲染的 Markdown 成稿，后端不会替你修复格式。"
            "你必须在 JSON 字符串中保留换行符，不要把 Markdown 压成一行。"
            "除寒暄外，回答必须多段排版：标题/小标题独占一行，标题前后空一行，列表逐项换行。"
            "编号列表只能用 `1. `、`2. `、`3. `；项目符号只能用 `- `；禁止把多个编号或多个 `-` 写在同一行。"
            "资料型、策划型、研学型、内容转化型回答要给到可直接使用的完整内容，通常 500-1200 中文字；只有事实短问才可以控制在 250-500 字。\n"
            "study_task 必须使用以下骨架，不能省略换行：\n"
            "## 研学任务：标题\n\n"
            "**适用对象：**对象\n\n"
            "**课时安排：**时长\n\n"
            "### 任务目标\n\n"
            "1. 目标一\n"
            "2. 目标二\n"
            "3. 目标三\n\n"
            "### 活动步骤\n\n"
            "1. 步骤一\n"
            "- 具体活动\n"
            "- 观察或讨论问题\n\n"
            "2. 步骤二\n"
            "- 具体活动\n\n"
            "### 注意事项\n\n"
            "- 安全或组织提醒\n"
            "- 资料依据边界\n\n"
            "当 task_type=\"recommendation\" 或用户要求推荐项目时，answer 必须使用 Markdown 表格；"
            "推荐表至少包含“项目、地区、可互动/展示形式、推荐理由、注意事项”列。"
            "每个推荐项目必须能从资料中的展示形式、适合场景或正文找到支撑；"
            "粗标签“研学体验”只能说明有学习体验潜力，不等同于适合亲子互动。"
            "如果用户明确说“亲子”，优先选择低门槛、可动手、可观看、可带走成果或适合儿童共同参与的项目；"
            "不要仅因“研学体验”就推荐烧制、茶制作、武术训练、医药等项目。"
            "除非资料明确提供相应活动，不要编写“可上釉、可烧制、可采茶、可练功”等互动环节。\n"
            "当 task_type=\"comparison\" 或用户要求比较多个项目时，answer 必须使用 Markdown 表格；"
            "至少包含“项目、地区/流派、制作/表演特点、题材/剧目或用途、适合展示的差异点”等列。"
            "表格必须是真正的多行 Markdown：表头、分隔行、每个项目的数据行都必须单独换行；在 JSON 的 answer 字符串中用换行符保留这些行。"
            "禁止输出单行表格，例如“| 项目 | ... | | --- | ... | | A | ... |”。"
            "正确格式示例：\n"
            "| 项目 | 地区/流派 | 特点 |\n"
            "| --- | --- | --- |\n"
            "| A | 地区 | 特点 |\n"
            "| B | 地区 | 特点 |\n"
            "表格后可加一小段结论，但不要把多个项目压成同一段编号文字。\n"
            "当用户要求中英双语、双语介绍等内容转化时，仍然只输出外层 JSON，"
            "但 answer 字符串里必须填写多行 Markdown 横读双语表格。"
            "answer 格式：一段中文导语，然后空一行，然后表格；表格第一行是中文完整介绍，第二行是英文完整介绍：\n"
            "| 语言 | 名称 | 类别 | 简介 | 主要特色 |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| 中文 | 规范中文名 | 规范中文类别 | 中文简介 | 中文特色 |\n"
            "| English | English name | English category | English summary | English key features |\n"
            "表格后不加结论文字。不要做成“中文列 / English列”的上下阅读表；不要把表格行拆散，也不要把所有行挤在同一行。\n"
            "输出前自检：如果 answer 中包含 `| --- |`，它前后必须有真实换行；如果包含 `1.` 和 `2.`，它们不能在同一行。\n"
            "不要编造资料库没有提供的事实；不要在没有资料支撑时凭常识列项目。"
            "如果没有可用资料且搜索预算已用尽，请明确说明资料不足，而不是给无依据推荐。"
            "只输出 JSON，不要输出 Markdown 或解释文字。\n"
            "JSON 格式："
            "{\"action\":\"answer|search\","
            "\"task_type\":\"chitchat|fact_qa|browse_query|comparison|recommendation|"
            "exhibition_plan|study_task|content_transform\","
            "\"confidence\":0.0,\"reason\":\"一句内部理由\","
            "\"search_queries\":[\"关键词\"]或null,"
            "\"answer\":\"回答文本\"或null,"
            "\"display_items\":[\"item_id\"]}"
        )
        user_prompt = (
            f"搜索状态：已连续搜索 {search_rounds_used} 轮，剩余 {remaining} 轮。\n\n"
            f"对话历史（最多最近五轮）：\n{history_text}\n\n"
            f"检索说明：{retrieval_note or '服务器尚未提供额外检索说明。'}\n\n"
            f"第1轮标题候选（仅含标题和基础元数据，不等同于完整事实依据）：\n{title_text}\n\n"
            f"第2轮详情资料（模型查询后由服务器补充）：\n{detail_text}\n\n"
            f"当前问题：{query}"
        )
        return [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

    def _format_history_for_llm(self, context: dict) -> str:
        history = context.get("history")
        if not isinstance(history, list) or not history:
            q = normalize_text(context.get("question") or "")
            a = normalize_text(context.get("answer") or "")
            items = context.get("items") or []
            lines = []
            if q:
                lines.append(f"上一轮问：{q}")
            if a:
                lines.append(f"上一轮答：{a[:300]}")
            if isinstance(items, list) and items:
                title_text = "、".join(
                    normalize_text(item.get("title") if isinstance(item, dict) else str(item))
                    for item in items[:8]
                )
                if title_text:
                    lines.append(f"上一轮涉及项目：{title_text}")
            return "\n".join(lines) if lines else "无"

        blocks: list[str] = []
        for idx, turn in enumerate(history[-5:], 1):
            if not isinstance(turn, dict):
                continue
            q = normalize_text(turn.get("q") or "")
            a = normalize_text(turn.get("a") or "")
            lines = [f"第{idx}轮"]
            if q:
                lines.append(f"问：{q}")
            if a:
                lines.append(f"答：{a[:300]}")

            items_full = turn.get("items_full") or []
            if isinstance(items_full, list) and items_full:
                lines.append("涉及项目：")
                for item in items_full[:8]:
                    item_text = self._format_context_item_for_llm(item)
                    if item_text:
                        lines.append(item_text)
            else:
                titles = turn.get("items") or []
                if isinstance(titles, list) and titles:
                    title_text = "、".join(str(title) for title in titles[:8] if str(title).strip())
                    if title_text:
                        lines.append(f"涉及项目：{title_text}")
            blocks.append("\n".join(lines))

        return "\n\n".join(blocks) if blocks else "无"

    def _format_context_item_for_llm(self, item: Any) -> str:
        if not isinstance(item, dict):
            return ""
        title = str(item.get("title") or "").strip()
        item_id = str(item.get("id") or "").strip()
        if not title and not item_id:
            return ""

        meta = " | ".join(
            part for part in [
                str(item.get("category") or "").strip(),
                str(item.get("level") or "").strip(),
                str(item.get("province") or "").strip(),
                str(item.get("city") or "").strip(),
                str(item.get("district") or "").strip(),
            ] if part
        )
        label = f"- [{item_id}] {title}" if item_id else f"- {title}"
        lines = [f"{label} | {meta}" if meta else label]
        for key, label_name in (
            ("summary", "简介"),
            ("features", "特色"),
            ("history", "历史"),
            ("cultural_value", "价值"),
            ("content", "正文摘要"),
        ):
            value = normalize_text(item.get(key) or "")
            if value:
                lines.append(f"  {label_name}：{value[:240]}")
        forms = item.get("display_forms")
        if isinstance(forms, list) and forms:
            lines.append(f"  展示形式：{'、'.join(str(form) for form in forms[:6])}")
        return "\n".join(lines)

    def _payload_action(self, payload: dict[str, Any]) -> str:
        action = str(payload.get("action") or "").strip().lower()
        if action in {"answer", "search"}:
            return action
        if self._payload_str_list(payload.get("search_queries")):
            return "search"
        return "answer"

    def _payload_str_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        result: list[str] = []
        for item in value:
            text = normalize_text(str(item))
            if text and text not in result:
                result.append(text)
        return result

    def _fallback_queries_from_context(self, context: dict) -> list[str]:
        queries: list[str] = []
        for item in self._context_item_payloads(context):
            title = normalize_text(item.get("title") or "")
            if title and title not in queries:
                queries.append(title)
            category = normalize_text(item.get("category") or "")
            if category and category not in queries:
                queries.append(category)
            if len(queries) >= 4:
                break
        if queries:
            return queries

        for item in context.get("items") or []:
            if not isinstance(item, dict):
                continue
            title = normalize_text(item.get("title") or "")
            if title and title not in queries:
                queries.append(title)
            if len(queries) >= 4:
                break
        return queries

    def _context_item_payloads(self, context: dict) -> list[dict]:
        payloads: list[dict] = []
        seen: set[str] = set()
        for item in context.get("items_full") or []:
            if isinstance(item, dict):
                key = str(item.get("id") or item.get("title") or "").strip()
                if key and key not in seen:
                    seen.add(key)
                    payloads.append(item)
        history = context.get("history")
        if isinstance(history, list):
            for turn in history[-5:]:
                if not isinstance(turn, dict):
                    continue
                for item in turn.get("items_full") or []:
                    if not isinstance(item, dict):
                        continue
                    key = str(item.get("id") or item.get("title") or "").strip()
                    if key and key not in seen:
                        seen.add(key)
                        payloads.append(item)
        return payloads

    def _context_items(self, context: dict) -> list[Any]:
        items: list[Any] = []
        seen: set[str] = set()
        for payload in self._context_item_payloads(context):
            item = self._resolve_context_item(payload)
            if item is None or item.id in seen:
                continue
            seen.add(item.id)
            items.append(item)
        return items

    def _resolve_context_item(self, payload: dict) -> Any | None:
        item_id = str(payload.get("id") or "").strip()
        if item_id:
            item = self.kb.get(item_id)
            if item is not None:
                return item

        title = normalize_text(payload.get("title") or "")
        if not title:
            return None
        for item in self.kb.items:
            if item.title == title or _title_with_family(item) == title:
                return item
        return None

    def _search_initial_candidates(
        self,
        query: str,
        category: str,
        context: dict | None = None,
    ) -> tuple[list[Any], int, str]:
        from ..search import LEXICAL_MIN_SCORE, normalize_search_query, rank_lexical, tokenize

        search_query = normalize_search_query(query)
        lowered_query = search_query or normalize_text(query).lower()
        context_items = self._context_items(context or {})
        contextual_items = self._contextual_initial_candidates(context_items, category)
        if not lowered_query:
            if contextual_items:
                return contextual_items, len(contextual_items), self._contextual_candidate_note(contextual_items)
            return [], 0, "服务器根据原问题没有查询到候选标题；你可以直接回答或组织关键词重新查询。"

        candidates = [
            item for item in self.kb.items
            if not category or item.category == category
        ]
        structured_items = self._structured_initial_candidates(query, limit=INITIAL_TITLE_CANDIDATE_LIMIT)
        ranked = rank_lexical(candidates, lowered_query, tokenize(search_query))
        scenario = self._query_scenario(query)
        lexical_items = [
            item for score, item in ranked
            if score >= LEXICAL_MIN_SCORE
            and (not scenario or scenario_is_hard_match(item, scenario))
        ][:INITIAL_TITLE_CANDIDATE_LIMIT]

        title_candidates = self._merge_items(
            contextual_items,
            self._merge_items(structured_items, lexical_items),
        )[:INITIAL_TITLE_CANDIDATE_LIMIT]
        if not title_candidates:
            return [], 0, (
                "服务器根据原问题没有查询到候选标题；"
                "如果历史上下文不足，你可以发送 search_queries 重新组织关键词查询。"
            )

        note_prefix = (
            "服务器已附带历史项目相关候选，是否采用由你根据对话判断；"
            if contextual_items else ""
        )
        note = (
            note_prefix +
            f"服务器已完成第 1 轮标题候选检索，提供 {len(title_candidates)} 个候选项目的标题和基础元数据；"
            "这些候选用于判断下一步，不包含完整事实依据。"
            "如果需要生成推荐理由、讲解词、对比或其他需要细节支撑的回答，"
            "请输出 action=\"search\"，并在 search_queries 列表中给出要精查的项目标题或主题；"
            "本轮最多只能连续查询两次。"
        )
        return title_candidates, len(title_candidates), note

    def _contextual_initial_candidates(self, context_items: list[Any], category: str) -> list[Any]:
        if not context_items:
            return []

        categories = {item.category for item in context_items if item.category}
        if category:
            categories.add(category)
        title_keywords = _context_title_keywords(context_items)
        context_ids = {item.id for item in context_items}
        forms = {form for item in context_items for form in item.display_forms}
        scenarios = {scenario for item in context_items for scenario in item.suitable_scenarios}

        scored: list[tuple[int, str, Any]] = []
        for item in self.kb.items:
            score = 0
            if item.id in context_ids:
                score += 12
            if categories and item.category in categories:
                score += 6
            if any(keyword and (keyword in item.title or keyword in item.family) for keyword in title_keywords):
                score += 10
            if forms and any(form in forms for form in item.display_forms):
                score += 2
            if scenarios and any(scenario in scenarios for scenario in item.suitable_scenarios):
                score += 1
            if item.level == "人类":
                score += 3
            elif item.level == "国家级":
                score += 2
            if score <= 0:
                continue
            scored.append((score, item.title, item))

        scored.sort(key=lambda row: (-row[0], row[1]))
        return [item for _, _, item in scored[:INITIAL_TITLE_CANDIDATE_LIMIT]]

    def _contextual_candidate_note(self, items: list[Any]) -> str:
        return (
            f"服务器根据历史项目附带 {len(items)} 个相关候选标题；"
            "是否承接上一轮由你根据对话历史判断。如果需要新增项目详情，请在 search_queries 中给出项目标题。"
        )

    def _structured_initial_candidates(self, query: str, limit: int) -> list[Any]:
        province = self._query_province(query)
        scenario = self._query_scenario(query)
        wants_recommendation = bool(re.search(r"推荐|适合|哪些|有哪些|找|筛选|展示|活动|体验|互动|亲子", query))
        if not wants_recommendation or not (province or scenario):
            return []

        scored: list[tuple[int, str, Any]] = []
        for item in self.kb.items:
            if province and item.province != province:
                continue
            score = 0
            if scenario:
                scenario_score = scenario_match_score(item, scenario)
                if scenario_score < 4:
                    continue
                score += scenario_score
            if province:
                score += 8
            if "展示" in query and any("展示" in form or "讲解" in form for form in item.display_forms):
                score += 4
            if "活动" in query and any("活动" in form or "表演" in form for form in item.display_forms):
                score += 4
            if item.level == "人类":
                score += 4
            elif item.level == "国家级":
                score += 3
            elif item.level == "省级":
                score += 1
            if item.display_forms:
                score += min(len(item.display_forms), 3)
            if score <= 0:
                continue
            scored.append((score, item.title, item))

        scored.sort(key=lambda row: (-row[0], row[1]))
        return [item for _, _, item in scored[:limit]]

    def _query_province(self, query: str) -> str:
        short_map = {
            "河南": "河南省",
            "河北": "河北省",
            "山东": "山东省",
            "山西": "山西省",
            "陕西": "陕西省",
            "湖北": "湖北省",
            "湖南": "湖南省",
            "广东": "广东省",
            "广西": "广西壮族自治区",
            "江苏": "江苏省",
            "浙江": "浙江省",
            "福建": "福建省",
            "四川": "四川省",
            "云南": "云南省",
            "贵州": "贵州省",
            "甘肃": "甘肃省",
            "青海": "青海省",
            "辽宁": "辽宁省",
            "吉林": "吉林省",
            "黑龙江": "黑龙江省",
            "安徽": "安徽省",
            "江西": "江西省",
            "海南": "海南省",
            "台湾": "台湾省",
            "北京": "北京市",
            "天津": "天津市",
            "上海": "上海市",
            "重庆": "重庆市",
            "内蒙古": "内蒙古自治区",
            "西藏": "西藏自治区",
            "宁夏": "宁夏回族自治区",
            "新疆": "新疆维吾尔自治区",
        }
        for province in {item.province for item in self.kb.items if item.province}:
            if province and province in query:
                return province
        for short, province in short_map.items():
            if short in query:
                return province
        return ""

    def _query_scenario(self, query: str) -> str:
        if "亲子" in query:
            return "亲子互动"
        if "社区" in query:
            return "社区活动"
        if "校园" in query or "学校" in query or "学生" in query:
            return "校园展示"
        if "研学" in query or "课堂" in query:
            return "研学体验"
        if "文创" in query or "包装" in query or "设计" in query:
            return "文创设计"
        if "展馆" in query or "讲解" in query:
            return "展馆讲解"
        return ""

    def _search_subsequent_items(self, queries: list[str], category: str) -> tuple[list[Any], int]:
        from ..search import search_items

        items: list[Any] = []
        seen: set[str] = set()
        total = 0
        for search_query in queries[:6]:
            exact_items = self._exact_items_for_query(search_query, category)
            if exact_items:
                result = exact_items
                result_total = len(exact_items)
            else:
                result, result_total = search_items(
                    self.kb,
                    query=search_query,
                    category=category,
                    limit=DETAIL_SEARCH_LIMIT_PER_QUERY,
                )
            total += result_total
            for item in result:
                if item.id in seen:
                    continue
                seen.add(item.id)
                items.append(item)
        return items, total

    def _exact_items_for_query(self, query: str, category: str) -> list[Any]:
        ref = normalize_text(query)
        if not ref:
            return []

        matches: list[Any] = []
        seen: set[str] = set()
        for item in self.kb.items:
            if category and item.category != category:
                continue
            item_refs = {
                item.id,
                item.title,
                _title_with_family(item),
                item.family,
            }
            if ref not in item_refs or item.id in seen:
                continue
            seen.add(item.id)
            matches.append(item)
        return matches

    def _merge_items(self, existing: list[Any], incoming: list[Any]) -> list[Any]:
        merged = list(existing)
        seen = {item.id for item in merged if hasattr(item, "id")}
        for item in incoming:
            item_id = getattr(item, "id", "")
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            merged.append(item)
        return merged

    def _subsequent_answer_result(
        self,
        payload: dict[str, Any],
        answer: str,
        context: dict,
        collected_items: list[Any],
        used_queries: list[str],
        total_count: int,
        warnings: list[str],
    ) -> tuple[AgentResult, AgentDecision]:
        task_type = task_type_from_str(str(payload.get("task_type") or TaskType.FACT_QA.value))
        confidence = clamp_float(payload.get("confidence"), default=0.78)
        reason = normalize_text(payload.get("reason") or "模型根据最近五轮上下文完成回答。")
        display_pool = self._merge_items(self._context_items(context), collected_items)
        raw_display_items = payload.get("display_items")
        if isinstance(raw_display_items, list):
            display_refs = self._payload_str_list(raw_display_items)
            display_items = self._select_display_items(
                display_refs,
                display_pool,
                fallback_items=[],
            )
        else:
            display_items = self._select_display_items(
                [],
                display_pool,
                fallback_items=collected_items,
            )
        cards = [_enriched_item_card(item) for item in display_items[:8]]
        sources = [_source_payload(item) for item in display_items[:5]]

        decision = AgentDecision(
            task_type=task_type,
            confidence=confidence,
            needs_retrieval=bool(used_queries),
            needs_llm=True,
            reason=reason,
            mode="llm_context",
            warnings=list(warnings),
            planner="llm_decision",
            search_queries=list(used_queries),
        )
        result = AgentResult(
            task_type=task_type,
            answer=answer,
            items=cards,
            sources=sources,
            mode="llm_context",
            confidence=confidence,
            warnings=list(warnings),
            total_count=len(display_items),
        )
        return result, decision

    def _select_display_items(
        self,
        refs: list[str],
        pool: list[Any],
        fallback_items: list[Any],
    ) -> list[Any]:
        selected: list[Any] = []
        seen: set[str] = set()

        def add(item: Any) -> None:
            item_id = getattr(item, "id", "")
            if item_id and item_id not in seen:
                seen.add(item_id)
                selected.append(item)

        for ref in refs:
            for item in pool:
                if self._item_matches_ref(item, ref):
                    add(item)
                    break

        if not selected:
            for item in fallback_items[:8]:
                add(item)
        return selected

    def _item_matches_ref(self, item: Any, ref: str) -> bool:
        ref = normalize_text(ref)
        if not ref:
            return False
        return ref in {
            item.id,
            item.title,
            _title_with_family(item),
            item.family,
        }

    def _subsequent_fallback_result(
        self,
        query: str,
        context: dict,
        collected_items: list[Any],
        used_queries: list[str],
        total_count: int,
        warnings: list[str],
    ) -> tuple[AgentResult, AgentDecision]:
        display_items = collected_items[:5] or self._context_items(context)[:5]
        if display_items:
            lines = ["我先基于当前已有资料回答："]
            for item in display_items[:3]:
                loc = " · ".join(part for part in [item.province, item.city] if part)
                meta = " | ".join(part for part in [item.category, item.level, loc] if part)
                lines.append(f"- **{_title_with_family(item)}**：{meta}")
                if item.summary:
                    lines.append(f"  {item.summary[:140]}")
            if used_queries:
                lines.append(f"\n已尝试检索：{'、'.join(used_queries)}。")
            answer = "\n".join(lines)
        else:
            answer = (
                "这轮我没有拿到足够可靠的资料来回答。可以换成更具体的项目名、类别或地区再问一次。"
            )

        decision = AgentDecision(
            task_type=TaskType.FACT_QA,
            confidence=0.4,
            needs_retrieval=bool(used_queries),
            needs_llm=False,
            reason="后续轮模型未能给出可用 answer，服务器使用上下文兜底。",
            mode="llm_context_fallback",
            warnings=list(warnings),
            planner="llm_decision",
            search_queries=list(used_queries),
        )
        result = AgentResult(
            task_type=TaskType.FACT_QA,
            answer=answer,
            items=[_enriched_item_card(item) for item in display_items],
            sources=[_source_payload(item) for item in display_items[:5]],
            mode="llm_context_fallback",
            confidence=0.4,
            warnings=list(warnings),
            total_count=len(display_items),
        )
        return result, decision

    def _progress_event(self, step: str, title: str, detail: str) -> dict[str, str]:
        return {
            "type": "progress",
            "step": step,
            "title": title,
            "detail": detail,
        }

    def _stream_direct_answer(self, decision: AgentDecision, include_speech: bool):
        yield self._progress_event("search", "检索资料", "当前问题可直接回应，已跳过资料库检索。")
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
            # Strip markdown table artifacts from speech (pipes, bold markers)
            speech_text = _clean_speech_text(result.speech)
            yield {"type": "speech", "text": speech_text}

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
        from ..search import search_items

        target_item = None
        # Try to resolve a specific target entity
        if analysis.entities:
            entity = analysis.entities[0]
            result, _ = search_items(self.kb, query=entity, limit=1)
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

        ai = get_ai_fields(target_item.id)
        features = ai["features"][:200] if ai["features"] else summary
        history = ai["history"][:200] if ai["history"] else ""
        display = "、".join(target_item.display_forms) if target_item.display_forms else "展板 + 讲解"
        cultural_value = ai["cultural_value"][:200] if ai["cultural_value"] else ""

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
        from ..search import search_items
        from ..ai import Answer, answer_question

        # Resolve target entity
        target_item = None
        if analysis.entities:
            entity = analysis.entities[0]
            result, _ = search_items(self.kb, query=entity, limit=1)
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
        ai = get_ai_fields(target_item.id)
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
        if ai["features"]:
            context_lines.append(f"主要特色：{ai['features']}")
        if ai["history"]:
            context_lines.append(f"历史背景：{ai['history']}")
        if ai["cultural_value"]:
            context_lines.append(f"重要价值：{ai['cultural_value']}")
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

    def _handle_browse(self, analysis) -> AgentResult:
        """BROWSE_QUERY: structured filters + local listing, no LLM."""
        from ..search import search_items

        province = analysis.metadata_filters.get("province", "")
        level = analysis.metadata_filters.get("level", "")
        category = analysis.metadata_filters.get("category", "")

        limit = analysis.retrieval_count
        result, total = search_items(
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
        """RECOMMENDATION: LLM selects best items from candidate pool."""
        from ..search import search_items
        from ..http_client import chat_completion

        scenario = analysis.scenario
        audience = analysis.audience
        limit = min(analysis.retrieval_count or 5, 10)

        # Step 1: Search candidates using planner's queries
        query = analysis.rewritten_query or " ".join(analysis.entities)
        candidates, _ = search_items(self.kb, query=query, limit=30)

        # Deduplicate
        seen_ids: set[str] = set()
        unique: list[Any] = []
        for item in candidates:
            if item.id not in seen_ids:
                seen_ids.add(item.id)
                unique.append(item)

        if not unique:
            return AgentResult(
                task_type=TaskType.RECOMMENDATION,
                answer="未找到相关非遗项目，请尝试调整问题。",
                mode="local",
                confidence=0.3,
                warnings=["检索候选池为空"],
            )

        # Step 2: Build candidate summaries for LLM
        candidate_text = _candidate_summaries_for_llm(unique[:20], limit)

        # Step 3: Ask LLM to select the best ones
        scene_desc = f"场景：{scenario}" if scenario else ""
        audience_desc = f"受众：{audience}" if audience else ""
        try:
            response = chat_completion(
                [
                    {
                        "role": "system",
                        "content": (
                            "你是一个非遗推荐助手。用户要求推荐非遗项目，你要从候选池中选出最合适的项目。\n"
                            "选择原则：\n"
                            "1. 优先选择与用户指定项目同类别的项目\n"
                            "2. 优先选择同省份/地区的项目\n"
                            "3. 优先选择级别高的项目（国家级 > 省级）\n"
                            "4. 展示形式多样的优先\n"
                            "5. 避免重复选择同名项目（不同地区版本选一个即可）\n"
                            f"请选出恰好 {limit} 个项目，输出 JSON："
                            '{"selected": ["item_id_1", "item_id_2", ...], "reason": "选择理由"}\n'
                            "只输出 JSON，不要其他内容。"
                        ),
                    },
                    {
                        "role": "user",
                        "content": (
                            f"用户需求：{analysis.original_query}\n"
                            f"{scene_desc}{audience_desc}\n\n"
                            f"候选项目（共 {len(unique)} 个）：\n{candidate_text}\n\n"
                            f"请从中选出最好的 {limit} 个。"
                        ),
                    },
                ],
                temperature=0.3,
            )
            selected = _parse_llm_selection(response, limit)
        except Exception:
            # Fallback: top by level
            unique.sort(key=lambda x: (
                5 if x.level == "人类" else 3 if x.level == "国家级" else 1 if x.level == "省级" else 0
            ), reverse=True)
            selected = [item.id for item in unique[:limit]]

        # Step 4: Collect selected items
        top = [self.kb.get(item_id) for item_id in selected if self.kb.get(item_id)]
        if len(top) < limit:
            # Pad from candidates
            used = set(selected)
            for item in unique:
                if item.id not in used:
                    top.append(item)
                    used.add(item.id)
                    if len(top) >= limit:
                        break

        # Build answer
        parts: list[str] = []
        scene_desc = scenario or "通用"
        parts.append(f"为您推荐 {len(top)} 个适合「{scene_desc}」的非遗项目：\n")

        for i, item in enumerate(top, 1):
            parts.append(f"**{i}. {_title_with_family(item)}**")
            parts.append(f"  - 类别：{item.category} | 级别：{item.level}")
            if item.display_forms:
                parts.append(f"  - 展示形式：{'、'.join(item.display_forms)}")
            parts.append(f"  - 简介：{item.summary[:120]}")
            parts.append("")

        selection_reason = f"共推荐 {len(top)} 个项目，排序依据：模型智能选择"

        # Build per-item cards with reason tags
        cards = []
        for item in top:
            card = _enriched_item_card(item)
            card["reason_tags"] = _item_reason_tags(item, scenario)
            cards.append(card)

        evidence: list[dict[str, Any]] = []
        for item in top:
            evidence.append({
                "type": "inferred",
                "claim": "推荐排序",
                "basis": f"scenario={scenario}, level={item.level}",
                "item_id": item.id,
            })

        return AgentResult(
            task_type=TaskType.RECOMMENDATION,
            answer="\n".join(parts),
            items=cards,
            evidence=evidence,
            selection_reason=selection_reason,
            mode="local",
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


def _score_for_recommendation(item, constraints: list[str],
                              anchor_category: str = "", anchor_province: str = "") -> int:
    """Score an item for recommendation. Higher = better fit."""
    score = 0

    # Level bonus
    lvl = item.level
    if lvl == "人类":
        score += 5
    elif lvl == "国家级":
        score += 3
    elif lvl == "省级":
        score += 1

    # Display forms diversity bonus
    if item.display_forms:
        score += min(len(item.display_forms), 3)

    # Category proximity — same category as anchor gets big bonus
    if anchor_category and item.category == anchor_category:
        score += 4

    # Province proximity — same province as anchor
    if anchor_province and item.province == anchor_province:
        score += 2

    return score


def _item_reason_tags(item, scenario: str = "") -> list[str]:
    """Build per-item reason tags for recommendation cards."""
    tags = []

    # Level badge
    lvl = item.level
    if lvl == "人类":
        tags.append("🏛 人类非遗")
    elif lvl == "国家级":
        tags.append("🏅 国家级")
    elif lvl == "省级":
        tags.append("📌 省级")

    # Display forms
    if item.display_forms:
        forms = item.display_forms[:3]
        tags.append(f"📐 {'·'.join(forms)}")

    # Scenario match
    if scenario and scenario in item.suitable_scenarios:
        tags.append(f"🎯 {scenario}")

    return tags


def _build_selection_reason(scenario: str, audience: str, constraints: list[str], count: int) -> str:
    parts = [f"共推荐 {count} 个项目"]
    if scenario:
        parts.append(f"匹配场景「{scenario}」")
    if audience:
        parts.append(f"适合「{audience}」受众")
    parts.append("排序依据：非遗级别 + 展示形式多样性")
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


def _normalize_answer_text(value: Any) -> str:
    """Clean an answer while preserving intentional Markdown line breaks."""
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").replace("\u00a0", " ")
    lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.split("\n")]
    cleaned = "\n".join(lines).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def _clean_speech_text(text: str) -> str:
    """Strip markdown table syntax and artifacts from speech output."""
    import re
    text = re.sub(r'\|[-:\s|]+\|', '', text)  # separator row
    text = re.sub(r'\|\s*', '，', text)        # pipe → comma
    text = re.sub(r'\*\*([^*]+)\*\*', r'\1', text)  # bold
    text = re.sub(r'\*([^*]+)\*', r'\1', text)      # italic
    text = re.sub(r'_{2,}', '', text)
    text = re.sub(r'[，,]{2,}', '，', text)
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip(' ，。')


def _build_transform_local(transform_type: str, target_item, meta) -> str:
    """Build a template-based local answer for content transformation."""
    title = _title_with_family(target_item)
    category = target_item.category
    summary = target_item.summary
    ai = get_ai_fields(target_item.id)
    features = ai["features"] if ai["features"] else summary
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


def _candidate_summaries_for_llm(items, limit: int) -> str:
    """Build item summaries for LLM selection."""
    lines = []
    for item in items:
        forms = "、".join(item.display_forms) if item.display_forms else "无"
        location = " · ".join(p for p in [item.province, item.city] if p)
        lines.append(
            f"[{item.id}] {_title_with_family(item)} | "
            f"{item.category} | {item.level} | "
            f"{location} | 展示：{forms} | "
            f"{item.summary[:80]}"
        )
    return "\n".join(lines)


def _parse_llm_selection(response: str, limit: int) -> list[str]:
    """Parse LLM JSON selection output. Returns list of item IDs."""
    import json
    text = response.strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        payload = json.loads(text[start:end + 1])
        selected = payload.get("selected", [])
        if isinstance(selected, list):
            return [str(s) for s in selected[:limit] if s]
    return []


def _items_to_llm_context(items, total: int) -> str:
    """Format search results as compact context for the answer LLM."""
    lines = [f"从资料库中检索到 {total} 条相关非遗项目，以下是其中最相关的：\n"]
    for i, item in enumerate(items[:30], 1):
        loc = " · ".join(p for p in [item.province, item.city] if p)
        forms = "、".join(item.display_forms) if item.display_forms else ""
        scenarios = "、".join(item.suitable_scenarios) if item.suitable_scenarios else ""
        lines.append(
            f"{i}. [{item.id}] {_title_with_family(item)}\n"
            f"   类别：{item.category} | 级别：{item.level} | 地区：{loc}\n"
            f"   简介：{item.summary[:200]}"
        )
        if forms:
            lines.append(f"   展示形式：{forms}")
        if scenarios:
            lines.append(f"   适合场景：{scenarios}")
        # Include content snippet
        content_snippet = item.content[:300].replace("\n", " ")
        if content_snippet:
            lines.append(f"   正文：{content_snippet}")
        lines.append("")
    return "\n".join(lines)


def _items_to_title_context(items, total: int) -> str:
    """Format broad first-round candidates as title-only planning context."""
    lines = [f"第 1 轮候选标题共 {total} 项，以下为标题和基础元数据：\n"]
    for i, item in enumerate(items[:INITIAL_TITLE_CONTEXT_LIMIT], 1):
        loc = " · ".join(part for part in [item.province, item.city, item.district] if part)
        forms = "、".join(item.display_forms[:4]) if item.display_forms else ""
        scenarios = "、".join(item.suitable_scenarios[:4]) if item.suitable_scenarios else ""
        meta = " | ".join(part for part in [item.category, item.level, loc] if part)
        extra = "；".join(part for part in [f"展示：{forms}" if forms else "", f"场景：{scenarios}" if scenarios else ""] if part)
        suffix = f" | {extra}" if extra else ""
        lines.append(f"{i}. [{item.id}] {_title_with_family(item)} | {meta}{suffix}")
    return "\n".join(lines)


def _context_title_keywords(items: list[Any]) -> list[str]:
    keywords: list[str] = []
    suffixes = ("绣", "剪纸", "年画", "皮影", "泥塑", "木雕", "石雕", "瓷", "陶", "茶", "酒", "医药", "戏", "曲")
    for item in items:
        texts = [getattr(item, "family", ""), getattr(item, "title", "")]
        for text in texts:
            text = normalize_text(text)
            if not text:
                continue
            for suffix in suffixes:
                if suffix in text and suffix not in keywords:
                    keywords.append(suffix)
            if len(text) <= 4 and text not in keywords:
                keywords.append(text)
        if len(keywords) >= 6:
            break
    return keywords[:6]

