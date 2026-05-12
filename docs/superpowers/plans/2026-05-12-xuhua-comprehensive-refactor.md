# 叙华全面重构实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 agent.py (1039行) 和 ai.py (842行) 拆分为包；统一 HTTP 层为 httpx；消除 config 副作用；外置模板；前端 ES modules 拆分；补测试覆盖。

**Architecture:** 后端按职责拆分为 `agent/` (调度+路由+各 task handler)、`ai/` (LLM 调用+语音+上下文)、`http_client.py` (统一HTTP层) 三个核心模块；前端 `app.js` 拆为 `js/` 目录下的 9 个 ES module。

**Tech Stack:** Python 3.10+ / Flask / httpx / Jinja2 / pypinyin / Vanilla JS ES Modules

---

## 文件结构总览

**创建:**
- `src/heritage_explorer/agent/__init__.py`
- `src/heritage_explorer/agent/router.py`
- `src/heritage_explorer/agent/dispatcher.py`
- `src/heritage_explorer/agent/planner.py`
- `src/heritage_explorer/agent/query_utils.py`
- `src/heritage_explorer/agent/handlers/__init__.py`
- `src/heritage_explorer/agent/handlers/browse.py`
- `src/heritage_explorer/agent/handlers/comparison.py`
- `src/heritage_explorer/agent/handlers/recommend.py`
- `src/heritage_explorer/agent/handlers/exhibition.py`
- `src/heritage_explorer/agent/handlers/study.py`
- `src/heritage_explorer/agent/handlers/transform.py`
- `src/heritage_explorer/ai/__init__.py`
- `src/heritage_explorer/ai/client.py`
- `src/heritage_explorer/ai/qa.py`
- `src/heritage_explorer/ai/speech.py`
- `src/heritage_explorer/ai/context.py`
- `src/heritage_explorer/ai/prompts.py`
- `src/heritage_explorer/http_client.py`
- `templates/study_task.md.j2`
- `templates/exhibition_plan.md.j2`
- `templates/transform_local.md.j2`
- `static/js/main.js`
- `static/js/state.js`
- `static/js/consts.js`
- `static/js/speech.js`
- `static/js/human.js`
- `static/js/markdown.js`
- `static/js/search.js`
- `static/js/ask.js`
- `static/js/ui.js`
- `tests/test_search.py`
- `tests/test_embeddings.py`
- `tests/test_http_client.py`
- `tests/test_planner.py`

**修改:**
- `src/heritage_explorer/agent.py` → 兼容 shim，re-export from agent/ package
- `src/heritage_explorer/agent_comparison.py` → 删除
- `src/heritage_explorer/ai.py` → 兼容 shim
- `src/heritage_explorer/config.py` → 移除顶层 load_dotenv()，常量改为函数
- `src/heritage_explorer/web.py` → main() 中显式调用 load_dotenv()
- `src/heritage_explorer/search.py` → _PINYIN_INDEX 改用 lru_cache
- `src/heritage_explorer/embeddings.py` → EmbeddingClient 改用 http_client
- `templates/index.html` → script type="module"
- `static/app.js` → 浅封装，import main.js
- `requirements.txt` → 加 httpx
- `tests/conftest.py` → import 路径适配
- `tests/test_agent.py` → import 路径适配
- `tests/test_web.py` → import 路径适配 + 前端 JS 检查适配

---

### Task 1: 创建 agent/ 包结构 + __init__.py

**Files:**
- Create: `src/heritage_explorer/agent/__init__.py`
- Create: `src/heritage_explorer/agent/handlers/__init__.py`

- [ ] **Step 1: 创建 agent/__init__.py — 保持完全向后兼容的公开 API**

```python
"""Agent orchestration package for the heritage RAG system."""

from .agent_models import (  # noqa: F401 - re-export
    AgentDecision,
    AgentResult,
    TaskConfig,
    TaskResult,
    TaskType,
    task_type_from_str,
    task_type_label,
)
from .agent_task_config import TASK_CONFIGS, _TASK_CONFIGS  # noqa: F401
from .dispatcher import Agent  # noqa: F401
from .planner import (  # noqa: F401
    build_agent_planner_messages,
    call_agent_planner_model,
    decision_from_planner_payload,
    extract_json_object,
)
from .query_utils import (  # noqa: F401
    normalize_query_with_pinyin_anchor,
    replace_homophone_span,
)
from .router import IntentRouter  # noqa: F401

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
```

- [ ] **Step 2: 创建 agent/handlers/__init__.py**

```python
"""Task handler modules for the heritage agent."""
```

- [ ] **Step 3: 验证 agent 包可导入**

```powershell
cd D:\Projects\xuhua && .\.venv\Scripts\python.exe -c "from heritage_explorer.agent import Agent, IntentRouter, TaskType; print('OK')"
```

- [ ] **Step 4: 提交**

```powershell
git add src/heritage_explorer/agent/__init__.py src/heritage_explorer/agent/handlers/__init__.py
git commit -m "Create agent package structure with backward-compat exports"
```

---

### Task 2: 抽取 agent/planner.py

**Files:**
- Create: `src/heritage_explorer/agent/planner.py`
- Modify: `src/heritage_explorer/agent.py` — 删除对应的函数

- [ ] **Step 1: 从 agent.py 中提取 4 个 planner 函数到 agent/planner.py**

提取: `call_agent_planner_model`, `build_agent_planner_messages`, `agent_planner_extra_options`, `extract_json_object`, `decision_from_planner_payload`, `clamp_float`

```python
"""Model-based intent planner for the heritage agent."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .. import config
from ..agent_models import AgentDecision, TaskType, task_type_from_str
from ..dataset import KnowledgeBase, normalize_text


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
                "任务边界：content_transform 用于把一个或多个非遗项目资料改写成讲解词、解说词、"
                "口播稿、传播文案、双语文案、年轻化版本、文创/纹样/包装/IP创意等成稿内容；"
                "study_task 用于课程、教案、研学任务、学习单、课堂活动、教学问题等教学设计；"
                "exhibition_plan 用于展览策划、展陈方案、展区动线、互动环节、物料配置等展示方案。"
                "如果用户要求为单个项目生成讲解词或解说词，优先选择 content_transform，"
                "不要因为出现"讲解"就归为 study_task，也不要因为用于展馆就归为 exhibition_plan。"
                "请根据用户最终意图自主选择最合适的任务类型和动作。"
                "direct_answer 必须使用用户可见角色"叙华"的口吻回答。"
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
```

- [ ] **Step 2: 从 agent.py 中删除已移动的函数**

删除 `call_agent_planner_model`, `build_agent_planner_messages`, `agent_planner_extra_options`, `extract_json_object`, `decision_from_planner_payload`, `clamp_float`。

- [ ] **Step 3: 在 agent.py 顶部添加 import 以保持模块级兼容**

在 agent.py 中保留的现有 import 之外添加：
```python
from .planner import (
    call_agent_planner_model,
    build_agent_planner_messages,
    agent_planner_extra_options,
    extract_json_object,
    decision_from_planner_payload,
    clamp_float,
)
```

- [ ] **Step 4: 运行测试验证**

```powershell
python -m pytest tests/test_agent.py -q
```

- [ ] **Step 5: 提交**

```powershell
git add src/heritage_explorer/agent/planner.py src/heritage_explorer/agent.py
git commit -m "Extract planner functions from agent.py to agent/planner.py"
```

---

### Task 3: 抽取 agent/query_utils.py

**Files:**
- Create: `src/heritage_explorer/agent/query_utils.py`
- Modify: `src/heritage_explorer/agent.py` — 删除对应的函数

- [ ] **Step 1: 从 agent.py 提取 pinyin 辅助函数**

