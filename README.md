# 叙华

叙华是一款面向非遗资料检索与讲解的对话应用。当前数据集包含 3610 项、10 类非遗项目，核心链路是：本地资料检索 → 流式回答 → 来源展示 → 实时语音交互。

## 当前能力

- 非遗项目检索：关键词、类别、地区、级别与拼音匹配。
- 流式问答：FastAPI SSE 输出，回答与资料来源共用同一检索核心。
- 连续会话：服务端维护 session / turn，并支持取消当前回答。
- 实时语音：浏览器端 VAD 采集 PCM，经讯飞流式 ASR 转写后进入同一回答链路。
- 中英与中文方言：当前只使用讯飞“中英识别大模型”一条 ASR 链路，配置为 `zh_cn` / `mandarin` / `slm`；该服务同时覆盖普通话、英语和中文方言。
- Edge TTS：浏览器先向 `/api/tts` 提交朗读文本换取短期 ticket，再通过 `/api/tts/{token}` 流式播放；前端支持中断、重试与浏览器语音降级。
- 数字人界面：React / Vite 前端，由 FastAPI 同源提供构建产物。

## 架构

```text
React / Vite
  ├─ 项目检索与筛选
  ├─ POST /api/chat
  ├─ WebSocket /api/voice
  ├─ POST /api/tts
  └─ GET /api/tts/{token}

FastAPI
  ├─ AdmissionMiddleware（昂贵服务容量 / 速率预算）
  ├─ AssistantService
  ├─ SearchService（词法 + 拼音检索）
  ├─ SessionStore
  ├─ OpenAI-compatible LLM provider
  ├─ XfyunStream（单路实时 ASR）
  └─ Edge TTS

本地数据
  └─ data/processed/heritage_items.json
```

当前运行时不依赖本地大模型，也不使用 embedding / 向量检索。

## Windows 快速开始

要求：Node.js 22+、Python 3.12，以及 `uv`。统一放在 `Packages` 目录时，`start.bat` 会优先复用 `Packages/runtime/uv/uv.exe` 和 `Packages/.venv`。

```powershell
cd D:\Projects\Packages\叙华
Copy-Item .env.example .env
# 编辑 .env，填入自己的密钥
.\start.bat
```

`start.bat` 会：

1. 检查 `.env`、`uv`、Node/npm 与端口。
2. `npm ci` 并构建前端。
3. 检查并补齐共享 Python 环境依赖。
4. 用 `.env` 实际导入配置，确认配置完整且类型有效。
5. 启动后端，并在健康检查通过后打开浏览器。

`start.bat --check` 只完成环境、构建与配置检查，不启动服务。

### 实验室电脑一键安装

可以直接运行仓库根目录的 `bootstrap-xuhua.cmd`。它会下载并执行 `deploy/install-lab.ps1`，完成 Git、Node、uv、源码、Python 依赖和前端构建准备。当前安装器不会下载任何本地模型。

如果把 `xuhua.env` 放在 `bootstrap-xuhua.cmd` 同目录，安装器会复制它为项目 `.env`；否则首次安装会从 `.env.example` 创建 `.env`。

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\deploy\install-lab.ps1 -SkipLaunch
```

默认安装到 `D:\Projects\Packages\叙华`。

## 环境变量

核心运行配置需要显式提供；`.env.example` 给出了本项目当前模板。公共服务预算另有代码默认值，因此旧部署不会因缺少新变量而无法启动，但生产环境建议显式配置，以便部署状态可审计。

| 变量 | 示例值 | 用途 |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | 服务监听地址 |
| `PORT` | `5050` | 服务端口 |
| `DEBUG` | `0` | 是否开启 Uvicorn reload |
| `DATASET_PATH` | `data/processed/heritage_items.json` | 主数据集 |
| `FRONTEND_DIR` | `frontend/dist/client` | 前端构建目录 |
| `AI_API_KEY` | 空 | OpenAI-compatible LLM 密钥；空值时使用本地降级回答 |
| `AI_BASE_URL` | `https://api.deepseek.com` | LLM API 地址 |
| `AI_MODEL` | `deepseek-flash` | DeepSeek 当前 Flash API 模型名；应用显式使用非思考模式 |
| `AI_TIMEOUT` | `60` | LLM 请求超时 |
| `AI_FIRST_TOKEN_TIMEOUT` | `8` | 首文本等待时间 |
| `AI_FIRST_TOKEN_MAX_ATTEMPTS` | `2` | 首文本最大尝试次数 |
| `AI_MAX_CONTEXT_CHARS` | `5200` | 发送给 LLM 的资料上下文上限 |
| `XF_APP_ID` | 空 | 讯飞应用 ID |
| `XF_API_KEY` | 空 | 讯飞 API Key |
| `XF_API_SECRET` | 空 | 讯飞 API Secret |
| `XF_ASR_HOST` | `iat.xf-yun.com` | 当前中英识别大模型 WebSocket 主机 |
| `CHAT_MAX_CONCURRENCY` | `8` | 单实例同时进行的文字回答上限 |
| `CHAT_MAX_PER_MINUTE` | `60` | 单实例每分钟允许启动的文字回答上限 |
| `CHAT_MAX_PER_CLIENT_PER_MINUTE` | `20` | 单客户端每分钟允许启动的文字回答上限 |
| `TTS_MAX_CONCURRENCY` | `12` | 单实例同时进行的 TTS 流上限 |
| `TTS_MAX_PER_MINUTE` | `240` | 单实例每分钟允许启动的 TTS 流上限 |
| `TTS_MAX_PER_CLIENT_PER_MINUTE` | `80` | 单客户端每分钟允许启动的 TTS 流上限 |
| `VOICE_MAX_CONCURRENCY` | `4` | 单实例同时保持的实时语音连接上限 |
| `VOICE_MAX_PER_MINUTE` | `30` | 单实例每分钟允许建立的实时语音连接上限 |
| `VOICE_MAX_PER_CLIENT_PER_MINUTE` | `8` | 单客户端每分钟允许建立的实时语音连接上限 |

