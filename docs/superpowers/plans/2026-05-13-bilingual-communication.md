# 双语传播 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将现有"翻译"功能升级为字段级中英双语对照卡片，LLM-only 路径，前端左右分栏渲染。

**Architecture:** 后端在 `_handle_content_transform` 的翻译分支新增 LLM JSON 解析，产出 `bilingual_fields` 结构化数据 → SSE result 事件携带新字段 → 前端 `ask.js` 检测后走专用卡片渲染，不走 markdown 管道。

**Tech Stack:** Python 3.12+, dataclasses (AgentResult), vanilla JS (ES modules), CSS grid

---

### Task 1: Extend AgentResult with `bilingual_fields`

**Files:**
- Modify: `src/heritage_explorer/agent_models.py:70-85`

- [ ] **Step 1: Add `bilingual_fields` field to AgentResult dataclass**

```python
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
    bilingual_fields: list[dict[str, str]] | None = None
    # backward-compat
    speech: str = ""
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `python -m pytest tests/test_agent.py -v --timeout=30`
Expected: all existing tests pass (AgentResult now has an extra optional field, no breakage)

- [ ] **Step 3: Commit**

```bash
git add src/heritage_explorer/agent_models.py
git commit -m "feat: add bilingual_fields to AgentResult dataclass"
```

---

### Task 2: Write the `_parse_bilingual_json` parser with tests

**Files:**
- Create: `tests/test_bilingual.py`
- Modify: `src/heritage_explorer/agent/__init__.py` (add `_parse_bilingual_json`)

- [ ] **Step 1: Write failing tests for the parser**

```python
"""Tests for bilingual JSON parsing."""


def test_parse_bilingual_json_valid():
    from heritage_explorer.agent import _parse_bilingual_json

    raw = """{
  "answer": "朱仙镇木版年画是中国传统美术瑰宝。",
  "fields": {
    "名称": "Zhuxianzhen Woodblock New Year Prints",
    "类别": "Traditional Fine Arts",
    "简介": "Zhuxianzhen woodblock prints are one of China's oldest folk art forms...",
    "主要特色": "Bold outlines, vibrant colors, hand-carved wooden blocks..."
  }
}"""
    result = _parse_bilingual_json(raw)
    assert result is not None
    assert result["answer"] == "朱仙镇木版年画是中国传统美术瑰宝。"
    assert result["fields"]["名称"] == "Zhuxianzhen Woodblock New Year Prints"
    assert result["fields"]["类别"] == "Traditional Fine Arts"
    assert len(result["fields"]) == 4


def test_parse_bilingual_json_with_markdown_fence():
    from heritage_explorer.agent import _parse_bilingual_json

    raw = """```json
{
  "answer": "test answer",
  "fields": {
    "名称": "Name",
    "类别": "Category",
    "简介": "Summary",
    "主要特色": "Features"
  }
}
```"""
    result = _parse_bilingual_json(raw)
    assert result is not None
    assert result["answer"] == "test answer"
    assert result["fields"]["名称"] == "Name"


def test_parse_bilingual_json_missing_keys():
    from heritage_explorer.agent import _parse_bilingual_json

    assert _parse_bilingual_json('{"answer": "hi"}') is None
    assert _parse_bilingual_json('{"fields": {}}') is None
    assert _parse_bilingual_json("not json") is None
    assert _parse_bilingual_json("") is None


def test_parse_bilingual_json_extra_text_around_json():
    from heritage_explorer.agent import _parse_bilingual_json

    raw = """Sure! Here is the translation:

{
  "answer": "intro",
  "fields": {
    "名称": "EN",
    "类别": "EN",
    "简介": "EN",
    "主要特色": "EN"
  }
}

Hope that helps!"""
    result = _parse_bilingual_json(raw)
    assert result is not None
    assert result["answer"] == "intro"


