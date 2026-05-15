# 叙华

叙华是一个面向非遗传播与教育展示的任务型 AI 智能体。它把全国非遗项目资料、混合检索、大模型规划、Markdown 回答和数字人播报整合到一个本地 Web 应用里，适合课程展示、竞赛演示和局域网现场讲解。

当前数据集包含 3610 项非遗项目，覆盖 10 个类别。系统可以回答知识问题，也可以完成项目推荐、项目对比、展示策划、研学任务设计和内容转化等更接近真实展示场景的任务。

## 核心能力

- 搜索优先的问答 Agent：每轮对话先由服务端召回高相关候选，再交给大模型判断是直接回答还是继续检索。
- 可控检索轮次：模型每轮最多连续检索 2 次，避免无限循环和长时间等待。
- 多查询精查：模型发起检索时可以一次给出多个 `search_queries`，服务端分别查询后合并资料。
- 上下文追问：服务端保留最近 5 轮对话和已展示条目，支持“再加入一个同类项目”“它有什么特点”这类追问。
- 混合检索：结构化筛选、关键词检索、拼音同音匹配和可选 embedding 语义召回共同参与排序。
- 模型决定展示：问答中间的重点卡片由模型根据任务选择，前端只负责展示，不替模型做业务决策。
- Markdown 展示：答案要求由提示词直接生成可渲染 Markdown，前端负责渲染，后端不再做复杂表格修复。
- 数字人播报：前端状态机驱动等待、思考、播报、结束视频；语音可用浏览器播报，也可接服务端 TTS。

## 适用任务

| 任务 | 示例问题 | 输出形态 |
| --- | --- | --- |
| 事实问答 | `汴绣是什么？` | 分段说明、要点列表 |
| 资料筛选 | `河南省国家级传统美术项目有哪些？` | 条目卡片 + 筛选说明 |
| 项目推荐 | `推荐几个适合亲子互动体验的河南非遗项目` | 推荐表格、推荐理由 |
| 项目对比 | `比较一下罗山皮影戏和桐柏皮影戏` | Markdown 对比表 |
| 展示策划 | `策划一个适合社区活动展示的河南非遗小展` | 展项、动线、互动、物料 |
| 研学任务 | `围绕豫剧设计一个适合中学生的研学任务` | 目标、步骤、评价、注意事项 |
| 内容转化 | `给汴绣生成中英双语介绍` | 双语表格或分段文案 |

## 技术架构

```text
浏览器页面
  ├─ 资料检索侧栏：/api/items
  ├─ 提问面板：/api/ask SSE
  ├─ Markdown 渲染：marked + DOMPurify
  └─ 数字人/语音：视频状态机 + Web Speech / 服务端 TTS

Flask 服务
  ├─ Agent 调度：任务识别、搜索预算、上下文追问
  ├─ 检索层：结构化字段 + 关键词 + 拼音 + embedding RRF
  ├─ 数据层：heritage_items.json + ai_fields.json
  ├─ 大模型层：OpenAI 兼容 chat completion
  └─ 语音层：浏览器播报、火山 TTS、OpenAI TTS 可选
```

语义检索不是 Chroma、FAISS 这类外部向量库，而是本地 JSON embedding 索引：`data/embeddings/heritage_embeddings.json`。索引由维护脚本生成，运行时加载后参与混合排序。

## 快速开始

### 1. 准备环境

```powershell
cd D:\Projects\xuhua
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

Python 3.10 到 3.12 均可。Windows 端推荐使用 PowerShell 和 Edge/Chrome。

### 2. 创建本地配置

```powershell
copy .env.example .env
```

不配置任何 API Key 也可以启动页面和检索资料；需要大模型问答时再填写 `AI_API_KEY`。

常用大模型配置示例：

```env
AI_BASE_URL=https://api.deepseek.com
AI_MODEL=deepseek-v4-flash
AI_TIMEOUT=60
AI_API_KEY=你的密钥
```

### 3. 启动服务

```powershell
python .\app.py
```

默认地址：

```text
http://127.0.0.1:5050
```

如果要让手机或其他设备访问，保持 `.env` 中 `HOST=0.0.0.0`，然后访问：

```text
http://你的电脑内网IP:5050
```

### 4. 可选：启用语义检索

填写 embedding 配置：

```env
SEARCH_USE_EMBEDDING=1
EMBEDDING_BASE_URL=https://api.vectorengine.ai/v1
EMBEDDING_MODEL=text-embedding-3-small
EMBEDDING_API_KEY=你的密钥
```

首次启用或数据集变化后，重建索引：

```powershell
python .\scripts\maintenance\rebuild_embedding_index.py --no-resume
```

PowerShell 包装命令：

```powershell
.\scripts\maintenance\rebuild_embedding_index.ps1 -NoResume
```

重建完成后重启 Web 服务。`data/embeddings/` 不提交到 Git，换机器运行时需要重新生成。

## 重要配置

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | Flask 监听地址；局域网演示用 `0.0.0.0` |
| `PORT` | `5050` | 服务端口 |
| `DATASET_PATH` | `data/processed/heritage_items.json` | 主数据集路径 |
| `AI_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容聊天接口地址 |
| `AI_MODEL` | `deepseek-v4-flash` | 聊天模型名 |
| `AI_API_KEY` | 空 | 留空时大模型能力不可用 |
| `AI_AGENT_PLANNER` | `1` | 是否启用模型规划器 |
| `AI_MAX_CONTEXT_CHARS` | `5200` | 单次发送给模型的资料上限 |
| `SEARCH_USE_EMBEDDING` | `0` | 是否启用 embedding 混合检索 |
| `EMBEDDING_INDEX_PATH` | `data/embeddings/heritage_embeddings.json` | 本地向量索引 |
| `OPENAI_TTS_ENABLED` | `0` | 是否使用 OpenAI 兼容音频接口 |
| `VOLC_TTS_ENABLED` | `1` | 是否启用火山引擎 TTS |
| `TTS_CACHE_DIR` | `tmp/tts` | 服务端生成音频缓存目录 |

