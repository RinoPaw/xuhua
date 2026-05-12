"""Model-based intent planner for the heritage agent."""

from __future__ import annotations

import json
from typing import Any

from .. import config
from ..agent_models import AgentDecision, TaskType, task_type_from_str
from ..dataset import KnowledgeBase, normalize_text


def call_agent_planner_model(
    query: str, kb: KnowledgeBase, category: str = '', context: dict | None = None,
) -> AgentDecision:
    if not config.AI_AGENT_PLANNER:
        raise RuntimeError('AI_AGENT_PLANNER is disabled')
    if not config.AI_API_KEY:
        raise RuntimeError('AI_API_KEY is not configured')
    from ..http_client import chat_completion

    content = chat_completion(
        build_agent_planner_messages(query, kb, category, context),
        temperature=0,
        extra_options=agent_planner_extra_options(),
    )
    plan = json.loads(extract_json_object(content))
    return decision_from_planner_payload(plan, query, kb, category)


def build_agent_planner_messages(
    query: str, kb: KnowledgeBase, category: str = '', context: dict | None = None,
) -> list[dict[str, str]]:
    categories = '、'.join(category.name for category in kb.categories[:12])
    user_content = (
        f'用户问题：{query}\n'
        f'显式分类筛选：{category or '无'}\n'
        f'资料库概况：{len(kb.items)} 个非遗项目，{len(kb.categories)} 类，类别包括：{categories}\n'
    )
    if context and isinstance(context, dict):
        prev_question = str(context.get('question') or '').strip()
        prev_items = _context_item_titles(context.get('items'))
        prev_answer = str(context.get('answer') or '').strip()
        if prev_question or prev_items:
            user_content += '\n上一轮对话上下文：\n'
            if prev_question:
                user_content += f'上一轮用户问题：{prev_question}\n'
            if prev_items:
                user_content += f"上一轮涉及项目：{'、'.join(prev_items)}\n"
            user_content += "请根据上下文理解本轮问题中的指代（如「它」「这个」「这份」），"
            user_content += '将其解析为具体项目名，并在 reason 中说明你的理解。\n'
            if prev_answer:
                prev_answer_short = prev_answer[:300]
                user_content += f'上一轮回答概要（仅供参考，请勿在 direct_answer 中复述）：{prev_answer_short}\n'
    user_content += (
        "\n请输出 JSON："
        '{"task_type":"...", "confidence":0.0, "needs_retrieval":true, '
        '"needs_llm":true, "reason":"...", "direct_answer":"", '
        '"mode":"local", "warnings":[]}'
    )
    return [
        {
            'role': 'system',
            'content': (
                '你是叙华智能体的内部规划器，用户不可见，不直接编造资料。'
                '你的任务只是在后台决定下一步行动，不是扮演最终回答者。'
                '可选任务类型：chitchat, fact_qa, browse_query, comparison, recommendation, '
                'exhibition_plan, study_task, content_transform。'
                '可选动作：direct_answer（身份/能力/寒暄/越界说明）、retrieval_tool（查资料库）、'
                'rule_handler（筛选/对比/推荐/策划/教案）、llm_generation（基于检索资料生成）。'
                '任务边界：content_transform 用于把一个或多个非遗项目资料改写成讲解词、解说词、'
                '口播稿、传播文案、双语文案、年轻化版本、文创/纹样/包装/IP创意等成稿内容；'
                'study_task 用于课程、教案、研学任务、学习单、课堂活动、教学问题等教学设计；'
                'exhibition_plan 用于展览策划、展陈方案、展区动线、互动环节、物料配置等展示方案。'
                '如果用户要求为单个项目生成讲解词或解说词，优先选择 content_transform，'
                "不要因为出现「讲解」就归为 study_task，也不要因为用于展馆就归为 exhibition_plan。"
                "如果有上一轮对话上下文，你必须理解其中的指代关系，"
                "例如「它」指代上一轮的项目、要把「它和同类对比」理解为「项目A和同类对比」。"
                '请根据用户最终意图自主选择最合适的任务类型和动作。'
                'direct_answer 必须使用用户可见角色「叙华」的口吻回答。'
                '不要在 direct_answer 中提到内部规划器、后台、决策层、路由、JSON、工具选择等实现细节。'
                '只输出 JSON，不要输出 markdown，不要解释。'
            ),
        },
        {'role': 'user', 'content': user_content},
    ]


def _context_item_titles(items) -> list[str]:
    if not isinstance(items, list):
        return []
    titles: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get('title') or '').strip()
        if title and title not in titles:
            titles.append(title)
        if len(titles) >= 5:
            break
    return titles


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
