# 叙华

叙华是一款面向非遗资料检索与讲解的对话应用。当前数据集包含 3610 项、10 类非遗项目，核心链路是：本地资料检索 → 流式回答 → 来源展示 → 实时语音交互。

## 当前能力

- 非遗项目检索：关键词、类别、地区、级别与拼音匹配。
- 流式问答：FastAPI SSE 输出，回答与资料来源共用同一检索核心。
- 连续会话：服务端维护 session / turn，并支持取消当前回答。
- 实时语音：浏览器端 VAD 采集 PCM，经讯飞流式 ASR 转写后进入同一回答链路。
- 中英语音识别：当前只使用讯飞“中英识别大模型”一条 ASR 链路，配置为 `zh_cn` / `mandarin` / `slm`。
- Edge TTS：浏览器先向 `/api/tts` 提交朗读文本换取短期、客户端绑定的 ticket，再通过 `/api/tts/{token}` 获取完整 MP3 音频；前端支持中断与有界重试，不使用浏览器 `speechSynthesis` 降级。
- 数字人界面：React / Vite Web 客户端，由 FastAPI 同源提供构建产物。

## 仓库结构

```text
xuhua/
├─ server/
│  ├─ src/heritage_explorer/   # FastAPI、智能体、检索、语音与 provider
│  └─ tests/                   # Python 测试
├─ web/                        # React / Vite Web 客户端
├─ data/                       # 原始与处理后的非遗数据
├─ tools/                      # 数据构建、本地开发辅助工具
│  └─ dev/start.bat            # Windows 本地启动入口
├─ deploy/                     # Nginx 反向代理配置
├─ docs/                       # 设计与项目文档
├─ pyproject.toml
├─ uv.lock
└─ README.md
```

未来如果增加玩偶端，会新增独立的 `device/` 客户端；服务端与 Web 端不再混在同一个源码目录里。

## 架构

