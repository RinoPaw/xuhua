# 叙华双语传播功能设计文档

日期: 2026-05-13

## 目标

将现有"翻译"功能升级为字段级中英双语对照，以结构化项目卡片形式呈现，支持左右分栏展示。替换原有的纯英文翻译输出。

## 数据模型

AgentResult 新增字段：

```python
bilingual_fields: list[dict[str, str]] | None = None
```

每项结构固定 4 个字段：

```python
{"label_cn": "名称", "label_en": "Name",
 "value_cn": "朱仙镇木版年画", "value_en": "Zhuxianzhen Woodblock New Year Prints"}
{"label_cn": "类别", "label_en": "Category",
 "value_cn": "传统美术", "value_en": "Traditional Fine Arts"}
{"label_cn": "简介", "label_en": "Summary",
 "value_cn": "...", "value_en": "..."}
{"label_cn": "主要特色", "label_en": "Key Features",
 "value_cn": "...", "value_en": "..."}
```

AgentResult.answer 存放一条简短的中英双语导语（50 字以内），作为卡片标题下方的引导文案。

## 后端流水线

`_handle_content_transform` 中 "翻译" 分支改为 LLM-only 路径：

1. 调用 LLM，使用新的双语翻译 system prompt，要求输出 JSON
2. 新增 `_parse_bilingual_json()` 解析 LLM 返回的 JSON
3. 解析成功 → 填入 `AgentResult(answer=导语, bilingual_fields=[...])`
4. 解析失败 → `AgentResult(answer=原始返回, bilingual_fields=None, warnings=["双语解析失败"])`
5. 无 API Key → `AgentResult(answer="双语翻译需要配置 API Key", mode="unavailable")`

保留现有的 `browse_query` 类型（query → search → item card）不受影响；"翻译"只在 CONTENT_TRANSFORM 路径触发。

## LLM Prompt

```
你是一个非遗资料翻译助手。请将以下非遗项目的中文信息逐字段翻译为英文，输出严格的 JSON 格式。

输出格式：
{
  "answer": "一段50字以内的中英双语导语，介绍该项目",
  "fields": {
    "名称": "English name",
    "类别": "English category",
    "简介": "English summary",
    "主要特色": "English key features"
  }
}

翻译要求：
- 名称：采用意译或通用译名，必要时括号注拼音
- 类别：使用标准的非物质文化遗产分类英文术语
- 简介：翻译准确流畅，适合对外传播
- 主要特色：保留关键技艺和文化的专有名词，可括号注中文
- 字段值保持简明，简介和特色各控制在 150 词以内
```

后端新增 `_parse_bilingual_json(raw_text: str) -> dict | None`，从 LLM 输出中提取 JSON 块（兼容 markdown code fence），验证必含字段 "answer" 和 "fields"（且 fields 含 4 个键），解析失败返回 None。

## 前端渲染

SSE result 事件可选传递 `bilingual_fields`（数组）。`ask.js` 收到后走专用渲染路径：

**渲染结构（从上到下）：**
1. 项目标题（中文大字 + 英文副标题）
2. 双语导语（`answer` 字段，普通段落）
3. 4 行字段卡片，每行左中右

**每行 CSS 布局：**
```
display: grid; grid-template-columns: 1fr 1fr;
```
左侧中文值，右侧英文值。

**不适用 markdown 渲染**：bilingual_fields 检测优先，不进入 marked 管道。

**无 bilingual_fields 时**：退回到现有 markdown 渲染（兼容旧结果和错误情况）。

## SSE 协议扩展

result 事件 JSON 新增可选字段：

```json
{
  "type": "result",
  "answer": "双语导语...",
  "bilingual_fields": [
    {"label_cn": "名称", "label_en": "Name", "value_cn": "...", "value_en": "..."},
    ...
  ],
  "items": [...],
  "mode": "llm",
  ...
}
```

不影响现有 result 事件的解析逻辑。

## 影响范围

- `src/heritage_explorer/agent/__init__.py`: `_handle_content_transform` 翻译分支, `_parse_bilingual_json`, `_TRANSFORM_PROMPTS["翻译"]`
- `static/js/ask.js`: result 事件处理，新增双语卡片渲染函数
- `static/styles.css`: 双语卡片行样式（grid 两栏）
- `templates/index.html`: CSS/JS 版本号更新

## 不变

- `_extract_transform_type` 仍将 "翻译/英文/英语/双语/translate" 映射为 "翻译"
- Planner prompt 中 "双语文案" 描述不变
- browse_query、recommend、comparison、exhibition_plan、study_task 路径完全不受影响
- speech/TTS 不处理双语内容（只播中文）
