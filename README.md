# 叙华

面向全国非遗数据的非遗传播任务型 AI 智能体。内置 4415 项非遗条目（11 个类别），覆盖查询、筛选、比较、推荐、任务策划和内容转化等完整链路，适合课程展示、局域网演示和非遗教育场景。

系统围绕"问题理解 → 资料召回 → 任务路由 → 答案生成 → 语音播报 → 数字人状态展示"这一流程构建。不依赖任何外部 API Key 也能正常运行——所有功能均有本地规则/模板回退。

## 功能特性

### 知识查询
- 全国非遗知识库：4415 项非遗条目，覆盖 11 个类别，含标题/地区/级别/简介/正文/特色/历史/文化价值等结构化字段。
- 混合检索：关键词 + 拼音同音匹配 + 可选 embedding 语义检索，RRF 排名融合。
- 多维筛选：支持按类别、省份、级别、区县、关键词自由组合过滤。
- 项目卡片：检索结果以结构化卡片展示，点击可查看详情、场景标签、受众标签和完整正文。

### 分析选择
- 同类对比：多个非遗项目的多维度结构化对比（类别/级别/地区/教育价值/互动潜力）。
- 项目推荐：基于场景（校园/社区/展馆/研学/文创）和受众标签的规则打分推荐。

### 任务策划
- 校园展示策划：自动筛选 5+ 展项，生成展示形式/核心讲解/互动环节/所需物料方案。
- 社区活动策划：同上流程，适配社区场景。
- 研学任务生成：7 段教案模板，按受众年龄（儿童/青少年/大学生/亲子）自适应调整。

### 内容转化
- 非遗翻译：中译英，支持 LLM 全译或本地模板摘要。
- 年轻化文案：社交媒体风格改写，口语化、带 emoji。
- 文创灵感：基于非遗元素的设计简报（灵感来源/视觉元素/产品类型/目标受众）。

### 通用能力
- AI 问答：支持 OpenAI 兼容接口（DeepSeek、智谱等），流式 SSE 输出。
- 本地兜底：所有功能模型不可用时自动退回本地规则/模板回答。
- 自动播报：浏览器 Web Speech API + 可选服务端 TTS（火山引擎/OpenAI），一键切换。
- 数字人面板：四段视频状态机（idle/thinking/speaking/farewell），交叉淡入淡出。
- 局域网访问：Flask 监听 `0.0.0.0`，同一网络设备直接访问。
- 响应式界面：桌面端和移动端自适应，视口内滚动。

## 运行环境

- Windows 10 / 11
- Python 3.10 - 3.12
- 现代浏览器，推荐 Edge 或 Chrome
- 可选：OpenAI 兼容大模型接口 API Key
- 可选：OpenAI 兼容 embedding 接口 API Key

项目不依赖 PySide6、FAISS、PyAudio、Vosk、Edge-TTS 等旧桌面端组件。浏览器语音播报使用系统和浏览器自带的 Web Speech API，实际音色取决于本机环境。语义检索使用远程 embedding 接口，不需要下载旧项目的本地 `models/` 目录。

## 快速开始

1. 创建并激活虚拟环境：

```powershell
cd D:\Projects\xuhua
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
```

如果本机没有 Python 3.12，也可以使用已安装的 3.10 或 3.11。

2. 安装依赖：

```powershell
python -m pip install -r requirements.txt
```

3. 创建本地配置文件：

```powershell
copy .env.example .env
```

4. 如需接入大模型，编辑 `.env` 并填写 API Key：

```env
AI_BASE_URL=your_chat_base_url
AI_MODEL=your_chat_model
AI_TIMEOUT=60
AI_API_KEY=your_api_key
```

不填写 `AI_API_KEY` 也能运行，只是回答会使用本地依据式模式。

5. 如需启用 embedding 语义检索，继续在 `.env` 中填写：

```env
EMBEDDING_BASE_URL=your_embedding_base_url
EMBEDDING_MODEL=your_embedding_model
EMBEDDING_TIMEOUT=60
EMBEDDING_BATCH_SIZE=8
EMBEDDING_WORKERS=6
EMBEDDING_REQUEST_TIMEOUT=5
EMBEDDING_MAX_RETRIES=4
EMBEDDING_RETRY_BACKOFF=3
EMBEDDING_REQUEST_DELAY=2
SEARCH_USE_EMBEDDING=1
EMBEDDING_API_KEY=your_embedding_api_key
```

然后生成本地向量索引：

