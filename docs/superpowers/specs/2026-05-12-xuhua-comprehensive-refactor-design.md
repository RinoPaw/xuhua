# 叙华全面重构设计文档

日期: 2026-05-12

## 目标

按评审报告全面改进代码架构：拆大文件、统一 HTTP 层、消除 config 副作用、模板外置、前端 ES modules 拆分、补测试覆盖。

## 模块拆分方案

### agent/ 包（从 agent.py 拆分）

```
src/heritage_explorer/agent/
├── __init__.py          # 公开 API: Agent, AgentResult, TaskType 等
├── router.py            # IntentRouter + call_agent_planner_model
├── dispatcher.py        # Agent.dispatch / dispatch_stream 核心调度
├── planner.py           # planner prompt 构建、JSON 提取、decision_from_planner_payload
├── handlers/
│   ├── __init__.py
│   ├── browse.py        # _handle_browse
│   ├── comparison.py    # handle_comparison (从 agent_comparison.py 迁入)
│   ├── recommend.py     # _handle_recommend
│   ├── exhibition.py    # _handle_exhibition
│   ├── study.py         # _handle_study_task
│   └── transform.py     # _handle_content_transform + _TRANSFORM_PROMPTS
└── query_utils.py       # normalize_query_with_pinyin_anchor, replace_homophone_span
```

- 现有 `agent_comparison.py` 删除，逻辑并入 `handlers/comparison.py`
- `agent_models.py`、`agent_task_config.py` 保持独立
- `__init__.py` 重新导出所有公开名称，保持现有 import 路径兼容

### ai/ 包（从 ai.py 拆分）

```
src/heritage_explorer/ai/
├── __init__.py          # 公开 API: Answer, answer_question, build_spoken_answer
├── client.py            # 通过 http_client 调聊天模型（替代 urllib + zhipuai SDK）
├── qa.py                # answer_question, build_local_answer, fact_question_sources
├── speech.py            # build_spoken_answer, build_speech_text, clean_spoken_output
├── context.py           # build_context, item_context_text, extract_structured_field
└── prompts.py           # 所有 system prompt 常量
```

### http_client.py（新建）

```python
# 全局 httpx.Client 单例，连接池复用
def get_http_client() -> httpx.Client: ...

# 聊天补全，统一处理 DeepSeek / 智谱 / OpenAI 兼容接口
def chat_completion(messages, temperature, max_tokens) -> str: ...

# embedding 请求
def embedding_request(texts) -> list[list[float]]: ...
```

- 替代所有 `urllib.request` 直接调用
- 替代 `ai.py` 中的 `call_zhipu_sdk` / `call_openai_compatible_model`
- `embeddings.py` 的 `EmbeddingClient` 改为用共享 client
- `agent.py` 的 planner 模型调用走同一通道

### config.py 改造

- 移除顶层 `load_dotenv()` 调用（第26行）
- 模块级常量改为 `@lru_cache` 包装的函数属性
- `load_dotenv()` 由 `web.py:main()` 入口显式调用

### 拼音索引线程安全

- 删除 `search.py:_PINYIN_INDEX` 全局变量
- `_build_pinyin_index()` 用 `@lru_cache` 缓存

## 模板外置

- `templates/study_task.md.j2` — `_handle_study_task` 教案模板
- `templates/exhibition_plan.md.j2` — `_handle_exhibition` 展示方案模板
- `templates/transform_local.md.j2` — `_build_transform_local` 各类模板
- Jinja2 渲染（Flask 自带），`render_template()` 或 `Environment` 实例

## 前端 ES Modules 拆分

```
static/
├── js/
│   ├── main.js          # 入口，import 所有模块并初始化
│   ├── state.js         # 全局 state 对象 + 状态管理
│   ├── consts.js        # 常量定义
│   ├── speech.js        # 语音播报全流程
│   ├── human.js         # 数字人视频状态机 + 过渡动画
│   ├── markdown.js      # Markdown 渲染引擎
│   ├── search.js        # 右侧资料栏 SSE 搜索 + 详情面板
│   ├── ask.js           # 提问流程（SSE 消费、进度调度）
│   └── ui.js            # 界面辅助函数
├── app.js               # 浅封装，动态 import main.js
├── styles.css
├── vendor/
└── media/
```

- `index.html` 用 `<script type="module" src="/static/js/main.js">`
- 每个模块保持干净的函数导出，共享依赖通过 import 明确标注
- 拆分时保持行为等价，不引入新功能

## 测试补全

- `tests/test_search.py` — score_item, tokenize, rank_lexical, rank_hybrid, RRF 融合, 拼音匹配
- `tests/test_embeddings.py` — normalize_vector, cosine, build_embedding_text
- `tests/test_http_client.py` — 重试、超时、error wrapping
- `tests/test_planner.py` — prompt 构建、JSON 提取、decision 校验
- 更新现有测试中的 import 路径

## 测试策略

- 不做真正的模型集成测试（依赖外部 API，CI 不可控）
- HTTP client 用 monkeypatch 替换为 fake
- 前端拆分后跑现有 web 测试（检查 JS 源码的关键字符串匹配需适配新的 import 结构）
- 全量 `pytest -q` 通过作为每阶段的门控条件

## 实施顺序

| 阶段 | 内容 | 依赖 |
|---|---|---|
| 1 | 拆 agent.py → agent/ 包 | 无 |
| 2 | 拆 ai.py → ai/ 包 | 无 |
| 3 | 新建 http_client.py + 统一 HTTP 调用 | 阶段2完成后 |
| 4 | 修 config 副作用 | 阶段3完成后 |
| 5 | 模板外置 | 无 |
| 6 | 拼音索引线程安全 | 无 |
| 7 | 前端 ES modules 拆分 | 无 |
| 8 | 补测试 | 阶段1-7完成后 |
| 9 | 回归验证 | 全部完成后 |