```python
"""Query normalization and homophone correction utilities."""

from __future__ import annotations

from ..dataset import KnowledgeBase, normalize_text


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
        from pypinyin import lazy_pinyin
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
```

- [ ] **Step 2: 从 agent.py 删除 `normalize_query_with_pinyin_anchor` 和 `replace_homophone_span`**

- [ ] **Step 3: 在 agent.py 添加 import**

```python
from .query_utils import normalize_query_with_pinyin_anchor, replace_homophone_span
```

- [ ] **Step 4: 运行测试**

```powershell
python -m pytest tests/test_agent.py -q
```

- [ ] **Step 5: 提交**

```powershell
git add src/heritage_explorer/agent/query_utils.py src/heritage_explorer/agent.py
git commit -m "Extract query utils from agent.py to agent/query_utils.py"
```

---

### Task 4: 抽取 agent/router.py

**Files:**
- Create: `src/heritage_explorer/agent/router.py`
- Modify: `src/heritage_explorer/agent.py` — 删除 IntentRouter 类

- [ ] **Step 1: 从 agent.py 提取 IntentRouter 类到 agent/router.py**

```python
"""Intent router for the heritage agent."""

from __future__ import annotations

from ..agent_models import AgentDecision
from ..dataset import KnowledgeBase
from .planner import call_agent_planner_model


class IntentRouter:
    """Plan user input with the model planner."""

    def decide(self, query: str, kb: KnowledgeBase, category: str = "") -> AgentDecision:
        return call_agent_planner_model(query, kb, category)

    def plan(self, query: str, kb: KnowledgeBase, category: str = "") -> AgentDecision:
        return self.decide(query, kb, category)

    def needs_retrieval(self, query: str, kb: KnowledgeBase, category: str = "") -> bool:
        return self.decide(query, kb, category).needs_retrieval
```

- [ ] **Step 2: 从 agent.py 删除 IntentRouter 类和 LOGGER 定义**

- [ ] **Step 3: 在 agent.py 添加 import**

```python
from .router import IntentRouter
```

- [ ] **Step 4: 运行测试**

```powershell
python -m pytest tests/test_agent.py -q
```

- [ ] **Step 5: 提交**

```powershell
git add src/heritage_explorer/agent/router.py src/heritage_explorer/agent.py
git commit -m "Extract IntentRouter from agent.py to agent/router.py"
```

---

### Task 5: 抽取 agent/handlers/ 各 handler 模块

**Files:**
- Create: `src/heritage_explorer/agent/handlers/browse.py`
- Create: `src/heritage_explorer/agent/handlers/comparison.py`
- Create: `src/heritage_explorer/agent/handlers/recommend.py`
- Create: `src/heritage_explorer/agent/handlers/exhibition.py`
- Create: `src/heritage_explorer/agent/handlers/study.py`
- Create: `src/heritage_explorer/agent/handlers/transform.py`
- Modify: `src/heritage_explorer/agent.py` — 删除handler方法
- Delete: `src/heritage_explorer/agent_comparison.py`

- [ ] **Step 1: 创建 handlers/browse.py**

从 agent.py 提取 `_handle_browse`, `_describe_filters` 函数。

```python
"""BROWSE_QUERY handler: structured filters + local listing."""

from __future__ import annotations

from typing import Any

from ...agent_models import AgentResult, TaskType
from ...item_cards import _enriched_item_card, _source_payload, _title_with_family
from ...search import search_items_lexical


def handle_browse(agent, analysis) -> AgentResult:
    province = analysis.metadata_filters.get("province", "")
    level = analysis.metadata_filters.get("level", "")
    category = analysis.metadata_filters.get("category", "")

    limit = analysis.retrieval_count
    result, total = search_items_lexical(
        agent.kb,
        query=analysis.rewritten_query,
        category=category,
        province=province,
        level=level,
        limit=limit,
    )

    items = [_enriched_item_card(item) for item in result]

    filter_desc = _describe_filters(category, province, level)
    header = f"找到 {total} 项{filter_desc}非遗：\n" if total else f"未找到匹配的{filter_desc}非遗。"
    lines = [header]
    for i, item in enumerate(result, 1):
        level_str = f" | {item.level}" if item.level else ""
        city_str = f" | {item.city}" if item.city else ""
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


def _describe_filters(category: str, province: str, level: str) -> str:
    parts: list[str] = []
    if province:
        parts.append(province)
    if level:
        parts.append(level)
    if category:
        parts.append(category)
    return "".join(parts) if parts else ""
```

- [ ] **Step 2: 创建 handlers/comparison.py**

将 `agent_comparison.py` 的全部内容复制到此文件。修改 import 路径：`from .agent_models` → `from ...agent_models`, `from .dataset` → `from ...dataset`, `from .search` → `from ...search`, `from .item_cards` → `from ...item_cards`, `from .retriever` → `from ...retriever`。

- [ ] **Step 3: 创建 handlers/recommend.py**

从 agent.py 提取 `_handle_recommend`, `_score_for_recommendation`, `_build_selection_reason`。

```python
"""RECOMMENDATION handler: SoftLabels matching + rule-based scoring."""

from __future__ import annotations

from typing import Any

from ...agent_models import AgentResult, TaskType
from ...item_cards import _enriched_item_card, _title_with_family


def handle_recommend(agent, analysis) -> AgentResult:
    scenario = analysis.scenario
    audience = analysis.audience
    constraints = analysis.constraints
    limit = analysis.retrieval_count

    scored: list[tuple[int, Any]] = []
    for item in agent.kb.items:
        if scenario and scenario not in item.suitable_scenarios:
            continue
        if audience and audience not in item.target_audience:
            continue
        score = _score_for_recommendation(item, constraints)
        scored.append((score, item))

    scored.sort(key=lambda x: -x[0])
    top = scored[:limit]

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


def _score_for_recommendation(item, constraints: list[str]) -> int:
    score = 0
    edu = item.education_value
    if edu == "高":
        score += 4
    elif edu == "中":
        score += 2

    inter = item.interaction_potential
    if inter == "高":
        score += 3
    elif inter == "中":
        score += 1

    lvl = item.level
    if lvl == "人类":
        score += 5
    elif lvl == "国家级":
        score += 3
    elif lvl == "省级":
        score += 1

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
```

- [ ] **Step 4: 创建 handlers/exhibition.py**

从 agent.py 提取 `_handle_exhibition`。

```python
"""EXHIBITION_PLAN handler: recommendation sub-pipeline + exhibition template."""

from __future__ import annotations

from ...agent_models import TaskType


def handle_exhibition(agent, analysis) -> "AgentResult":
    from ...agent_models import AgentResult

    if analysis.retrieval_count < 5:
        analysis.retrieval_count = 5

    rec = agent._handle_recommend(analysis)
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

    from ...item_cards import _title_with_family

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
```

- [ ] **Step 5: 创建 handlers/study.py**

从 agent.py 提取 `_handle_study_task`。此函数体量较大(~180行)，完整复制后修改 import 路径。

- [ ] **Step 6: 创建 handlers/transform.py**

从 agent.py 提取 `_handle_content_transform`, `_TRANSFORM_PROMPTS`, `_call_transform_model`, `_build_transform_local`。

- [ ] **Step 7: 更新 agent.py**

删除所有 handler 方法和辅助函数。在 Agent 类的 `_run_configured_handler` 中改为调用包内 handler：