完整配置见 [.env.example](.env.example)。

## 数据与索引

主要数据文件：

- `data/processed/heritage_items.json`：3610 项非遗条目，包含标题、类别、地区、级别、摘要、正文和展示标签。
- `data/processed/ai_fields.json`：由离线处理生成的补充字段，用于摘要、特色、历史、文化价值等展示。
- `data/embeddings/heritage_embeddings.json`：本地语义索引，按需生成，不提交。

数据集或 embedding 模型有任何变化时，必须全量重建索引：

```powershell
python .\scripts\maintenance\rebuild_embedding_index.py --no-resume
```

只有上一次构建被网络中断，且数据集没有变化时，才去掉 `--no-resume` 续跑。

## API

| 路径 | 方法 | 说明 |
| --- | --- | --- |
| `/` | GET | 主页面 |
| `/api/meta` | GET | 应用版本、数据集版本、条目数量 |
| `/api/categories` | GET | 类别列表和数量 |
| `/api/items` | GET | 资料检索，支持 `q`、`category`、`province`、`level`、`district`、`keywords`、`limit`、`offset` |
| `/api/items?stream=1` | GET | 资料检索 SSE 版本 |
| `/api/items/<id>` | GET | 条目详情 |
| `/api/ask` | POST | 任务型问答，SSE 返回进度、结果和语音事件 |
| `/api/tts` | POST | 生成服务端 TTS 音频 |
| `/api/tts/stream` | GET | 流式 TTS 音频 |
| `/api/tts/<filename>` | GET | 读取缓存音频 |

`/api/ask` 的最小请求：

```json
{
  "question": "推荐几个适合亲子互动体验的河南非遗项目",
  "voice_enabled": false
}
```

## 目录结构

```text
xuhua/
├── app.py
├── src/heritage_explorer/
│   ├── agent/                  # 搜索优先 Agent、规划器、检索轮次控制
│   ├── ai/                     # RAG 问答、提示词、语音稿生成
│   ├── config.py               # 环境变量配置
│   ├── conversation.py         # 最近 5 轮上下文
│   ├── dataset.py              # 数据加载与序列化
│   ├── embeddings.py           # 本地 embedding 索引
│   ├── retriever.py            # 查询分析、实体/结构化线索提取
│   ├── search.py               # 混合检索与排序
│   ├── transform_config.py     # 内容转化提示词
│   ├── volc_tts.py             # 服务端 TTS
│   └── web.py                  # Flask API
├── data/processed/             # 已处理数据
├── scripts/maintenance/        # 数据维护脚本
├── static/js/                  # 前端模块
├── static/media/               # 数字人视频和提示音频
├── templates/                  # 页面和本地回答模板
├── requirements.txt
└── pyproject.toml
```

## 开发检查

```powershell
python -m pip install -r requirements-dev.txt
python -m compileall src
python -m ruff check src scripts app.py
```

前端脚本语法检查：

```powershell
node --check static/js/ask.js
node --check static/js/search.js
node --check static/js/speech.js
```

如果本地没有 Node，可以跳过前端语法检查，只用浏览器控制台观察错误。

## 常见问题

### 问答失败或模型不回答

先确认 `.env` 中 `AI_API_KEY`、`AI_BASE_URL`、`AI_MODEL` 是否正确。DeepSeek 等 OpenAI 兼容接口使用 `/chat/completions`，不要把 embedding 或 TTS 地址填到聊天接口里。

### 检索结果很多但不相关

确认是否启用了最新的 embedding 索引；数据集更新后必须使用 `--no-resume` 全量重建。场景类问题还会结合硬证据匹配，避免只因为软标签就把项目排到前面。

### 手机访问不了

确认 `.env` 中 `HOST=0.0.0.0`，电脑和手机在同一局域网，Windows 防火墙允许 Python 访问专用网络。部分校园网或路由器会开启 AP 隔离，设备之间会互相不可见。

### 没有语音

浏览器播报需要页面获得一次用户交互。服务端 TTS 需要配置火山引擎或 OpenAI 兼容音频接口；未配置时会自动回退到浏览器 Web Speech。

### Markdown 表格显示异常

当前策略是让模型直接输出规范 Markdown，前端只渲染，不在后端做复杂修复。出现异常时优先检查对应任务提示词，而不是叠加文本后处理。

## 安全

- 不要提交 `.env`、真实 API Key、TTS 凭据或本地日志。
- 大模型、embedding 和 TTS 都可能产生费用，演示前建议限制并发和请求次数。
- 公开展示时请注意非遗资料来源、引用规范和学校/比赛的内容要求。