文字回答、TTS 与实时语音分别使用独立预算。HTTP 超出速率预算时返回 `429`，并发容量耗尽时返回 `503`；实时语音握手被拒绝时使用 WebSocket `1013`。这些预算按应用进程 / 实例计算；当前服务显式以单 worker 运行。如果未来水平扩容到多个 worker 或实例，需要先把 ticket、session 与集群级预算迁到共享存储或上游网关。

讯飞三个凭据为空时，文字功能仍可使用，页面会把实时语音能力标记为不可用。`AI_API_KEY` 为空时，文字链路使用本地降级回答。

实际 `.env` 不应提交到 Git。

## 开发模式

先准备 `.env`，然后：

```powershell
uv sync --group dev
uv run --env-file .env uvicorn heritage_explorer.api:app --reload --host 127.0.0.1 --port 5050
```

前端开发服务器：

```powershell
cd frontend
npm install
npm run dev
```

Vite 会代理 `/api` 与 `/healthz` 到本地 FastAPI。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/healthz` | 进程 / 数据加载健康检查 |
| GET | `/api/meta` | 版本、数据规模与能力开关 |
| GET | `/api/categories` | 类别列表 |
| GET | `/api/items` | 项目检索 |
| GET | `/api/items/{item_id}` | 项目详情 |
| POST | `/api/chat` | SSE 流式问答 |
| POST | `/api/chat/{session_id}/turn/{turn_id}/cancel` | 中断指定轮次 |
| WS | `/api/voice` | VAD、讯飞 ASR、连续对话与抢话 |
| POST | `/api/tts` | 提交朗读文本并获取短期 TTS token |
| GET | `/api/tts/{token}` | 使用 token 流式获取 Edge TTS 音频 |

实时语音路径：

```text
浏览器麦克风
  → 浏览器 VAD
  → /api/voice
  → XfyunStream
  → AssistantService / LLM
  → POST /api/tts 获取 ticket
  → GET /api/tts/{token} 流式播放
```

## 数据维护

源数据位于 `data/source/heritage_source.json`，运行数据可重新生成：

```powershell
uv run python scripts/build_dataset.py `
  --input data/source/heritage_source.json `
  --output data/processed/heritage_items.json
```

## 验证

```powershell
uv lock --check
uv run pytest -q
uv run ruff check src scripts tests app.py
uv run python -m compileall -q src scripts app.py

cd frontend
npm ci
npm run lint
npm test
npm run build
```

GitHub `verify` 还会构建生产 Docker 镜像并实际启动容器，对 `/healthz`、`/api/meta` 与首页做冒烟检查。

## Docker / 服务器部署

Docker 运行时同样要求显式提供核心环境配置：

```powershell
docker build -t xuhua .
docker run --rm -p 5050:5050 --env-file .env xuhua
```

`compose.yaml` 用于生产服务器部署，默认读取仓库外的 `/etc/xuhua/xuhua.env`，并由 Compose 显式设置容器内 `HOST=0.0.0.0`、`PORT=5050`。`deploy/xuhua-deploy.sh` 负责拉取 `main`、构建镜像、健康检查与失败回滚。

应用自身的 `AdmissionMiddleware` 是昂贵服务的主保护层。仓库提供的 Nginx 配置还会针对 `/api/chat`、TTS ticket、TTS synthesis 与 `/api/voice` 分别增加单 IP 请求速率限制，并限制同一 IP 的实时语音连接数，作为第二层防护。

## 安全

不要提交 `.env`、`xuhua.env`、API Key、日志或其他凭据。公开部署前仍应在 DeepSeek、讯飞等服务侧设置额度与并发限制；应用 admission、反向代理限制与供应商额度三层应同时存在。
