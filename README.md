# 叙华

叙华是一个面向牡丹非遗资料的本地 Web 知识库与 AI 问答系统。项目从 `panda_mudan` 中拆分重建，保留非遗数据与数字人展示能力，移除了旧桌面端、语音识别和复杂本地向量模型依赖，更适合课程展示、局域网演示和轻量 RAG 问答原型。

系统围绕“问题输入、资料召回、AI 回答、语音播报、数字人状态展示”这一流程构建。即使不配置模型接口，也可以基于本地数据集返回依据式回答。

## 功能特性

- 本地知识库：内置牡丹非遗条目数据，统一为标题、分类、摘要、正文、别名和来源字段。
- 混合检索：默认使用轻量关键词召回，也可接入 embedding 语义检索提升相关性。
- AI 问答：支持 OpenAI 兼容接口，默认按智谱 API 地址配置。
- 本地兜底：模型不可用或未配置 Key 时，会退回本地依据式回答。
- 自动播报：回答生成后自动调用浏览器语音合成播报，并清理 Markdown 符号。
- 数字人面板：根据待机、检索、回答状态切换三段数字人视频。
- 局域网访问：Flask 服务可监听 `0.0.0.0`，手机和同一网络设备可直接访问。
- 响应式界面：桌面端和手机端都可使用，页面高度控制在视口内，主要区域内部滚动。

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
cd D:\Projects\mudan_heritage_explorer
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
AI_BASE_URL=https://open.bigmodel.cn/api/paas/v4
AI_MODEL=glm-4-flash
AI_TIMEOUT=60
AI_API_KEY=your_api_key
```

不填写 `AI_API_KEY` 也能运行，只是回答会使用本地依据式模式。

5. 如需启用 embedding 语义检索，继续在 `.env` 中填写：

```env
EMBEDDING_BASE_URL=https://api.vectorengine.ai/v1
EMBEDDING_MODEL=text-embedding-3-small
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
| `AI_BASE_URL` | 否 | OpenAI 兼容接口基础地址 | `https://open.bigmodel.cn/api/paas/v4` |
| `AI_MODEL` | 否 | 使用的模型名称 | `glm-4-flash` |
| `AI_TIMEOUT` | 否 | 模型请求超时时间，单位秒 | `60` |
| `AI_MAX_CONTEXT_CHARS` | 否 | 发送给模型的资料上下文最大字符数 | `5200` |
| `EMBEDDING_API_KEY` | 否 | OpenAI 兼容 embedding 接口密钥，留空时不启用语义检索 | 空 |
| `EMBEDDING_BASE_URL` | 否 | embedding 接口基础地址 | `https://api.vectorengine.ai/v1` |
| `EMBEDDING_MODEL` | 否 | embedding 模型名称 | `text-embedding-3-small` |
| `EMBEDDING_TIMEOUT` | 否 | embedding 请求超时时间，单位秒 | `60` |
| `EMBEDDING_BATCH_SIZE` | 否 | 构建索引时每批请求条目数 | `64` |
| `EMBEDDING_WORKERS` | 否 | 构建索引时的并发请求数 | `6` |
| `EMBEDDING_REQUEST_TIMEOUT` | 否 | 构建索引时单个请求的超时时间，单位秒 | `5` |
| `EMBEDDING_MAX_RETRIES` | 否 | embedding 请求失败后的最大重试次数 | `4` |
| `EMBEDDING_RETRY_BACKOFF` | 否 | embedding 重试基础等待秒数 | `3` |
| `EMBEDDING_REQUEST_DELAY` | 否 | 构建索引时每个批次后的等待秒数 | `0` |
| `EMBEDDING_INDEX_PATH` | 否 | 本地向量索引路径 | `data/embeddings/heritage_embeddings.json` |
| `EMBEDDING_TEXT_MAX_CHARS` | 否 | 每条资料送入 embedding 的最大字符数 | `1400` |
| `EMBEDDING_MIN_SCORE` | 否 | 语义召回最低相似度 | `0.15` |
| `SEARCH_USE_EMBEDDING` | 否 | 是否优先使用 embedding 混合检索，`1` 为启用 | `0` |

`.env` 文件只用于本地运行，不应提交到仓库。

## 数据结构

新数据集位于：

```text
data/processed/heritage_items.json
```