```python
def _run_configured_handler(self, task_config, analysis):
    if not task_config.handler_name:
        raise ValueError(f"Task config for {task_config.task_type.value} does not declare a handler.")
    handler_module_name = task_config.handler_name
    # Map internal handler names to handler functions
    handler_map = {
        "_handle_browse": "browse",
        "_handle_comparison": "comparison",
        "_handle_recommend": "recommend",
        "_handle_exhibition": "exhibition",
        "_handle_study_task": "study",
        "_handle_content_transform": "transform",
    }
    module_name = handler_map.get(handler_module_name, handler_module_name)
    import importlib
    module = importlib.import_module(f".handlers.{module_name}", package="heritage_explorer.agent")
    handler_name = {
        "browse": "handle_browse",
        "comparison": "handle_comparison",
        "recommend": "handle_recommend",
        "exhibition": "handle_exhibition",
        "study": "handle_study",
        "transform": "handle_transform",
    }[module_name]
    return getattr(module, handler_name)(self, analysis)
```

- [ ] **Step 8: 删除 agent_comparison.py**

- [ ] **Step 9: 更新所有 import 引用**

- `web.py`: `from .agent import Agent` 保持不变（agent/__init__.py 会导出）
- `tests/conftest.py`: `from heritage_explorer.agent_models import ...` 保持不变
- `tests/test_agent.py`: 从 `heritage_explorer.agent` 导入，保持不变
- `tests/test_web.py`: 无需更改

- [ ] **Step 10: 运行全量测试**

```powershell
python -m pytest tests/ -q
```

- [ ] **Step 11: 提交**

```powershell
git add src/heritage_explorer/agent/handlers/ src/heritage_explorer/agent.py
git rm src/heritage_explorer/agent_comparison.py
git commit -m "Extract handler methods from agent.py to agent/handlers/ package"
```

---

### Task 6: 完善 agent/dispatcher.py

**Files:**
- Create: `src/heritage_explorer/agent/dispatcher.py`
- Modify: `src/heritage_explorer/agent.py` — 变为兼容 shim

- [ ] **Step 1: 将 Agent 类及其辅助方法移入 dispatcher.py**

提取: `Agent` 类 (含 `dispatch`, `dispatch_stream`, `_progress_event`, `_stream_direct_answer`, `_run_configured_handler`, `_build_fact_result`, `_stream_completed_result`, `_ensure_speech`, `_speech_source_items`, `with_agent_decision`)。

Agent 类从 handlers 导入 handler 函数，通过 `getattr(self, handler_name)` 调用。

- [ ] **Step 2: agent.py 改为纯 re-export shim**

```python
"""Backward-compatible shim for the heritage agent package."""

from .agent import *  # noqa: F401, F403 - re-export from agent/ package
```

实际上 `agent.py` 的位置是 `src/heritage_explorer/agent.py`，而 `agent/` 包是 `src/heritage_explorer/agent/`。由于 Python import 优先匹配模块文件(`agent.py`)而非包(`agent/`)，我们需要：

1. 重命名 `agent.py` → `agent_legacy.py`（或不提交）
2. 或者删除 agent.py，直接在 `agent/__init__.py` 中完成所有导出

更好的方案：**删除 agent.py，让 agent/ 包直接接替**。`from heritage_explorer.agent import Agent` 现在会导入 `heritage_explorer/agent/__init__.py` 中的 `Agent`。

```powershell
# 检查所有 import agent 的地方
rg "from \.agent import|from heritage_explorer.agent import" src/ tests/
```

`web.py` 现有: `from .agent import Agent, AgentResult, task_type_label`

这些名称已在 `agent/__init__.py` 中导出，所以删除 `agent.py` 后 import 路径不变。

- [ ] **Step 3: 删除 agent.py 文件**

- [ ] **Step 4: 运行全量测试验证**

```powershell
python -m pytest tests/ -q
```

- [ ] **Step 5: 提交**

```powershell
git rm src/heritage_explorer/agent.py
git add src/heritage_explorer/agent/dispatcher.py
git commit -m "Move Agent class to agent/dispatcher.py, remove legacy agent.py"
```

---

### Task 7: 创建 ai/ 包

**Files:**
- Create: `src/heritage_explorer/ai/__init__.py`
- Create: `src/heritage_explorer/ai/prompts.py`
- Create: `src/heritage_explorer/ai/client.py`
- Create: `src/heritage_explorer/ai/qa.py`
- Create: `src/heritage_explorer/ai/speech.py`
- Create: `src/heritage_explorer/ai/context.py`
- Delete: `src/heritage_explorer/ai.py`

- [ ] **Step 1: 创建 ai/__init__.py**

```python
"""AI question-answering and speech generation for the heritage knowledge base."""

from .client import call_chat_model  # noqa: F401
from .context import (  # noqa: F401
    build_context,
    clean_knowledge_text,
    extract_structured_field,
    item_context_text,
)
from .qa import (  # noqa: F401
    Answer,
    answer_question,
    build_local_answer,
    direct_item_matches,
    fact_question_sources,
    source_payload,
    summarize_snippet,
)
from .speech import (  # noqa: F401
    build_source_speech,
    build_spoken_answer,
    build_speech_text,
    clean_spoken_output,
    remove_speech_symbols,
)

__all__ = [
    "Answer",
    "answer_question",
    "build_context",
    "build_spoken_answer",
    "call_chat_model",
    "source_payload",
]
```

- [ ] **Step 2: 创建 ai/prompts.py**

从 ai.py 提取所有 system prompt 和结构化标签常量。

```python
"""System prompts and label constants for the AI module."""

import re

# Structured field labels used for content parsing
STRUCTURED_LABELS = (
    "序号", "标题", "归属", "类别", "城市", "地区", "报道地区",
    "介绍", "重大地区", "主要特色", "重要价值", "传承人", "企业",
    "展示形式", "联系", "电话", "省份", "地点", "面积",
    "operation", "经纬度", "历史", "主要时间", "内容", "省份ject",
)

_EMOJI_RE = re.compile(
    "["
    "\U0001F1E6-\U0001F1FF"
    "\U0001F300-\U0001FAFF"
    "☀-➿"
    "‍"
    "️"
    "]+"
)


def qa_system_prompt() -> str:
    return (
        "你是一个严谨的非物质文化遗产知识库助手。"
        "只能依据给定资料回答；资料不足时要直接说明。"
        "回答应使用中文，先用一句话概括，再用少量短段或短列表说明历史、技艺特点、代表作品、传承价值。"
        "不要照抄经纬度、电话、地址、面积、序号、销售额等后台管理字段，除非用户明确询问。"
        "不要用"基本信息"字段表作为开头。"
    )


def speech_system_prompt() -> str:
    return (
        "你是一个中文语音播报编辑。"
        ...  # 完整 prompt 见 ai.py:337-353
    )
```

- [ ] **Step 3: 创建 ai/client.py**

从 ai.py 提取模型调用函数:
`call_chat_model`, `call_model_with_messages`, `call_openai_compatible_model`, `call_openai_compatible_messages`, `call_zhipu_sdk`, `call_zhipu_messages`, `should_use_zhipu_sdk`, `zhipu_extra_options`, `call_speech_model`, `describe_model_error`, `sanitize_error`。

- [ ] **Step 4: 创建 ai/qa.py**

提取: `answer_question`, `build_local_answer`, `summarize_snippet`, `fact_question_sources`, `direct_item_matches`, `_dedupe_items`, `source_payload`, `build_messages`, `build_speech_messages`。

- [ ] **Step 5: 创建 ai/speech.py**

提取: `build_spoken_answer`, `build_speech_text`, `build_answer_speech`, `clean_spoken_output`, `remove_speech_symbols`, `speech_section_heading`, `speech_line`, `apply_section_intro`, `clean_speech_body`, `clean_representative_body`, `build_source_speech`, `spoken_sentences`, `is_admin_sentence`, `clean_spoken_source_text`。

- [ ] **Step 6: 创建 ai/context.py**