def test_parse_bilingual_json_partial_fields():
    from heritage_explorer.agent import _parse_bilingual_json

    raw = """{
  "answer": "intro",
  "fields": {
    "名称": "Name",
    "类别": "Category"
  }
}"""
    result = _parse_bilingual_json(raw)
    assert result is None  # must have all 4 fields
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_bilingual.py -v`
Expected: FAIL with "ImportError" (no `_parse_bilingual_json` yet)

- [ ] **Step 3: Implement `_parse_bilingual_json` in agent/__init__.py**

Add after `_call_transform_model` (around line 791):

```python
def _parse_bilingual_json(raw_text: str) -> dict | None:
    """Extract bilingual fields JSON from LLM output.

    Handles markdown code fences and extra text around the JSON block.
    Returns None if parsing fails or required keys are missing.
    """
    import json as _json

    text = (raw_text or "").strip()
    if not text:
        return None

    # Strip markdown code fence if present
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    else:
        # Try to find JSON object boundaries
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

    return data
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_bilingual.py -v`
Expected: all 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_bilingual.py src/heritage_explorer/agent/__init__.py
git commit -m "feat: add _parse_bilingual_json parser for bilingual LLM output"
```

---

### Task 3: Update the "翻译" system prompt

**Files:**
- Modify: `src/heritage_explorer/agent/__init__.py:747-751` (`_TRANSFORM_PROMPTS["翻译"]`)

- [ ] **Step 1: Replace the existing 翻译 prompt**

Replace the current "翻译" entry in `_TRANSFORM_PROMPTS` (line 748-751):

```python
_TRANSFORM_PROMPTS: dict[str, str] = {
    "翻译": (
        "你是一个非遗资料翻译助手。请将以下非遗项目的中文信息逐字段翻译为英文，输出严格的 JSON 格式。\n"
        "\n"
        "输出格式：\n"
        '{\n'
        '  "answer": "一段50字以内的中英双语导语，介绍该项目",\n'
        '  "fields": {\n'
        '    "名称": "English name",\n'
        '    "类别": "English category",\n'
        '    "简介": "English summary",\n'
        '    "主要特色": "English key features"\n'
        '  }\n'
        '}\n'
        "\n"
        "翻译要求：\n"
        "- 名称：采用意译或通用译名，必要时括号注拼音\n"
        "- 类别：使用标准的非物质文化遗产分类英文术语\n"
        "- 简介：翻译准确流畅，适合对外传播\n"
        "- 主要特色：保留关键技艺和文化的专有名词，可括号注中文\n"
        "- 字段值保持简明，简介和特色各控制在 150 词以内"
    ),
    "年轻化": (
        ...
    ),
    ...
}
```

- [ ] **Step 2: Verify prompt test still passes**

Run: `python -m pytest tests/test_agent.py::test_content_transform_prompts_keep_cultural_promotion_closing -v`
Expected: PASS (old assertion about "生活场景/参观体验" etc. won't hit 翻译 — 翻译 prompt has been intentionally replaced with JSON instruction. If the test only checks 年轻化/朋友圈/讲解词, it'll pass fine.)

Recheck: `python -m pytest tests/test_agent.py -k "transform" -v`
Expected: all transform tests PASS or are adjusted to match new prompt

- [ ] **Step 3: Commit**

```bash
git add src/heritage_explorer/agent/__init__.py
git commit -m "feat: update translation prompt for structured bilingual JSON output"
```

---

### Task 4: Rewire `_handle_content_transform` translation branch

**Files:**
- Modify: `src/heritage_explorer/agent/__init__.py:458-486` (LLM path and local fallback within `_handle_content_transform`)

- [ ] **Step 1: Write test for the new bilingual LLM path**

In `tests/test_agent.py`, add:

```python
def test_content_transform_translation_produces_bilingual_fields(monkeypatch):
    from heritage_explorer.dataset import load_dataset
    from heritage_explorer import config

    kb = load_dataset()
    agent = Agent(kb)
    monkeypatch.setattr(config, "AI_API_KEY", "test-key")
    monkeypatch.setattr(
        "heritage_explorer.agent._call_transform_model",
        lambda **_kwargs: (
            '{\n'
            '  "answer": "朱仙镇木版年画是中国传统美术瑰宝。",\n'
            '  "fields": {\n'
            '    "名称": "Zhuxianzhen Woodblock New Year Prints",\n'
            '    "类别": "Traditional Fine Arts",\n'
            '    "简介": "One of China\'s oldest folk art forms.",\n'
            '    "主要特色": "Bold outlines and vibrant colors."\n'
            '  }\n'
            '}'
        ),
    )

    result = agent.dispatch("把朱仙镇木版年画翻译成英文")

    assert result.task_type is TaskType.CONTENT_TRANSFORM
    assert result.mode == "llm"
    assert result.bilingual_fields is not None
    assert len(result.bilingual_fields) == 4
    assert result.bilingual_fields[0] == {
        "label_cn": "名称",
        "label_en": "Name",
        "value_cn": result.items[0]["title"],
        "value_en": "Zhuxianzhen Woodblock New Year Prints",
    }
    assert result.answer == "朱仙镇木版年画是中国传统美术瑰宝。"


def test_content_transform_translation_no_api_key(monkeypatch):
    from heritage_explorer.dataset import load_dataset
    from heritage_explorer import config

    kb = load_dataset()
    agent = Agent(kb)
    monkeypatch.setattr(config, "AI_API_KEY", "")

    result = agent.dispatch("把朱仙镇木版年画翻译成英文")

    assert result.task_type is TaskType.CONTENT_TRANSFORM
    assert result.mode == "unavailable"
    assert result.bilingual_fields is None
    assert "API Key" in result.answer


def test_content_transform_translation_parse_failure_fallback(monkeypatch):
    from heritage_explorer.dataset import load_dataset
    from heritage_explorer import config

    kb = load_dataset()
    agent = Agent(kb)
    monkeypatch.setattr(config, "AI_API_KEY", "test-key")
    monkeypatch.setattr(
        "heritage_explorer.agent._call_transform_model",
        lambda **_kwargs: "This is not JSON, just some English text.",
    )

    result = agent.dispatch("把朱仙镇木版年画翻译成英文")

    assert result.task_type is TaskType.CONTENT_TRANSFORM
    assert result.mode == "llm"
    assert result.bilingual_fields is None
    assert "This is not JSON" in result.answer
    assert any("双语解析失败" in w for w in result.warnings)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_agent.py -k "bilingual" -v`
Expected: all 3 new tests FAIL (old behavior still produces plain text)

- [ ] **Step 3: Implement the new translation branch**

Replace lines 458-486 in `_handle_content_transform`:

```python
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
```

Add the new handler method before `_handle_browse` (around line 488):

```python
    def _handle_bilingual_transform(self, context: str, query: str, target_item) -> AgentResult:
        """Handle bilingual (翻译) transform using LLM JSON output."""
        import json as _json

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

        # Convert flat fields dict to ordered label-value pairs
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
                "value_cn": _field_value_cn(target_item, label_cn),
                "value_en": parsed["fields"].get(label_cn, ""),
            }
            for label_cn, label_en in field_order
        ]

        return AgentResult(
            task_type=TaskType.CONTENT_TRANSFORM,
            answer=parsed.get("answer", ""),
            bilingual_fields=bilingual_fields,
            items=[_enriched_item_card(target_item)],
            sources=[_source_payload(target_item)],
            mode="llm",
            confidence=0.8,
        )
```

Add a helper before `_handle_bilingual_transform`:

```python
def _field_value_cn(target_item, field_name: str) -> str:
    """Extract Chinese value for a bilingual field from the heritage item."""
    if field_name == "名称":
        return _title_with_family(target_item)
    if field_name == "类别":
        return target_item.category
    if field_name == "简介":
        return target_item.summary[:300] if target_item.summary else ""
    if field_name == "主要特色":
        return target_item.features[:300] if target_item.features else target_item.summary[:300]
    return ""
```

- [ ] **Step 4: Run all bilingual-related tests**

Run: `python -m pytest tests/test_agent.py -k "bilingual or transform" -v`
Expected: all tests PASS (3 new + existing transform tests)

- [ ] **Step 5: Commit**

```bash
git add src/heritage_explorer/agent/__init__.py tests/test_agent.py
git commit -m "feat: rewire content_transform translation to produce bilingual_fields"
```

---

### Task 5: Add `bilingual_fields` to SSE result payload

**Files:**
- Modify: `src/heritage_explorer/web.py:134-150` (result_payload dict)

- [ ] **Step 1: Write web test for bilingual_fields in SSE result**

In `tests/test_web.py`, add:

```python
def test_bilingual_fields_in_sse_result(client, monkeypatch):
    """SSE result event carries bilingual_fields when present."""
    from heritage_explorer.agent import AgentResult, TaskType
    from heritage_explorer.agent_models import AgentDecision

    # Mock agent to return a result with bilingual_fields
    fake_result = AgentResult(
        task_type=TaskType.CONTENT_TRANSFORM,
        answer="导语",
        bilingual_fields=[
            {"label_cn": "名称", "label_en": "Name", "value_cn": "汴绣", "value_en": "Bian Embroidery"},
            {"label_cn": "类别", "label_en": "Category", "value_cn": "传统美术", "value_en": "Traditional Fine Arts"},
            {"label_cn": "简介", "label_en": "Summary", "value_cn": "汴绣是...", "value_en": "Bian embroidery is..."},
            {"label_cn": "主要特色", "label_en": "Key Features", "value_cn": "针法细腻", "value_en": "Fine stitching"},
        ],
        items=[{"id": "test-1", "title": "汴绣"}],
        sources=[],
        mode="llm",
        confidence=0.8,
    )
    fake_decision = AgentDecision(
        task_type=TaskType.CONTENT_TRANSFORM,
        confidence=0.8,
        needs_retrieval=True,
        needs_llm=True,
        reason="test",
        mode="llm",
    )

    def fake_stream():
        yield fake_result  # result event
        # speech event (dict with type="speech")
        yield {"type": "speech", "text": "test speech"}

    monkeypatch.setattr(
        "heritage_explorer.agent.Agent.dispatch_stream",
        lambda self, **_: fake_stream(),
    )

    response = client.post(
        "/api/ask",
        json={"question": "把汴绣翻译成英文", "voice_enabled": "0"},
        headers={"Accept": "text/event-stream"},
    )
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "bilingual_fields" in body
    assert "Bian Embroidery" in body
    assert "Traditional Fine Arts" in body
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_web.py::test_bilingual_fields_in_sse_result -v`
Expected: FAIL ("bilingual_fields" not in SSE output)

- [ ] **Step 3: Add bilingual_fields to result_payload in web.py**

In `src/heritage_explorer/web.py`, modify the `result_payload` dict (after line 150):

```python
                    result_payload = {
                        'type': 'result',
                        'answer': event.answer,
                        'speech': event.speech,
                        **speech_audio,
                        'mode': event.mode,
                        'task_type': event.task_type.value,
                        'task_label': task_type_label(event.task_type),
                        'confidence': event.confidence,
                        'sources': event.sources,
                        'items': event.items,
                        'evidence': event.evidence,
                        'selection_reason': event.selection_reason,
                        'warnings': event.warnings,
                        'total_count': event.total_count,
                        'decision': event.decision,
                        'bilingual_fields': event.bilingual_fields,
                    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_web.py::test_bilingual_fields_in_sse_result -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/heritage_explorer/web.py tests/test_web.py
git commit -m "feat: wire bilingual_fields into SSE result payload"
```

---

### Task 6: Add bilingual card CSS layout

**Files:**
- Modify: `static/styles.css` (add `.bilingual-card` and related styles)
- Modify: `templates/index.html:7` (update CSS version)

- [ ] **Step 1: Add CSS for bilingual card grid layout**

At the end of `static/styles.css`, add:

```css
/* ── Bilingual card layout ── */
.bilingual-card {
  padding: 16px 0;
}

.bilingual-card .bilingual-head {
  padding: 0 4px;
  margin-bottom: 18px;
}

.bilingual-card .bilingual-title {
  font-size: 18px;
  font-weight: 700;
  color: var(--ink-primary);
  margin: 0 0 4px;
}

.bilingual-card .bilingual-subtitle {
  font-size: 14px;
  color: var(--ink-secondary);
  font-style: italic;
  margin: 0;
}

.bilingual-card .bilingual-intro {
  padding: 0 4px;
  margin-bottom: 16px;
  font-size: 13px;
  color: var(--ink-secondary);
  line-height: 1.6;
}

.bilingual-card .bilingual-fields {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.bilingual-field-row {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  padding: 12px 4px;
  border-bottom: 1px solid var(--border-light);
}

.bilingual-field-row:last-child {
  border-bottom: none;
}

.bilingual-field-col {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.bilingual-field-label {
  font-size: 11px;
  font-weight: 600;
  color: var(--ink-tertiary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
  margin-bottom: 2px;
}

.bilingual-field-value {
  font-size: 14px;
  color: var(--ink-primary);
  line-height: 1.5;
  word-break: break-word;
}
```

- [ ] **Step 2: Update CSS version in index.html**

In `templates/index.html`, change the CSS version:

```html
<link rel="stylesheet" href="{{ url_for('static', filename='styles.css', v='20260513-bilingual') }}" />
```

- [ ] **Step 3: Commit**

```bash
git add static/styles.css templates/index.html
git commit -m "feat: add bilingual card CSS grid layout"
```

