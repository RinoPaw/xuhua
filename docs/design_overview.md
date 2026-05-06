# 叙华 · 完整设计文档

## 项目定位

叙华：面向全国非遗数据的非遗传播任务型 AI 智能体。

**核心价值：** 让全国非遗数据从"能查"变成"能理解、能筛选、能比较、能推荐、能应用"。不是聊天机器人，不是文案生成器——是基于全国非遗数据库，帮助用户完成"查询→筛选→比较→推荐→应用"的完整任务链。

**技术栈：** Python 3.10+ / Flask / Jinja2 / Vanilla JS / pypinyin

---

## 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                      前端 (Vanilla JS)                    │
│  ┌──────────┐  ┌──────────┐  ┌──────────────────────┐  │
│  │ 数字人挂轴 │  │ 问答输入区 │  │ 批注/相关资料 (右侧)   │  │
│  │  video    │  │ textarea  │  │ 条目列表 + 详情面板    │  │
│  └──────────┘  └──────────┘  └──────────────────────┘  │
└─────────────────────────────────────────────────────────┘
         │  SSE (部分)         │  REST / SSE
         ▼                     ▼
┌─────────────────────────────────────────────────────────┐
│                     Flask Web 层                          │
│  GET  /api/items?q=&stream=1 → SSE 两阶段搜索             │
│  POST /api/ask               → SSE Agent 流式回答         │
│  GET  /api/items/<id>        → 条目详情 JSON              │
│  GET  /api/meta              → 数据库元信息               │
└─────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│                     Agent 层                              │
│  IntentRouter → QueryAnalyzer → Task Handler             │
│  (8 种任务类型，7 个专用 handler，1 个 LLM 回退)          │
└─────────────────────────────────────────────────────────┘
         │                    │
         ▼                    ▼
┌──────────────────┐  ┌──────────────────┐
│   Search 引擎     │  │   AI / LLM 桥接   │
│  lexical + hybrid │  │   answer_question │
│  拼音索引(待做)    │  │   template fill   │
└──────────────────┘  └──────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────┐
│                   数据层                                  │
│  KnowledgeBase (805+ 条目, JSON)                          │
│  StructuredMeta (province / level / district / …)        │
│  SoftLabels (推荐场景标签)                                 │
│  ExtractionCache (field evidence + provenance)            │
└─────────────────────────────────────────────────────────┘
```

---

## 核心数据模型

### HeritageItem
```
id          — 条目唯一标识
title       — 非遗项目名称
category    — 分类 (民间文学/传统音乐/传统戏剧/…)
aliases     — 别名列表
summary     — 摘要
content     — 原文/详细介绍
province    — 省份 (来自 StructuredMeta)
level       — 保护级别 (国家级/省级/市级)
district    — 区县
keywords    — 关键词
search_text — 检索用扁平文本
```

### StructuredMeta (关联)
```
province / level / district / city / history / features / cultural_value
```

### SoftLabels (关联)
```
scenario_scores — { "校园展示": 0.8, "社区活动": 0.6, … }
audience_scores — { "中小学生": 0.9, "大学生": 0.7, … }
```

---

## Agent 流水线

### 请求流程
```
用户输入
  → IntentRouter.classify(query)
    → 若 CHITCHAT → 直接返回寒暄回应
    → 否则 → QueryAnalyzer.analyze(query, task_type)
      → 提取 province/category/level/scenario/audience/retrieval_count
      → 分发到对应 Task Handler
        → handler 内部自行搜索 + 生成回答
```

### 8 种任务类型

| TaskType | 触发条件 (正则) | Handler | 状态 |
|---|---|---|---|
| CHITCHAT | 你好/谢谢/你是谁/你能做什么 | `build_chitchat_answer()` | ✅ |
| FACT_QA | 默认回退 | `answer_question()` (LLM) | ✅ |
| BROWSE_QUERY | 列举/有哪些/筛选/过滤 | `_handle_browse()` | ✅ 纯规则 |
| COMPARISON | 比较/对比/区别/哪个更 | `_handle_comparison()` | ✅ 纯规则 |
| RECOMMENDATION | 推荐/适合/帮我找/挑选 | `_handle_recommend()` | ✅ 纯规则 |
| EXHIBITION_PLAN | 策划/展览/展板/布展/办展 | `_handle_exhibition()` | ✅ 纯规则 |
| STUDY_TASK | 教案/课程/研学/教学/课件 | `_handle_study_task()` | ✅ 纯规则 |
| CONTENT_TRANSFORM | 翻译/英文/年轻化/朋友圈/改写/文创 | `_handle_content_transform()` | ✅ 优先 LLM，回退模板 |

### Handler 设计原则
- **纯规则 handler**：BROWSE / COMPARISON / RECOMMENDATION / EXHIBITION / STUDY_TASK — 不调 LLM，用模板 + 数据拼接生成回答
- **LLM handler**：CONTENT_TRANSFORM — 有 API 时调 LLM 自定义 prompt，无 API 时模板兜底
- **回退**：FACT_QA 走 LLM 的 `answer_question()` 管道

### IntentRouter
- 按优先级依次匹配正则 → 第一个命中即为 task_type
- CHITCHAT 单独前置检查
- 返回 `(task_type, confidence)`，confidence 固定 0.85

### QueryAnalyzer
- 从原始查询提取结构化字段：
  - province / city：正则匹配省份名 / 城市名
  - level：国家级 / 省级 / 市级 / 县级
  - category：匹配 18 类非遗分类
  - scenario：校园展示 / 社区活动 / 展馆讲解 / 文创设计 / 研学活动
  - audience：中小学生 / 大学生 / 成人 / 游客
  - retrieval_count：数字 + "个/项/条"

---

## 搜索管道

### 两阶段 SSE（现有）
```
GET /api/items?q=...&limit=8&stream=1

  ← :ready\n\n                          (SSE 建连)
  ← data: {phase:"lexical", items, total}  (纯关键词，~ms级别)
  ← data: {phase:"hybrid",  items, total}  (RRF fusion，等embedding API)