提取: `build_context`, `item_context_text`, `extract_structured_field`, `clean_knowledge_text`。

- [ ] **Step 7: 删除 ai.py**

- [ ] **Step 8: 更新导入引用**

检查所有 `from .ai import` 或 `from heritage_explorer.ai import` 的地方。主要调用方是 `agent/dispatcher.py` 和 `agent/handlers/transform.py`，它们从 `.ai import` 导入——现在指向 `ai/__init__.py`。

- [ ] **Step 9: 运行测试**

```powershell
python -m pytest tests/test_ai.py tests/test_agent.py -q
```

- [ ] **Step 10: 提交**

```powershell
git rm src/heritage_explorer/ai.py
git add src/heritage_explorer/ai/
git commit -m "Split ai.py into ai/ package: client, qa, speech, context, prompts"
```

---

### Task 8: 创建 http_client.py + 统一 HTTP 调用

**Files:**
- Create: `src/heritage_explorer/http_client.py`
- Modify: `src/heritage_explorer/requirements.txt`
- Modify: `src/heritage_explorer/ai/client.py`
- Modify: `src/heritage_explorer/agent/planner.py`
- Modify: `src/heritage_explorer/embeddings.py`

- [ ] **Step 1: 添加 httpx 依赖**

在 `requirements.txt` 中添加 `httpx>=0.28,<1`。

```powershell
.\.venv\Scripts\python.exe -m pip install httpx
```

- [ ] **Step 2: 创建 http_client.py**

```python
"""Unified HTTP client for all external API calls."""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from typing import Any

import httpx

from . import config

LOGGER = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30.0
DEFAULT_MAX_RETRIES = 1


@lru_cache(maxsize=1)
def get_http_client() -> httpx.Client:
    return httpx.Client(
        timeout=httpx.Timeout(DEFAULT_TIMEOUT),
        limits=httpx.Limits(max_keepalive_connections=5, max_connections=10),
    )


def chat_completion(
    messages: list[dict[str, str]],
    temperature: float = 0.2,
    max_tokens: int = 1000,
    extra_options: dict[str, Any] | None = None,
) -> str:
    """Send a chat completion request to the configured model API.

    Automatically routes through zhipuai SDK when the base URL points to bigmodel.cn,
    and through httpx for all other OpenAI-compatible endpoints.
    """
    if _should_use_zhipu_sdk():
        return _zhipu_completion(messages, temperature, max_tokens)

    payload: dict[str, Any] = {
        "model": config.AI_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if extra_options:
        payload.update(extra_options)

    client = get_http_client()
    url = config.AI_BASE_URL.rstrip("/") + "/chat/completions"
    headers = {
        "Authorization": f"Bearer {config.AI_API_KEY}",
        "Content-Type": "application/json",
    }

    try:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        body = response.json()
        return body["choices"][0]["message"]["content"].strip()
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Chat API HTTP {exc.response.status_code}: {_truncate_body(exc.response)}") from exc
    except httpx.RequestError as exc:
        raise RuntimeError(f"Chat API request failed: {exc}") from exc


def embedding_request(texts: list[str]) -> list[list[float]]:
    """Send an embedding request to the configured embedding API."""
    if not config.EMBEDDING_API_KEY:
        raise RuntimeError("EMBEDDING_API_KEY is not configured.")
    if not texts:
        return []

    client = get_http_client()
    url = config.EMBEDDING_BASE_URL.rstrip("/") + "/embeddings"
    headers = {
        "Authorization": f"Bearer {config.EMBEDDING_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {"model": config.EMBEDDING_MODEL, "input": texts}

    try:
        response = client.post(url, json=payload, headers=headers)
        response.raise_for_status()
        body = response.json()
        rows = sorted(body["data"], key=lambda row: int(row.get("index", 0)))
        return [list(map(float, row["embedding"])) for row in rows]
    except httpx.HTTPStatusError as exc:
        raise RuntimeError(f"Embedding API HTTP {exc.response.status_code}") from exc
    except httpx.RequestError as exc:
        raise RuntimeError(f"Embedding API request failed: {exc}") from exc


def describe_error(exc: Exception, api_key: str = "") -> str:
    import textwrap

    if isinstance(exc, httpx.HTTPStatusError):
        detail = f"HTTPError {exc.response.status_code}"
        body = _truncate_body(exc.response, max_chars=200)
        if body:
            detail += f": {body}"
    elif isinstance(exc, (httpx.RequestError, OSError)):
        detail = f"RequestError: {exc}"
    else:
        detail = str(exc) or type(exc).__name__

    text = _normalize_str(detail)
    if api_key:
        text = text.replace(api_key, "***")
    return textwrap.shorten(text, width=220, placeholder="...")


def _should_use_zhipu_sdk() -> bool:
    from urllib.parse import urlparse

    host = urlparse(config.AI_BASE_URL).hostname or ""
    return host.endswith("bigmodel.cn")


def _zhipu_completion(messages, temperature, max_tokens) -> str:
    from zhipuai import ZhipuAI

    model = config.AI_MODEL.lower()
    extra: dict[str, Any] = {}
    if any(name in model for name in ("glm-4.5", "glm-4.6", "glm-4.7", "glm-5")):
        extra["thinking"] = {"type": "disabled"}

    client = ZhipuAI(
        api_key=config.AI_API_KEY,
        base_url=config.AI_BASE_URL.rstrip("/"),
        timeout=int(config.AI_TIMEOUT),
        max_retries=0,
    )
    response = client.chat.completions.create(
        model=config.AI_MODEL,
        messages=messages,
        temperature=temperature,
        top_p=0.8,
        max_tokens=max_tokens,
        **extra,
        stream=False,
    )
    try:
        choice = response.choices[0]
        message = choice.message
    except (AttributeError, IndexError, TypeError) as exc:
        raise RuntimeError(f"Unexpected model response: {response}") from exc

    text = (getattr(message, "content", "") or "").strip()
    if text:
        return text

    finish_reason = getattr(choice, "finish_reason", "")
    reasoning = getattr(message, "reasoning_content", "")
    detail = "Empty model response"
    if finish_reason:
        detail += f"; finish_reason={finish_reason}"
    if reasoning:
        detail += "; reasoning_content was returned without final content"
    raise RuntimeError(detail)


def _truncate_body(response: httpx.Response, max_chars: int = 200) -> str:
    try:
        text = response.text
    except Exception:
        return ""
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "..."
    return text


def _normalize_str(value: str) -> str:
    import re

    return re.sub(r"\s+", " ", value).strip()
```

- [ ] **Step 3: 更新 ai/client.py 使用 http_client**

删除 `call_openai_compatible_model`, `call_openai_compatible_messages`, `call_zhipu_sdk`, `call_zhipu_messages`, `should_use_zhipu_sdk`, `zhipu_extra_options`, `describe_model_error`, `sanitize_error`。

替换 `call_model_with_messages`:
```python
def call_model_with_messages(messages, temperature=0.2, max_tokens=1000):
    from ..http_client import chat_completion
    return chat_completion(messages, temperature, max_tokens)

def call_chat_model(question, sources):
    from ..ai.prompts import qa_system_prompt
    messages = build_messages(question, sources)
    return call_model_with_messages(messages, temperature=0.2, max_tokens=1000)

def call_speech_model(answer, question="", sources=None, max_chars=1800):
    from ..ai.prompts import speech_system_prompt
    messages = build_speech_messages(answer, question=question, sources=sources or [], max_chars=max_chars)
    return call_model_with_messages(messages, temperature=0.1, max_tokens=max(900, min(2400, max_chars + 300)))

def describe_model_error(exc):
    from ..http_client import describe_error
    return describe_error(exc, config.AI_API_KEY)
```