---

### Task 7: Render bilingual card in ask.js

**Files:**
- Modify: `static/js/ask.js:349-368` (`renderResultAnswer` function and result event handling)
- Modify: `templates/index.html:96` (update JS version)

- [ ] **Step 1: Add bilingual card rendering function**

Add a new function before `renderResultAnswer` in `ask.js` (around line 349):

```javascript
function renderBilingualCard(payload) {
  const fields = payload?.bilingual_fields;
  if (!fields?.length) return "";

  const title = payload?.items?.[0]?.title || "";
  const enTitle = fields.find(f => f.label_cn === "名称")?.value_en || "";

  return `
    <div class="bilingual-card">
      <div class="bilingual-head">
        <h2 class="bilingual-title">${escapeHtml(title)}</h2>
        <p class="bilingual-subtitle">${escapeHtml(enTitle)}</p>
      </div>
      <p class="bilingual-intro">${escapeHtml(payload?.answer || "")}</p>
      <div class="bilingual-fields">
        ${fields.map(f => `
        <div class="bilingual-field-row">
          <div class="bilingual-field-col">
            <span class="bilingual-field-label">${escapeHtml(f.label_cn)}</span>
            <span class="bilingual-field-value">${escapeHtml(f.value_cn)}</span>
          </div>
          <div class="bilingual-field-col">
            <span class="bilingual-field-label">${escapeHtml(f.label_en)}</span>
            <span class="bilingual-field-value">${escapeHtml(f.value_en)}</span>
          </div>
        </div>`).join("")}
      </div>
    </div>
  `;
}
```

- [ ] **Step 2: Modify `renderResultAnswer` to branch on bilingual_fields**

Replace the existing `renderResultAnswer` (line 349):

```javascript
function renderResultAnswer(question, payload) {
  const taskLabel = payload?.task_label || modeLabel(payload?.mode);

  const bilingualCard = renderBilingualCard(payload);
  const answerSection = bilingualCard
    ? bilingualCard
    : `<section class="result-section">
        <h3>${escapeHtml(taskLabel)}结果</h3>
        <div class="result-markdown">${renderMarkdown(payload?.answer || "")}</div>
      </section>`;

  return `
    <div class="result-shell" data-task="${escapeHtml(payload?.task_type || "fact_qa")}">
      <section class="result-section">
        <h3>任务理解</h3>
        <p class="result-intro">${escapeHtml(resultIntroText(question, payload))}</p>
      </section>
      ${renderResultStats(payload)}
      ${renderResultItems(payload)}
      ${renderSelectionReason(payload)}
      ${answerSection}
      ${renderWarnings(payload)}
      ${renderFollowups(payload)}
    </div>
  `;
}
```

- [ ] **Step 3: Update JS version in index.html**

In `templates/index.html`, change the JS version:

```html
<script type="module" src="{{ url_for('static', filename='js/main.js', v='20260513-bilingual') }}"></script>
```

- [ ] **Step 4: Commit**

```bash
git add static/js/ask.js templates/index.html
git commit -m "feat: render bilingual card with left-right field grid in ask.js"
```

---

### Task 8: End-to-end manual verification

**Files:**
- No file changes

- [ ] **Step 1: Start the Flask dev server**

```bash
python -m heritage_explorer.web
```
Expected: server starts on http://127.0.0.1:5050

- [ ] **Step 2: Verify bilingual workflow with API key**

1. Configure `AI_API_KEY` in environment
2. Type: "把朱仙镇木版年画翻译成英文"
3. Expected UI:
   - 3-step progress animation
   - Result renders with bilingual card layout (not markdown)
   - Chinese values in left column, English in right column
   - 4 field rows: 名称, 类别, 简介, 主要特色
   - Bilingual intro paragraph between title and field rows

- [ ] **Step 3: Verify without API key**

1. Unset `AI_API_KEY`
2. Type: "把汴绣翻译成英文"
3. Expected: "双语翻译需要配置 API Key。请在环境变量中设置 AI_API_KEY 后重试。"

- [ ] **Step 4: Verify other transforms still work**

1. Type: "把朱仙镇木版年画改写成年轻化文案"
2. Expected: normal markdown rendering, no bilingual card (fallback path untouched)

- [ ] **Step 5: Run full test suite**

```bash
python -m pytest tests/ -v --timeout=60
```
Expected: all tests green, no regressions