```powershell
python .\scripts\build_embeddings.py
```

不生成索引也能运行，系统会自动退回关键词检索。

6. 启动服务：

```powershell
python .\app.py
```

默认访问地址：

```text
http://127.0.0.1:5050
```

同一局域网设备访问时，把地址中的 `127.0.0.1` 换成电脑的内网 IP：

```text
http://你的电脑内网IP:5050
```

例如电脑 IP 是 `192.168.1.141`，手机访问：

```text
http://192.168.1.141:5050
```

## 配置说明

项目会优先读取系统环境变量，也会自动加载项目根目录下的 `.env` 文件。

| 变量名 | 必填 | 说明 | 默认值 |
| --- | --- | --- | --- |
| `HOST` | 否 | Flask 监听地址。局域网访问建议使用 `0.0.0.0` | `127.0.0.1` |
| `PORT` | 否 | Flask 监听端口 | `5050` |
| `DEBUG` | 否 | 是否开启调试模式，`1` 为开启 | `0` |
| `DATASET_PATH` | 否 | 非遗数据集路径 | `data/processed/heritage_items.json` |
| `AI_API_KEY` | 否 | OpenAI 兼容接口密钥，留空时使用本地依据式回答 | 空 |
| `AI_BASE_URL` | 否 | OpenAI 兼容接口基础地址 | 空 |
| `AI_MODEL` | 否 | 使用的模型名称 | 空 |
| `AI_TIMEOUT` | 否 | 模型请求超时时间，单位秒 | `60` |
| `AI_MAX_CONTEXT_CHARS` | 否 | 发送给模型的资料上下文最大字符数 | `5200` |
| `EMBEDDING_API_KEY` | 否 | OpenAI 兼容 embedding 接口密钥，留空时不启用语义检索 | 空 |
| `EMBEDDING_BASE_URL` | 否 | embedding 接口基础地址 | 空 |
| `EMBEDDING_MODEL` | 否 | embedding 模型名称 | 空 |
| `EMBEDDING_TIMEOUT` | 否 | embedding 请求超时时间，单位秒 | `60` |
| `EMBEDDING_BATCH_SIZE` | 否 | 构建索引时每批请求条目数 | `64` |
| `EMBEDDING_WORKERS` | 否 | 构建索引时的并发请求数 | `6` |
| `EMBEDDING_REQUEST_TIMEOUT` | 否 | 构建索引时单个请求的超时时间，单位秒 | `5` |
| `EMBEDDING_MAX_RETRIES` | 否 | embedding 请求失败后的最大重试次数 | `4` |
| `EMBEDDING_RETRY_BACKOFF` | 否 | embedding 重试基础等待秒数 | `3` |
| `EMBEDDING_REQUEST_DELAY` | 否 | 构建索引时每个批次后的等待秒数 | `0` |
| `EMBEDDING_INDEX_PATH` | 否 | 本地向量索引路径 | `data/embeddings/heritage_embeddings.json` |
| `EMBEDDING_TEXT_MAX_CHARS` | 否 | 每条资料送入 embedding 的最大字符数 | `1400` |
| `EMBEDDING_MIN_SCORE` | 否 | 低层语义评分的备用最低相似度；应用混合检索使用排名融合，不依赖硬阈值 | `0.15` |
| `SEARCH_USE_EMBEDDING` | 否 | 是否优先使用 embedding 混合检索，`1` 为启用 | `0` |

`.env` 文件只用于本地运行，不应提交到仓库。

## 数据结构

新数据集位于：

```text
data/processed/heritage_items.json
```

每条记录统一为结构化 HeritageItem：

```json
{
  "id": "h_xxxxxxxxxx",
  "title": "太极拳（陈氏太极拳）",
  "family": "太极拳",
  "category": "传统体育、游艺与杂技",
  "province": "河南省",
  "city": "焦作市",
  "district": "温县",
  "level": "人类非物质文化遗产代表作名录",
  "summary": "摘要文本",
  "content": "资料原文",
  "display_forms": ["表演", "体验"],
  "history": "历史背景文本",
  "features": "核心特色文本",
  "cultural_value": "文化价值文本",
  "suitable_scenarios": ["校园展示", "社区活动"],
  "target_audience": ["青少年", "大学生"],
  "display_difficulty": "低",
  "interaction_potential": "高",
  "education_value": "高",
  "cultural_keywords": ["武术", "养生", "哲学"],
  "search_text": "用于检索的合并文本",
  "source": {"files": [], "urls": []}
}
```