- [ ] **Step 4: 更新 agent/planner.py 使用 http_client**

将 `call_agent_planner_model` 中的 `urllib.request` 改为 `http_client.chat_completion`。

- [ ] **Step 5: 更新 embeddings.py 使用 http_client**

`EmbeddingClient._embed_texts_once` 改为调用 `http_client.embedding_request`。

- [ ] **Step 6: 运行测试验证 HTTP 迁移**

```powershell
python -m pytest tests/test_ai.py tests/test_agent.py -q
```

- [ ] **Step 7: 提交**

```powershell
git add src/heritage_explorer/http_client.py requirements.txt
git add src/heritage_explorer/ai/client.py src/heritage_explorer/agent/planner.py src/heritage_explorer/embeddings.py
git commit -m "Add unified http_client.py with httpx, replace urllib across all modules"
```

---

### Task 9: 修 config 副作用

**Files:**
- Modify: `src/heritage_explorer/config.py`
- Modify: `src/heritage_explorer/web.py`

- [ ] **Step 1: 重构 config.py**

移除顶层 `load_dotenv()` 调用。将模块级常量改为通过函数访问（保持 `@lru_cache` 值缓存）。

```python
"""Application paths and environment-backed settings."""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def load_dotenv(path: Path | None = None) -> None:
    path = path or PROJECT_ROOT / ".env"
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip("'\"")
        if key and key not in os.environ:
            os.environ[key] = value


def _env_path(name: str, default: str) -> Path:
    value = os.getenv(name, default)
    path = Path(value)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


# ── Accessor functions (lazy, with lru_cache) ──

def _env_str(name: str, default: str) -> str:
    return os.getenv(name, default)

def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, str(default)))

def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, str(default)))

def _env_bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, "1" if default else "0") == "1"


@lru_cache(maxsize=1)
def _get_dataset_path() -> Path:
    return _env_path("DATASET_PATH", "data/processed/heritage_items.json")

@lru_cache(maxsize=1)
def _get_host() -> str:
    return _env_str("HOST", "127.0.0.1")

@lru_cache(maxsize=1)
def _get_port() -> int:
    return _env_int("PORT", 5050)

# ... (all other config values follow the same pattern)


# Module-level access via property-like getters for backward compatibility
# These are called on first access and cached via the underlying lru_cache functions

class _Config:
    @property
    def DATASET_PATH(self) -> Path:
        return _get_dataset_path()

    @property
    def HOST(self) -> str:
        return _get_host()

    @property
    def PORT(self) -> int:
        return _get_port()

    @property
    def DEBUG(self) -> bool:
        return _get_debug()

    @property
    def AI_API_KEY(self) -> str:
        return _get_ai_api_key()

    @property
    def AI_BASE_URL(self) -> str:
        return _get_ai_base_url()

    @property
    def AI_MODEL(self) -> str:
        return _get_ai_model()

    @property
    def AI_TIMEOUT(self) -> int:
        return _get_ai_timeout()

    @property
    def AI_MAX_CONTEXT_CHARS(self) -> int:
        return _get_ai_max_context_chars()

    @property
    def AI_AGENT_PLANNER(self) -> bool:
        return _get_ai_agent_planner()

    @property
    def EMBEDDING_API_KEY(self) -> str:
        return _get_embedding_api_key()

    @property
    def EMBEDDING_BASE_URL(self) -> str:
        return _get_embedding_base_url()

    @property
    def EMBEDDING_MODEL(self) -> str:
        return _get_embedding_model()

    @property
    def EMBEDDING_TIMEOUT(self) -> int:
        return _get_embedding_timeout()

    @property
    def EMBEDDING_BATCH_SIZE(self) -> int:
        return _get_embedding_batch_size()

    @property
    def EMBEDDING_WORKERS(self) -> int:
        return _get_embedding_workers()

    @property
    def EMBEDDING_REQUEST_TIMEOUT(self) -> float:
        return _get_embedding_request_timeout()

    @property
    def EMBEDDING_MAX_RETRIES(self) -> int:
        return _get_embedding_max_retries()

    @property
    def EMBEDDING_RETRY_BACKOFF(self) -> float:
        return _get_embedding_retry_backoff()

    @property
    def EMBEDDING_REQUEST_DELAY(self) -> float:
        return _get_embedding_request_delay()

    @property
    def EMBEDDING_INDEX_PATH(self) -> Path:
        return _get_embedding_index_path()

    @property
    def EMBEDDING_TEXT_MAX_CHARS(self) -> int:
        return _get_embedding_text_max_chars()

    @property
    def EMBEDDING_MIN_SCORE(self) -> float:
        return _get_embedding_min_score()

    @property
    def SEARCH_USE_EMBEDDING(self) -> bool:
        return _get_search_use_embedding()

    @property
    def VOLC_TTS_ENABLED(self) -> bool:
        return _get_volc_tts_enabled()

    @property
    def VOLC_TTS_API_VERSION(self) -> str:
        return _get_volc_tts_api_version()

    @property
    def VOLC_TTS_ENDPOINT(self) -> str:
        return _get_volc_tts_endpoint()

    @property
    def VOLC_TTS_V3_ENDPOINT(self) -> str:
        return _get_volc_tts_v3_endpoint()

    @property
    def VOLC_TTS_API_KEY(self) -> str:
        return _get_volc_tts_api_key()

    @property
    def VOLC_TTS_APP_ID(self) -> str:
        return _get_volc_tts_app_id()

    @property
    def VOLC_TTS_ACCESS_TOKEN(self) -> str:
        return _get_volc_tts_access_token()

    @property
    def VOLC_TTS_CLUSTER(self) -> str:
        return _get_volc_tts_cluster()

    @property
    def VOLC_TTS_RESOURCE_ID(self) -> str:
        return _get_volc_tts_resource_id()

    @property
    def VOLC_TTS_VOICE_TYPE(self) -> str:
        return _get_volc_tts_voice_type()

    @property
    def VOLC_TTS_EMOTION(self) -> str:
        return _get_volc_tts_emotion()

    @property
    def VOLC_TTS_EMOTION_SCALE(self) -> int:
        return _get_volc_tts_emotion_scale()

    @property
    def VOLC_TTS_ENCODING(self) -> str:
        return _get_volc_tts_encoding()

    @property
    def VOLC_TTS_RATE(self) -> int:
        return _get_volc_tts_rate()

    @property
    def VOLC_TTS_SPEED_RATIO(self) -> float:
        return _get_volc_tts_speed_ratio()

    @property
    def VOLC_TTS_VOLUME_RATIO(self) -> float:
        return _get_volc_tts_volume_ratio()

    @property
    def VOLC_TTS_PITCH_RATIO(self) -> float:
        return _get_volc_tts_pitch_ratio()

    @property
    def VOLC_TTS_TIMEOUT(self) -> float:
        return _get_volc_tts_timeout()

    @property
    def VOLC_TTS_MAX_CHUNK_BYTES(self) -> int:
        return _get_volc_tts_max_chunk_bytes()

    @property
    def TTS_CACHE_DIR(self) -> Path:
        return _get_tts_cache_dir()


# Replace the module with a _Config instance for backward compatibility
# This is a clean singleton that defers env reads to first access.
import sys as _sys
_config_instance = _Config()
# Set all properties as module-level attributes
for _attr in dir(_config_instance):
    if not _attr.startswith("_"):
        setattr(_sys.modules[__name__], _attr, getattr(_config_instance, _attr))
```

- [ ] **Step 2: 在 web.py:main() 中添加显式 load_dotenv() 调用**

```python
def main() -> None:
    from .config import load_dotenv
    load_dotenv()
    from .config import HOST, PORT, DEBUG
    create_app().run(host=HOST, port=PORT, debug=DEBUG)
```