```text
Web / React / Vite
  ├─ 项目检索与筛选
  ├─ POST /api/chat
  ├─ WebSocket /api/voice
  ├─ POST /api/tts
  └─ GET /api/tts/{token}

Server / FastAPI
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

要求：Node.js 22+、Python 3.12，以及 `uv`。统一放在 `Packages` 目录时，`tools/dev/start.bat` 会优先复用 `Packages/runtime/uv/uv.exe` 和 `Packages/.venv`。

```powershell
cd D:\Projects\Packages\叙华
Copy-Item .env.example .env
# 编辑 .env，填入自己的密钥
.\tools\dev\start.bat
```

`tools/dev/start.bat` 会：

1. 检查 `.env`、`uv`、Node/npm 与端口。
2. 在 `web/` 中执行 `npm ci`，准备并校验固定版本的本地唤醒资源，再构建 Web 客户端。
3. 根据根目录 `pyproject.toml` / `uv.lock` 同步 Python 项目与依赖。
4. 用 `.env` 实际导入配置，确认配置完整且类型有效。
5. 通过项目入口 `xuhua` 启动后端，并在健康检查通过后打开浏览器。

`tools/dev/start.bat --check` 只完成环境、构建与配置检查，不启动服务。

## 环境变量

核心运行配置需要显式提供；`.env.example` 给出了本项目当前模板。Web 构建目录固定为仓库内的 `web/dist/client`，不通过环境变量覆盖。

| 变量 | 示例值 | 用途 |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | 服务监听地址 |
| `PORT` | `5050` | 服务端口 |
| `DEBUG` | `0` | 是否开启 Uvicorn reload |
| `DATASET_PATH` | `data/processed/heritage_items.json` | 主数据集 |
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
| `TTS_MAX_CONCURRENCY` | `12` | 单实例同时进行的 TTS 合成上限 |
| `TTS_MAX_PER_MINUTE` | `240` | 单实例每分钟允许启动的 TTS 合成上限 |
| `TTS_MAX_PER_CLIENT_PER_MINUTE` | `80` | 单客户端每分钟允许启动的 TTS 合成上限 |
| `VOICE_MAX_CONCURRENCY` | `4` | 单实例同时保持的实时语音连接上限 |
| `VOICE_MAX_PER_MINUTE` | `30` | 单实例每分钟允许建立的实时语音连接上限 |
| `VOICE_MAX_PER_CLIENT_PER_MINUTE` | `8` | 单客户端每分钟允许建立的实时语音连接上限 |

文字回答、TTS 与实时语音分别使用独立预算。HTTP 超出速率预算时返回 `429`，并发容量耗尽时返回 `503`；实时语音握手被拒绝时使用 WebSocket `1013`。这些预算按应用进程 / 实例计算；当前服务显式以单 worker 运行。

讯飞三个凭据为空时，文字功能仍可使用，页面会把实时语音能力标记为不可用。`AI_API_KEY` 为空时，文字链路使用本地降级回答。

实际 `.env` 不应提交到 Git。

## 开发模式

先准备 `.env`，然后：

```powershell
uv sync --group dev
uv run --env-file .env uvicorn heritage_explorer.api:app --reload --host 127.0.0.1 --port 5050
```

Web 开发服务器首次运行或唤醒资源版本变化后，先显式准备资源：

```powershell
cd web
npm install
npm run prepare:assets
npm run dev
```

`web/public/wake/` 不提交到 Git。`npm run prepare:assets` 只下载清单中固定来源的资源，并在写入前校验内容摘要；`npm run build` 只校验这些资源已经准备好，不再在构建阶段访问网络或调用系统 `tar`。Vite 会代理 `/api` 与 `/healthz` 到本地 FastAPI。

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
| POST | `/api/tts` | 提交朗读文本并获取短期、客户端绑定的 TTS token |
| GET | `/api/tts/{token}` | 使用 token 获取完整 Edge TTS MP3 音频 |

实时语音路径：

```text
浏览器麦克风
  → 浏览器 VAD
  → /api/voice
  → XfyunStream
  → AssistantService / LLM
  → POST /api/tts 获取 ticket
  → GET /api/tts/{token} 获取并播放完整音频
```

本地唤醒词通过独立的 `wake` WebSocket 命令触发固定唤醒确认，不会伪装成普通文本问题进入检索 / LLM 链路。

## 数据维护

源数据位于 `data/source/heritage_source.json`，运行数据可重新生成：

```powershell
uv run python tools/build_dataset.py `
  --input data/source/heritage_source.json `
  --output data/processed/heritage_items.json
```

## 验证

```powershell
uv lock --check
uv run pytest -q
uv run ruff check server/src tools server/tests
uv run python -m compileall -q server/src tools

cd web
npm ci
npm run prepare:assets
npm run lint
npm test
npm run build
```

GitHub `verify` 会缓存已经校验过的唤醒资源，缓存未命中时先执行 `prepare:assets`，随后再进行纯校验式构建；最后直接启动 `xuhua` 进程，对 `/healthz`、`/api/meta` 与首页做冒烟检查。

## 反向代理

仓库保留 `deploy/nginx-xuhua-http.conf`、`deploy/nginx-xuhua-https.conf` 和 `deploy/reload-nginx.sh` 作为 Nginx 反向代理模板。它们针对 `/api/chat`、TTS ticket、TTS synthesis 与 `/api/voice` 提供单 IP 请求速率限制和实时语音连接数限制。

当前仓库不再维护 Docker、Compose、自动服务器部署脚本或实验室一键安装器。若后续确定正式上线方式，再为那一条生产路径单独建立部署配置。

## 安全

浏览器实时语音 WebSocket 会校验 `Origin` 与当前对外站点同源；TTS ticket 绑定签发客户端，泄漏到其他客户端后不能直接复用。不要提交 `.env`、API Key、日志或其他凭据。公开部署前仍应在 DeepSeek、讯飞等服务侧设置额度与并发限制；应用 admission、反向代理限制与供应商额度应同时存在。