软标签（scenarios/audience/difficulty/interaction/education）由规则推断，用于推荐和筛选。

## 项目结构

```text
xuhua/
├── app.py                         # 项目根目录启动器
├── src/heritage_explorer/         # 核心 Python 包
│   ├── agent/                     # Agent 意图路由、规划器与任务处理器
│   │   ├── __init__.py            #   主处理器: fact_qa / comparison / recommendation /
│   │   │                          #     exhibition_plan / study_task / content_transform / browse
│   │   ├── planner.py             #   LLM 规划器 prompt 构建（任务分类 + 改写）
│   │   ├── models.py              #   任务类型与决策模型
│   │   └── task_config.py         #   任务配置与提示词
│   ├── ai/                        # AI 问答、语音生成与提示词
│   │   ├── __init__.py            #   RAG 问答入口（构建上下文 + 调用模型）
│   │   ├── prompts.py             #   系统提示词（QA + Speech）
│   │   └── speech.py              #   服务端 TTS 编排
│   ├── config.py                  # 环境变量和路径配置
│   ├── dataset.py                 # 数据集加载、分类统计与条目序列化
│   ├── embeddings.py              # OpenAI 兼容 embedding 索引与语义召回
│   ├── extractor.py               # 结构化字段提取与软标签推断
│   ├── http_client.py             # 统一 HTTP 层（httpx + zhipuai 自动路由）
│   ├── item_cards.py              # 条目卡片渲染（前端侧边栏卡片）
│   ├── retriever.py               # 查询分析、实体/场景/约束提取、语义正则
│   ├── search.py                  # 关键词检索 + 拼音匹配 + RRF 混合排序
│   ├── volc_tts.py                # 火山引擎服务端 TTS
│   └── web.py                     # Flask 页面与 API
├── data/processed/
│   └── heritage_items.json        # 4415 项非遗数据
├── data/embeddings/               # 本地生成的语义索引，不上传 GitHub
├── static/
│   ├── styles.css                 # Web UI 样式
│   ├── js/                        # 前端 ES 模块（9 个模块）
│   │   ├── main.js                #   入口 & 事件绑定
│   │   ├── ask.js                 #   问答 SSE 流处理
│   │   ├── search.js              #   侧边栏检索与详情
│   │   ├── speech.js              #   语音切换与三态状态机
│   │   ├── human.js               #   数字人视频四态调度
│   │   ├── markdown.js            #   Markdown 渲染
│   │   ├── ui.js                  #   UI 交互
│   │   ├── state.js               #   全局状态管理
│   │   └── consts.js              #   常量与能力检测
│   ├── media/                     # 数字人视频素材
│   └── vendor/                    # 第三方库（marked, DOMPurify）
├── templates/
│   ├── index.html                 # 主页面
│   ├── study_task.md.j2           # 研学教案本地模板
│   ├── exhibition_plan.md.j2      # 展示策划本地模板
│   └── transform_local.md.j2      # 内容转化本地模板（含翻译/年轻化/文创/讲解词）
├── scripts/
│   ├── build_dataset.py           # 从旧项目迁移数据集
│   ├── build_embeddings.py        # 生成本地语义索引
│   ├── build_embeddings.ps1       # embedding 构建 PS 包装
│   ├── import_ihchina_projects.py # 从 ihchina.cn 批量导入
│   └── migrate_dataset.py         # 数据集格式迁移
├── tests/                         # 12 个测试文件
├── .env.example
├── requirements.txt
└── README.md
```

需要手动准备或本地生成的内容：

- `.env`：不会上传 GitHub，需要从 `.env.example` 复制后填写本地 API Key。
- `.venv/`：不会上传 GitHub，需要按快速开始重新创建虚拟环境。
- `data/embeddings/`：不会上传 GitHub，需要在配置 embedding 后本地生成。
- `logs/`、`__pycache__/`、`.pytest_cache/`、`.ruff_cache/`：运行和测试产物，不需要手动下载。
- `D:\Projects\panda_mudan`：只在重新构建数据集时需要；直接运行本项目不需要旧项目目录，可从"资源下载"中的旧项目整体或 data 包补齐。

## 常用命令

启动 Web 服务：

```powershell
python .\app.py
```

安装为可编辑包后启动：

```powershell
python -m pip install -e .
xuhua
```

从旧项目迁移数据集：

```powershell
python .\scripts\build_dataset.py --source-root D:\Projects\panda_mudan
```

生成 embedding 语义索引：