- [ ] **Step 3: 运行全量测试确认无回归**

```powershell
python -m pytest tests/ -q
```

- [ ] **Step 4: 提交**

```powershell
git add src/heritage_explorer/config.py src/heritage_explorer/web.py
git commit -m "Remove config import-time side effects, defer dotenv loading to main()"
```

---

### Task 10: 模板外置

**Files:**
- Create: `templates/study_task.md.j2`
- Create: `templates/exhibition_plan.md.j2`
- Create: `templates/transform_local.md.j2`
- Modify: `src/heritage_explorer/agent/handlers/study.py`
- Modify: `src/heritage_explorer/agent/handlers/exhibition.py`
- Modify: `src/heritage_explorer/agent/handlers/transform.py`

- [ ] **Step 1: 创建 templates/study_task.md.j2**

将 `_handle_study_task` 中的硬编码教案模板提取为 Jinja2 模板。

```jinja2
## 非遗研学教案：{{ title }}

**适用对象：**{{ audience_label }}
**课时安排：**{{ time_budget }}
**研学场景：**{{ scenario }}
**所属类别：**{{ category }}
**展示形式：**{{ display }}

### 一、教学目标

1. **知识目标：**了解{{ title }}的历史渊源、技艺特点和代表性作品。
2. **能力目标：**通过观察、讨论和实践体验，培养学生对传统{{ category }}项目的感知和分析能力。
3. **情感目标：**激发对非遗文化的兴趣和认同感，理解保护传承的意义。

### 二、教学重点与难点

- **重点：**{{ title }}的核心技艺特点和历史文化价值。
- **难点：**引导学生理解非遗传承与当代生活的关联。

### 三、教学准备

- 多媒体课件（含项目图片或视频资料）
- 实物展示或模型（如条件允许）
- 学习任务单 / 观察记录表
- 互动体验材料（根据项目特点准备）

### 四、教学过程

#### 环节一：情境导入（5分钟）

展示{{ title }}的图片或短视频，提问：「你们见过这种技艺/艺术形式吗？它来自哪个地方？」
引导学生分享已有认知，引出课题。

#### 环节二：知识讲解（15分钟）

{% if history %}
**历史背景：**{{ history }}
{% endif %}
**技艺特点：**{{ features }}
{% if cultural_value %}
**文化价值：**{{ cultural_value }}
{% endif %}

#### 环节三：小组探究（15分钟）

将学生分为 3-4 组，每组领取一个探究任务：
- **第1组：**研究{{ title }}的历史发展脉络，画出时间轴。
- **第2组：**分析{{ title }}的主要技艺特点，用思维导图整理。
- **第3组：**讨论{{ title }}在当代社会的价值和面临的挑战。
各组派代表汇报，教师点评补充。

#### 环节四：实践体验（8分钟）

根据项目特点选择以下一种或多种方式：
- 动手模仿：让学生尝试简单的技艺操作步骤。
- 创意设计：基于项目元素进行简单的文创设计。
- 角色扮演：模拟传承人向观众介绍项目。

#### 环节五：总结评价（2分钟）

- 回顾本节课的核心知识点。
- 请学生分享「今天印象最深的一个发现」。
- 布置课后拓展任务（如：向家人介绍一项非遗）。

### 五、评价方式

- 课堂参与度：小组讨论和汇报表现。
- 探究任务成果：时间轴 / 思维导图完成质量。
- 实践体验：动手环节的投入程度。

### 六、拓展建议

- 组织实地参观{{ title }}传习所或传承人工作室。
- 与美术课、历史课、语文课进行跨学科联动。
- 鼓励学生制作非遗主题手抄报或短视频介绍。

---
*本教案由 Xuhua AI 基于非遗数据自动生成，建议教师根据实际学情调整。*
```

- [ ] **Step 2: 创建 templates/exhibition_plan.md.j2**

```jinja2
## 非遗展示策划方案

- **场景：**{{ scene }}
- **受众：**{{ audience }}
- **时长：**{{ time_budget }}

### 推荐展项

{% for item in items %}
#### {{ loop.index }}. {{ item.title }}
- **展示形式：**{{ item.display }}
- **核心讲解：**{{ item.summary }}……
- **互动环节：**[建议：知识问答 / 手工体验 / VR 展示]
- **所需物料：**[建议：展板×2 / 实物×1 / 多媒体设备]

{% endfor %}
---
*本方案由 Xuhua AI 基于非遗数据自动生成，互动环节与物料建议仅供参考。*
```

- [ ] **Step 3: 创建 templates/transform_local.md.j2**

包含翻译、年轻化、朋友圈、文创、讲解词、改写的 6 种模板；按 `transform_type` 条件渲染。

- [ ] **Step 4: 更新 handler 使用 Flask render_template_string**

```python
from flask import render_template_string
from pathlib import Path

_TEMPLATE_DIR = Path(__file__).resolve().parents[4] / "templates"

def _render_template(name, **kwargs):
    path = _TEMPLATE_DIR / name
    return render_template_string(path.read_text(encoding="utf-8"), **kwargs)
```

- [ ] **Step 5: 运行测试**

```powershell
python -m pytest tests/test_agent.py -q
```

- [ ] **Step 6: 提交**

```powershell
git add templates/study_task.md.j2 templates/exhibition_plan.md.j2 templates/transform_local.md.j2
git add src/heritage_explorer/agent/handlers/study.py src/heritage_explorer/agent/handlers/exhibition.py src/heritage_explorer/agent/handlers/transform.py
git commit -m "Extract hardcoded templates to Jinja2 template files"
```

---

### Task 11: 拼音索引线程安全

**Files:**
- Modify: `src/heritage_explorer/search.py`

- [ ] **Step 1: 用 lru_cache 替换全局 _PINYIN_INDEX**

```python
# 删除: _PINYIN_INDEX: dict[str, list[str]] | None = None

from functools import lru_cache

@lru_cache(maxsize=1)
def _build_pinyin_index(dataset_path_hash: str) -> dict[str, list[str]]:
    """..."""
    # 实现不变
```

在 `search_items_pinyin` 中:
```python
index = _build_pinyin_index(kb.generated_at or str(len(kb.items)))
```

- [ ] **Step 2: 运行测试**

```powershell
python -m pytest tests/test_agent.py::test_fact_qa_normalizes_homophone_item_name_before_generation -q
```

- [ ] **Step 3: 提交**

```powershell
git add src/heritage_explorer/search.py
git commit -m "Replace global _PINYIN_INDEX with lru_cache for thread safety"
```

---

### Task 12: 前端 ES modules 拆分

**Files:**
- Create: `static/js/main.js`
- Create: `static/js/state.js`
- Create: `static/js/consts.js`
- Create: `static/js/speech.js`
- Create: `static/js/human.js`
- Create: `static/js/markdown.js`
- Create: `static/js/search.js`
- Create: `static/js/ask.js`
- Create: `static/js/ui.js`
- Modify: `templates/index.html`
- Modify: `static/app.js` — 兼容 shim
- Modify: `tests/test_web.py` — 适配新的 JS 文件路径

- [ ] **Step 1: 创建 static/js/state.js**

```javascript
// Global application state
export const state = {
  query: "",
  selectedId: "",
  currentTaskType: "",
  lastAskContext: null,
};

// DOM references
export const els = {};
export function bindElements(map) {
  Object.assign(els, map);
}
```

- [ ] **Step 2: 创建 static/js/consts.js**

从 app.js 提取所有常量：`humanVideos`, `defaultSuggestionQueries`, `followupQueriesByTask`, `PROGRESS_STEP_INDEX`, `loadingSteps`, `HUMAN_MIN_THINKING_MS`, `HUMAN_DISSOLVE_LEAD_MS`, `LOADING_MIN_STEP_MS`, 以及 feature detection (`browserSpeechSupported`, `audioSpeechSupported`, `speechSupported`)。