```

### Lexical 搜索
- tokenize：中文分词 (字符→2-gram→单字)
- score_item：title/category/summary/content 逐字段打分
- 精确全匹配 = 100 分，token 命中 title = 12 分，命中 category = 5 分，命中 summary = 3 分

### Hybrid 搜索
- lexical top-80 + semantic top-80 → RRF fusion (k=60)
- LEXICAL_RANK_WEIGHT = 1.3（已上调，因拼音同音只走 lexical）
- SEMANTIC_RANK_WEIGHT = 1.35
- 加 strong_match_bonus + lexical_tiebreak
- embedding API 不可用时自动降级为纯 lexical

### 前端防抖与竞态
- 输入停止 1s 后才发请求（防抖）
- 用 query 字符串本身作请求标识（非计数器），回到同一 query 时复用已在飞的请求
- SSE 每个 chunk 检查 requestKey 是否仍为最新，否则 reader.cancel()

---

## 前端架构

### 三栏布局
```
┌──────────────┬──────────────┬──────────────┐
│  挂轴 (左)    │  问页 (中)    │  批注 (右)    │
│  数字人视频   │  textarea    │  条目列表     │
│  状态栏       │  语音/提问    │  详情面板     │
│  字幕行       │  回答区      │  空态提示     │
└──────────────┴──────────────┴──────────────┘
```

### 数字人状态机
- idle → thinking → speaking → idle
- 视频切换：idle.mp4 / greet.mp4 / speak.mp4

### 语音播报
- 浏览器 SpeechSynthesis API
- 状态切换：播报 ↔ 暂停
- markdown → 纯文本 → 截断 720 字
- 首字触发 unlock (解决浏览器自动播放限制)

### 回答渲染
- markdown → HTML（h1-h4 / p / ul/ol / code block / inline bold/italic/code）
- 加载态：4 步进度动画（翻检资料库→比对资料→组织回答→生成回答→润色播报）

---

## 拼音模糊搜索（待实现）

### 目标
输入同音字命中目标条目。例："落山"(luò shān) → "罗山"(luó shān)

### 方案
- `pypinyin` lazy style（无调号）
- 对 title 预建拼音索引 `{ "luo": [...ids], "shan": [...ids], ... }`
- `tokenize()` 产出额外同音 pinyin token 参与 `score_item()` 打分
- 精确字面 : 同音 ≈ 1 : 0.4

### 调权
- 拼音命中只走 lexical，不走 embedding
- `LEXICAL_RANK_WEIGHT` 已从 1.0 调到 1.3

### 改动文件
| 文件 | 内容 |
|------|------|
| `search.py` | 新增 `build_pinyin_index()`，tokenize 产出拼音 token |
| `indexer.py` 或 KB 构建 | 调用 pinyin 索引生成 |
| `requirements.txt` | 加 `pypinyin` |
| `tests/test_search.py` | 同音召回用例 |

### 不做
- 模糊音（前后鼻音 etc）
- 编辑距离排序

---

## 待完成项

1. **拼音模糊搜索** — 见上方
2. ~~COMPARISON handler~~ ✅
3. ~~STUDY_TASK handler~~ ✅
4. ~~CONTENT_TRANSFORM handler~~ ✅
5. 全量测试 + 代码审查 + 提交

---

## 设计决策

| 决策 | 原因 |
|------|------|
| handler 优先纯规则，不调 LLM | 减少 API 成本、响应更快、结果稳定 |
| 两阶段搜索（lexical → hybrid） | 先让用户看到即时结果，embedding 到了再刷新 |
| 防抖 1s | 减少 embedding API 浪费 |
| 请求标识用 query 字符串而非计数器 | 回到同一 query 时复用已在飞的请求 |
| 搜索结果质量门控交给 LLM 判断 | 硬阈值无法区分 "hello" vs "桐柏山歌" |
| Agent 自主决定是否检索 | 寒暄/闲聊跳过搜索，直接回答 |