```powershell
.\scripts\build_embeddings.ps1
```

如果接口限速，可以调小批次并增加批次间隔：

```powershell
python .\scripts\build_embeddings.py --batch-size 4 --delay 3
```

如果接口单次响应较快但偶发卡住，可以使用并发构建，并让慢请求 5 秒超时后重试：

```powershell
.\scripts\build_embeddings.ps1 -BatchSize 64 -Workers 6 -RequestTimeout 5
```

运行开发检查：

```powershell
python -m pip install -r requirements-dev.txt
python -m ruff check src tests scripts app.py
python -m pytest -q
```

检查前端脚本语法：

```powershell
node --check static/js/*.js
```

## API 简介

| 路径 | 方法 | 说明 |
| --- | --- | --- |
| `/` | GET | 主页面 |
| `/api/meta` | GET | 数据集版本、条目数、类别数 |
| `/api/categories` | GET | 分类列表及每类条目数量 |
| `/api/items` | GET | 条目检索，支持 `q`/`category`/`province`/`level`/`district`/`keywords`/`limit`/`offset`；可选 embedding 混合检索 |
| `/api/items/<id>` | GET | 条目完整详情 |
| `/api/ask` | POST | 任务型问答，SSE 流式输出（含进度/结果/语音事件） |
| `/api/tts` | POST | 服务端 TTS，生成音频文件并返回 URL |
| `/api/tts/stream` | GET | 流式 TTS 音频 |
| `/api/tts/<filename>` | GET | 获取缓存的 TTS 音频文件 |

## 数据来源

当前数据集来自 ihchina.cn 全国非遗项目数据，通过 `scripts/import_ihchina_projects.py` 导入并结构化处理为 `data/processed/heritage_items.json`。

如需从旧项目（牡丹非遗）重新构建数据集：

```powershell
python .\scripts\build_dataset.py --source-root D:\Projects\panda_mudan
```

## 资源下载

本仓库已经包含直接运行所需的 `data/processed/heritage_items.json` 和 `static/media/` 数字人视频。正常克隆仓库后，一般不需要额外下载网盘资源。

如果需要重新构建数据集、恢复旧项目来源文件，或替换数字人素材，可使用以下资源：

- 旧项目整体 -> `D:\Projects\panda_mudan`：<https://pan.baidu.com/s/1wKuYYoeXhD80HnuSkbSl6w>（提取码：`h54t`）
- 旧项目 data -> `D:\Projects\panda_mudan\data\`：<https://pan.baidu.com/s/1ccoQmU1BSTbK_wJVYe5hCw>（提取码：`y3ke`）
- 旧项目动画素材 -> 可按需提取到 `static/media/`：<https://pan.baidu.com/s/1zQyRXYG6JfvfzVDprm96cQ>（提取码：`wsv6`）

旧项目中的 `models/`、`assets/audio/`、`assets/icons/` 等资源不再是本项目运行必需项；只有继续维护旧桌面端时才需要。

## 常见问题

### 手机无法访问页面

确认 `.env` 中 `HOST=0.0.0.0`，并检查 Windows 防火墙是否允许 Python 通过专用网络。宿舍路由器如果开启了 AP 隔离，同一 Wi-Fi 下的设备也可能互相访问不到。

### 模型接口暂不可用

检查 `AI_API_KEY`、`AI_BASE_URL`、`AI_MODEL` 是否填写正确。模型请求超时或网络不可达时，系统会自动退回本地依据式回答。

### embedding 检索没有生效

确认 `.env` 中 `EMBEDDING_API_KEY` 已填写，`SEARCH_USE_EMBEDDING=1`，并且已经执行过 `python .\scripts\build_embeddings.py`。如果索引不存在或接口不可用，系统会自动退回关键词检索。

### 没有语音播报

确认浏览器允许页面播放声音，并使用支持 Web Speech API 的浏览器。部分手机浏览器会限制自动语音播放，需要先与页面发生一次点击交互。

### 回答里出现 Markdown 符号

前端会把回答渲染为 Markdown，并在播报前清理标题、加粗、列表等符号。如果仍出现异常，优先检查模型返回内容是否包含特殊格式。

## 安全说明

- 不要提交 `.env` 或任何真实 API Key。
- 如果密钥曾出现在公开仓库历史中，建议立即到服务商后台轮换。
- 大模型接口可能产生调用费用，请以对应服务商说明为准。
- 公开演示非遗资料时，应注意资料来源、版权和学校展示要求。