- [ ] **Step 3: 创建 static/js/human.js**

数字人视频状态机：`humanIdleTimer`, `humanLoopTimer`, `humanTransitionTimer`, `humanDissolveTimer`, `humanTransitionSeq`, `currentHumanState`, `activeHumanVideo`, `standbyHumanVideo`。

导出: `setDigitalHumanState`, `transitionHumanVideo`, `configureHumanVideoPlayback`, `scheduleHumanVideoAdvance`, `pickHumanVideo`, `responseHumanState`, `waitForThinkingDissolve`, `scheduleHumanReturnToIdle`, `visualAnswerDuration`, `digitalHumanCaption`, `syncVoiceIdleState`, 等。

- [ ] **Step 4: 创建 static/js/speech.js**

语音播报全流程：`currentUtterance`, `currentSpeechAudio`, `currentSpeechSegments`, `lastSpeechText`, `lastSpeechAudioUrl`, `speechPlaybackSeq`, `speechUnlocked`, `speechCancelTimer`, `speechStartGuardTimer`, `voiceState`。

导出: `speakAnswer`, `stopSpeech`, `finishSpeechPlayback`, `unlockSpeech`, `setVoiceStatus`, `setVoiceState`, `speakText`, `playAudioAnswer`, `requestServerSpeech`, `requestServerSpeechFile`, `playSpeechSegment`, `speechPlaybackSegments`, `ttsStreamUrl`, `speechText`, `stripSpeechDecorations`, `stripMarkdown`, `syncVoiceIdleState`。

- [ ] **Step 5: 创建 static/js/markdown.js**

Markdown 渲染：`renderMarkdown`, `renderMarkdownFallback`, `renderInlineMarkdown`, `normalizeMarkdownSource`。

- [ ] **Step 6: 创建 static/js/search.js**

右侧资料栏 SSE 搜索 + 详情：`loadRelatedItems`, `renderRelatedItems`, `itemButtonHtml`, `loadDetail`, `clearDetail`, `updateRelatedItems`, `relatedTimer`, `relatedRequestKey`, `inFlightKey`, `relatedPanelTitle`, `updateRelatedPanelTitle`, `detailCardMeta`, `detailSupportText`, `itemTitle`, `itemMetaParts`, `itemTagList`, `fetchJson`, `escapeHtml`。

- [ ] **Step 7: 创建 static/js/ask.js**

提问流程：`askButton`, `askAbortController`, `askRequestId`, `askQuestion`, `beginAskSession`, `finishAskSession`, `postSseResult`, `presentAskResponse`, `presentAskError`, `answerSpeechFromPayload`, `answerRelatedItems`, `rememberAskContext`, `buildAskContext`, `isContextualFollowup`, `setAnswerState`, `setAnswerPlain`, `setAnswerMarkdown`, `setAnswerResult`, `startLoadingSteps`, `stopLoadingSteps`, `applyAskProgress`, `scheduleNextLoadingStep`, `waitForLoadingSteps`, `renderResultAnswer`, `renderResultStats`, `renderResultItems`, `renderSelectionReason`, `renderWarnings`, `renderFollowups`, `modeLabel`, `taskModeLabel`, `resultIntroText`, `resultStats`, `followupQueries`。

- [ ] **Step 8: 创建 static/js/ui.js**

界面辅助函数：`resizeQuestionInput`, `handleQuestionInput`, `bindQueryChips`, `bindResultItemLinks`, `renderQuerySuggestions`, `renderSuggestionStrip`, `syncRestoredQuestion`, `loadMeta`。

- [ ] **Step 9: 创建 static/js/main.js**

```javascript
import { state, bindElements } from './state.js';
import { humanVideos, defaultSuggestionQueries, followupQueriesByTask } from './consts.js';
import { setDigitalHumanState, configureHumanVideoPlayback, scheduleHumanVideoAdvance, stopSpeech as humanStopSpeech } from './human.js';
import { speakAnswer, stopSpeech as speechStopSpeech } from './speech.js';
import { renderMarkdown } from './markdown.js';
import { loadRelatedItems, renderRelatedItems, loadDetail, clearDetail, updateRelatedItems, fetchJson } from './search.js';
import { askQuestion, setupAskListeners } from './ask.js';
import { renderQuerySuggestions, loadMeta, resizeQuestionInput } from './ui.js';

// Bridge stopSpeech to use the imports
window.__stopSpeech = function(opts) {
  humanStopSpeech(opts);
  speechStopSpeech(opts);
};

// Initialize
configureHumanVideoPlayback(document.querySelector('#digitalHumanVideo'), 'idle');
scheduleHumanVideoAdvance(document.querySelector('#digitalHumanVideo'), 'idle');
renderQuerySuggestions();
loadMeta();
document.querySelector('#askButton')?.addEventListener('click', askQuestion);
// ... etc.
```

- [ ] **Step 10: 更新 templates/index.html**

```html
<script type="module" src="{{ url_for('static', filename='js/main.js', v='20260512-refactor') }}"></script>
```

保留 vendor 的 `<script>`（非 module，正常加载）。

- [ ] **Step 11: 更新 static/app.js 为兼容 shim**

```javascript
// Backward-compat shim — redirects to ES module entry
import('./js/main.js');
```

- [ ] **Step 12: 运行 web 测试 + 手动冒烟**

```powershell
python -m pytest tests/test_web.py -q
```

预期：部分 JS 源码字符串检查的测试会失效（因为源码已拆到多个文件），需要更新 test_web.py 中的断言以检查 `js/` 目录下的新文件。

- [ ] **Step 13: 更新 tests/test_web.py**

把所有 `(ROOT / "static" / "app.js").read_text(encoding="utf-8")` 改为检查 `static/js/` 下对应的文件。

```python
# 旧: script = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
# 新: human_js = (ROOT / "static" / "js" / "human.js").read_text(encoding="utf-8")
#     speech_js = (ROOT / "static" / "js" / "speech.js").read_text(encoding="utf-8")
#     consts_js = (ROOT / "static" / "js" / "consts.js").read_text(encoding="utf-8")
```

- [ ] **Step 14: 提交**

```powershell
git add static/js/ static/app.js templates/index.html tests/test_web.py
git commit -m "Split frontend app.js into ES modules under static/js/"
```

---

### Task 13: 补测试

**Files:**
- Create: `tests/test_search.py`
- Create: `tests/test_embeddings.py`
- Create: `tests/test_http_client.py`
- Create: `tests/test_planner.py`

- [ ] **Step 1: 创建 tests/test_search.py**