每条记录统一为：

```json
{
  "id": "h_xxxxxxxxxx",
  "title": "太极拳（陈氏太极拳）",
  "category": "传统体育、游艺与杂技",
  "summary": "摘要文本",
  "content": "资料原文",
  "aliases": [],
  "search_text": "用于检索的合并文本",
  "source": {
    "legacy_order": 1,
    "files": []
  }
}
```

相比旧项目中分散的数据文件，这种结构更方便检索、展示、维护和后续接入数据库。

## 项目结构

```text
mudan_heritage_explorer/
├── app.py                         # 项目根目录启动器
├── src/heritage_explorer/         # 核心 Python 包
│   ├── ai.py                      # AI 问答、本地兜底回答与提示词组织
│   ├── config.py                  # 环境变量和路径配置
│   ├── dataset.py                 # 数据集加载、分类统计与条目序列化
│   ├── embeddings.py              # OpenAI 兼容 embedding 索引与语义召回
│   ├── search.py                  # 关键词检索和排序
│   └── web.py                     # Flask 页面与 API
├── data/processed/
│   └── heritage_items.json        # 已处理的牡丹非遗知识库数据
├── data/embeddings/               # 本地生成的语义索引，不上传 GitHub
├── static/
│   ├── app.js                     # 前端交互、问答、语音播报和数字人状态
│   ├── styles.css                 # Web UI 样式
│   └── media/                     # 数字人 idle/greet/speak 视频
├── templates/
│   └── index.html                 # 主页面模板
├── scripts/
│   ├── build_dataset.py           # 从旧项目重新生成数据集
│   └── build_embeddings.py        # 调用 embedding 接口生成本地语义索引
├── tests/                         # 单元测试
├── .env.example                   # 配置模板
├── .env                           # 本地配置，不上传 GitHub
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

需要手动准备或本地生成的内容：

- `.env`：不会上传 GitHub，需要从 `.env.example` 复制后填写本地 API Key。
- `.venv/`：不会上传 GitHub，需要按快速开始重新创建虚拟环境。
- `data/embeddings/`：不会上传 GitHub，需要在配置 embedding 后本地生成。
- `logs/`、`__pycache__/`、`.pytest_cache/`、`.ruff_cache/`：运行和测试产物，不需要手动下载。
- `D:\Projects\panda_mudan`：只在重新构建数据集时需要；直接运行本项目不需要旧项目目录，可从“资源下载”中的旧项目整体或 data 包补齐。

## 常用命令

启动 Web 服务：

```powershell
python .\app.py
```

安装为可编辑包后启动：

```powershell
python -m pip install -e .
heritage-explorer
```

重新生成数据集：

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
node --check static/app.js
```

## API 简介

| 路径 | 方法 | 说明 |
| --- | --- | --- |
| `/` | GET | 主页面 |
| `/api/meta` | GET | 数据集版本、来源和数量信息 |
| `/api/categories` | GET | 分类列表 |
| `/api/items` | GET | 条目检索，支持 `q`、`category`、`limit`、`offset`；启用 embedding 后使用混合检索 |
| `/api/items/<item_id>` | GET | 条目详情 |
| `/api/ask` | POST | 基于本地资料和可选模型接口生成回答 |

## 旧数据来源

默认从同级旧项目读取数据：

```text
D:\Projects\panda_mudan
```

可手动指定来源目录：

```powershell
python .\scripts\build_dataset.py --source-root D:\Projects\panda_mudan
```

构建脚本会把旧项目中的牡丹非遗资料整理为 `data/processed/heritage_items.json`。

## 资源下载

本仓库已经包含直接运行所需的 `data/processed/heritage_items.json` 和 `static/media/` 数字人视频。正常克隆仓库后，一般不需要额外下载网盘资源。

如果需要重新构建数据集、恢复旧项目来源文件，或替换数字人素材，可使用以下资源：

- 旧项目整体 -> `D:\Projects\panda_mudan`：<https://pan.baidu.com/s/1wKuYYoeXhD80HnuSkbSl6w>（提取码：`h54t`）
- 旧项目 data -> `D:\Projects\panda_mudan\data/`：<https://pan.baidu.com/s/1ccoQmU1BSTbK_wJVYe5hCw>（提取码：`y3ke`）
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