```python
"""Tests for lexical search, ranking, and pinyin matching."""

from heritage_explorer.search import (
    tokenize,
    normalize_search_query,
    score_item,
    rank_lexical,
    search_items_lexical,
    search_items_pinyin,
)
from heritage_explorer.dataset import load_dataset


def test_tokenize_splits_chinese_chars_into_bigrams():
    tokens = tokenize("太极拳")
    assert "太极" in tokens
    assert "极拳" in tokens

def test_tokenize_deduplicates():
    tokens = tokenize("太极拳太极拳")
    assert tokens.count("太极") == 1

def test_normalize_search_query_strips_fillers():
    assert "太极拳" in normalize_search_query("介绍一下太极拳是什么")
    assert "生成讲解词" not in normalize_search_query("生成讲解词太极拳")

def test_score_item_exact_title_match():
    kb = load_dataset()
    item = next(i for i in kb.items if i.title == "太极拳（陈氏太极拳）")
    score = score_item(item, "太极拳（陈氏太极拳）", tokenize("太极拳（陈氏太极拳）"))
    assert score >= 100

def test_score_item_partial_title():
    kb = load_dataset()
    item = next(i for i in kb.items if "太极拳" in i.title)
    score = score_item(item, "太极", tokenize("太极"))
    assert score >= 40

def test_rank_lexical_orders_by_score():
    kb = load_dataset()
    candidates = [i for i in kb.items if "木版年画" in (i.family or "")]
    if len(candidates) >= 2:
        ranked = rank_lexical(candidates, "滑县木版年画", tokenize("滑县木版年画"))
        assert ranked[0][0] >= ranked[-1][0]

def test_search_items_lexical_returns_results():
    kb = load_dataset()
    result, total = search_items_lexical(kb, query="太极拳", limit=5)
    assert total > 0
    assert len(result) <= 5
    assert any("太极拳" in item.title for item in result)

def test_search_items_lexical_filters_by_category():
    kb = load_dataset()
    result, total = search_items_lexical(kb, query="", category="传统美术", limit=10)
    assert total > 0
    assert all(item.category == "传统美术" for item in result)

def test_search_items_pinyin_finds_homophone():
    kb = load_dataset()
    result = search_items_pinyin(kb, "落山皮影")
    assert any("罗山" in item.title for item in result)

def test_search_items_pinyin_empty_for_short_query():
    kb = load_dataset()
    result = search_items_pinyin(kb, "落")
    assert result == []
```

- [ ] **Step 2: 创建 tests/test_embeddings.py**

```python
"""Tests for embedding index, normalization, and cosine similarity."""

import math
from heritage_explorer.embeddings import (
    normalize_vector,
    dot,
    build_embedding_text,
)
from heritage_explorer.dataset import load_dataset


def test_normalize_vector_unit_length():
    v = [3.0, 4.0]
    n = normalize_vector(v)
    assert math.isclose(n[0], 0.6)
    assert math.isclose(n[1], 0.8)

def test_normalize_vector_empty_for_zero():
    assert normalize_vector([0.0, 0.0, 0.0]) == []

def test_dot_product():
    assert dot([1, 2, 3], [4, 5, 6]) == 32.0

def test_build_embedding_text_includes_title_and_category():
    kb = load_dataset()
    item = kb.items[0]
    text = build_embedding_text(item)
    assert item.title in text
    assert item.category in text
```

- [ ] **Step 3: 创建 tests/test_http_client.py**

```python
"""Tests for http_client: retry, timeout, error wrapping."""

import pytest
import httpx
from heritage_explorer.http_client import (
    get_http_client,
    chat_completion,
    embedding_request,
    describe_error,
)


def test_get_http_client_returns_same_instance():
    c1 = get_http_client()
    c2 = get_http_client()
    assert c1 is c2


def test_describe_error_http_status(monkeypatch):
    import httpx
    response = httpx.Response(500, content=b"Internal Error", request=httpx.Request("POST", "http://test"))
    exc = httpx.HTTPStatusError("fail", request=response.request, response=response)
    desc = describe_error(exc)
    assert "500" in desc
    assert "Internal Error" in desc


def test_describe_error_strips_api_key():
    exc = httpx.RequestError("api-key-12345 and other text")
    desc = describe_error(exc, api_key="api-key-12345")
    assert "api-key-12345" not in desc
    assert "***" in desc


def test_chat_completion_returns_content(monkeypatch):
    class FakeResponse:
        def raise_for_status(self): pass
        def json(self):
            return {"choices": [{"message": {"content": "test answer"}}]}

    def fake_post(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(get_http_client(), "post", fake_post)
    monkeypatch.setattr("heritage_explorer.http_client._should_use_zhipu_sdk", lambda: False)
    result = chat_completion([{"role": "user", "content": "hi"}])
    assert result == "test answer"


def test_embedding_request_returns_vectors(monkeypatch):
    class FakeResponse:
        def raise_for_status(self): pass
        def json(self):
            return {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}

    def fake_post(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(get_http_client(), "post", fake_post)
    monkeypatch.setattr("heritage_explorer.http_client.config", type("cfg", (), {"EMBEDDING_API_KEY": "k", "EMBEDDING_BASE_URL": "http://x", "EMBEDDING_MODEL": "m"})())
    result = embedding_request(["test"])
    assert result == [[0.1, 0.2]]
```

- [ ] **Step 4: 创建 tests/test_planner.py**

```python
"""Tests for planner prompt construction, JSON extraction, and decision parsing."""

from heritage_explorer.agent.planner import (
    build_agent_planner_messages,
    extract_json_object,
    decision_from_planner_payload,
)
from heritage_explorer.agent_models import TaskType
from heritage_explorer.dataset import load_dataset


def test_build_planner_messages_includes_task_boundaries():
    kb = load_dataset()
    messages = build_agent_planner_messages("给朱仙镇木版年画生成讲解词", kb)
    prompt = messages[0]["content"]
    assert "content_transform" in prompt
    assert "study_task" in prompt
    assert "exhibition_plan" in prompt

def test_build_planner_messages_includes_kb_stats():
    kb = load_dataset()
    messages = build_agent_planner_messages("太极拳", kb)
    user_msg = messages[1]["content"]
    assert str(len(kb.items)) in user_msg

def test_extract_json_object_handles_markdown_fence():
    result = extract_json_object('```json\n{"key": "value"}\n```')
    assert result == '{"key": "value"}'

def test_extract_json_object_handles_plain_json():
    result = extract_json_object('{"task_type": "fact_qa"}')
    assert result == '{"task_type": "fact_qa"}'

def test_extract_json_object_raises_on_non_json():
    import pytest
    with pytest.raises(ValueError):
        extract_json_object("no json here")

def test_decision_from_planner_chitchat_forces_local():
    kb = load_dataset()
    decision = decision_from_planner_payload(
        {"task_type": "chitchat", "confidence": 0.9, "needs_retrieval": True, "needs_llm": True, "reason": "test", "direct_answer": "hello", "mode": "no_context"},
        "hi", kb
    )
    assert decision.task_type is TaskType.CHITCHAT
    assert not decision.needs_retrieval
    assert not decision.needs_llm
    assert decision.mode == "local"

def test_decision_from_planner_unknown_type_defaults_to_fact_qa():
    kb = load_dataset()
    decision = decision_from_planner_payload({"task_type": "xyz"}, "test", kb)
    assert decision.task_type is TaskType.FACT_QA
```

- [ ] **Step 5: 运行新测试**

```powershell
python -m pytest tests/test_search.py tests/test_embeddings.py tests/test_http_client.py tests/test_planner.py -q
```

- [ ] **Step 6: 提交**

```powershell
git add tests/test_search.py tests/test_embeddings.py tests/test_http_client.py tests/test_planner.py
git commit -m "Add tests for search, embeddings, http_client, and planner modules"
```

---

### Task 14: 回归验证

- [ ] **Step 1: 运行全量测试**

```powershell
python -m pytest tests/ -q
```

预期：全部通过。

- [ ] **Step 2: 运行 lint**

```powershell
python -m ruff check src tests scripts
```

- [ ] **Step 3: 启动服务冒烟测试**

```powershell
.\.venv\Scripts\python.exe .\app.py
```

浏览器访问 `http://127.0.0.1:5050`，手动测试：
- 基本问答："太极拳是什么"
- 任务分发："推荐3个适合校园展示的传统美术项目"
- 对比："四川皮影和湖北皮影有什么区别"
- 语音播报按钮
- 数字人视频切换
- 右侧资料栏 SSE 搜索

- [ ] **Step 4: 最终提交**

```powershell
git add -A
git commit -m "Finalize comprehensive refactor: all tests pass, lint clean"
```

---
