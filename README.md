# 叙华

叙华是一款非遗资料检索与对话应用。它以本地可核验资料为依据，把 3610 项、10 类非遗项目组织成可搜索、可追问、可引用的数字人讲解体验。

当前版本聚焦一条清晰主链路：**检索资料 → 流式回答 → 展示来源 → 语音播报**。没有配置大模型时，应用仍会基于本地资料给出可用回答。

## 产品能力

- 非遗项目检索：支持关键词、类别、地区、级别与拼音匹配。
- 有来源的流式问答：回答与候选资料来自同一检索核心。
- 连续文本对话：服务端保留最近对话，支持上下文追问。
- 自然轮次：浏览器端 VAD 自动判断用户是否开始、结束说话，无需按住按钮或手动提交录音。
- 连续与抢话：一个浏览器语音 WebSocket 承载多轮上下文；用户开口并被确认后，立即取消正在播报的回答。
- 数字人界面：浅色宣纸质感的全屏三栏工作区，左侧数字人、中间对话、右侧项目资料。
- 实时语音：浏览器采集音频，经讯飞流式 ASR、AssistantService 与 DeepSeek 生成回答，再由 Edge TTS 返回可中断音频。

## 架构

```text
React / Vite 前端
  ├─ 项目检索与筛选
  ├─ POST /api/chat 流式事件
  ├─ 来源与推荐卡片
  ├─ WebSocket /api/voice：浏览器 VAD 与流式语音识别
  └─ GET /api/tts：Edge TTS 音频流与中断播放

FastAPI 服务
  ├─ AssistantService：唯一回答流程
  ├─ SearchService：唯一检索入口
  ├─ SessionStore：session / turn / cancel
  ├─ OpenAI-compatible LLM provider
  ├─ XfyunStream：讯飞流式 ASR
  └─ Edge TTS：流式语音合成

本地数据
  └─ data/processed/heritage_items.json
```

普通文字问答使用稳定事件信封：`type`、`session_id`、`turn_id`、`seq`、`timestamp`、`payload`。实时语音使用同一个 session / turn / cancel 核心：浏览器端 VAD 通过 `/api/voice` 发送 PCM，讯飞返回流式 ASR 结果，回答仍由 `AssistantService` 复用唯一资料检索入口，语音输出通过 `/api/tts` 在浏览器端播放并支持打断。

## 快速开始

要求：Node.js 22+。放在统一的 `Packages` 目录中时，启动器会优先复用
`Packages/runtime/uv/uv.exe`；单独交付时则需要系统已安装 [uv](https://docs.astral.sh/uv/)。
Python 版本由 `.python-version` 锁定为 3.12。启动器与牡丹、田田共用
`Packages/.venv`，只增量安装叙华缺少的依赖，不会用项目同步命令清理共享环境。

```powershell
cd D:\Projects\Packages\叙华
Copy-Item .env.example .env
.\start.bat
```

`start.bat` 会严格按 `package-lock.json` 重建前端，并按 `pyproject.toml` 检查、补齐共享
Python 环境后启动服务。`uv.lock` 仍用于开发、测试与容器构建；共享环境采用增量安装，
避免叙华启动时卸载牡丹、田田的专用依赖。本地启动固定监听 `127.0.0.1:5050`，健康检查
通过后会自动用默认浏览器打开：

```text
http://127.0.0.1:5050
```

`AI_API_KEY` 为空时，文字检索与问答仍可使用本地降级回答；实时语音还需要配置讯飞的三个 `XF_*` 变量，未配置时页面会明确显示语音不可用，不会模拟连接。

### 开发模式

终端一：

```powershell
uv sync --group dev
uv run --env-file .env uvicorn heritage_explorer.api:app --reload --port 5050
```

终端二：

```powershell
cd frontend
npm install
npm run dev
```

Vite 会把 `/api` 与 `/healthz` 代理到本地 FastAPI 服务。

## 配置

完整示例见 `.env.example`。常用变量：

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| `HOST` | `127.0.0.1` | 服务监听地址 |
| `PORT` | `5050` | 服务端口 |
| `DATASET_PATH` | `data/processed/heritage_items.json` | 主数据集 |
| `FRONTEND_DIR` | `frontend/dist/client` | 已构建前端目录 |
| `AI_BASE_URL` | `https://api.deepseek.com` | OpenAI 兼容聊天接口 |
| `AI_MODEL` | `deepseek-v4-flash` | 聊天模型 |
| `AI_API_KEY` | 空 | 大模型密钥 |
| `XF_APP_ID` | 空 | 讯飞流式语音识别应用 ID |
| `XF_API_KEY` | 空 | 讯飞流式语音识别 API Key |
| `XF_API_SECRET` | 空 | 讯飞流式语音识别 API Secret |
| `SEARCH_USE_EMBEDDING` | `0` | 是否启用可选语义索引 |

应用不会自行读取 `.env`。本地命令请使用 `uv run --env-file .env ...`；`start.bat` 已自动处理。

## API

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/healthz` | 健康检查 |
| GET | `/api/meta` | 版本、数据规模与能力开关 |
| GET | `/api/categories` | 类别与数量 |
| GET | `/api/items` | 项目检索 |
| GET | `/api/items/{item_id}` | 项目详情 |
| POST | `/api/chat` | SSE 流式问答 |
| POST | `/api/chat/{session_id}/turn/{turn_id}/cancel` | 中断指定轮次 |
| WS | `/api/voice` | 浏览器端 VAD、讯飞流式 ASR、连续对话与抢话 |
| GET | `/api/tts` | Edge TTS 音频流；通过 `text`、`trace_id`、`segment`、`reason` 标记播报段 |

实时语音由浏览器端 VAD 自动断句。每个明确的用户轮次经讯飞流式 ASR 转成文字后，交给
`AssistantService`；模型使用 `AI_BASE_URL` / `AI_MODEL` 配置的 OpenAI 兼容接口（默认
DeepSeek），回答事实前复用本地检索。回答文本通过 Edge TTS 流式合成，浏览器播放过程中
可以被新的用户语音立即打断。

最小问答请求：

```json
{
  "question": "推荐适合校园展示的河南非遗项目",
  "session_id": null,
  "category": ""
}
```

## 数据维护

源数据位于 `data/source/heritage_source.json`，运行数据由同一个确定性脚本生成：

```powershell
uv run python scripts/build_dataset.py `
  --input data/source/heritage_source.json `
  --output data/processed/heritage_items.json
```

可选 embedding 索引不提交到仓库。需要时执行：

```powershell
uv run --env-file .env python scripts/maintenance/rebuild_embedding_index.py --no-resume
```

## 实时语音链路

当前唯一支持的语音路径是：

```text
浏览器麦克风
  → 浏览器端 VAD（开始/结束说话、抢话判定）
  → /api/voice WebSocket
  → 讯飞流式 ASR（partial / final）
  → AssistantService / DeepSeek（检索、流式回答）
  → Edge TTS（/api/tts）
  → 浏览器可中断播放
```

文字聊天与实时语音共享 `SessionStore`、`turn_id`、取消语义和本地资料检索；语音播放不依赖
独立的第二套回答流程。用户在回答过程中开口并被 ASR 确认后，当前回答、正在播放的音频和
剩余预取音频都应一起取消，再进入新的识别轮次。

## 目录

```text
frontend/                       React 界面与真实视觉素材
src/heritage_explorer/          FastAPI、对话、检索、会话与 providers
data/source/                    原始数据
data/processed/                 运行数据与离线补充字段
scripts/                        数据构建、补充与索引维护
tests/                           API、核心流程、检索、取消与语音传输测试
```

## 验证

```powershell
uv lock --check
uv run pytest -q
uv run ruff check src scripts tests app.py
uv run python -m compileall -q src scripts app.py

cd frontend
npm run build
npm run test:sites
```

## Docker

```powershell
docker build -t xuhua .
docker run --rm -p 5050:5050 --env-file .env -e HOST=0.0.0.0 xuhua
```

镜像会在独立 Node 阶段构建前端，再由 FastAPI 提供同源页面与 API。`render.yaml` 已配置 `/healthz` 健康检查。

### Ubuntu 自动部署

仓库包含 `compose.yaml`、`deploy/xuhua-deploy.sh` 与配套 systemd 单元。生产服务器使用
独立的 `xuhua` 系统用户运行部署任务，配置保存在仓库外的
`/etc/xuhua/xuhua.env`。`xuhua-deploy.timer` 每 30 秒检查一次 `main`，仅接受快进更新；
工作区出现本地修改时会停止部署，构建或健康检查失败时不会继续发布，并在可能时恢复上一镜像。
环境文件的元数据发生变化时，即使代码提交未变，也会用已验证镜像重建容器以加载新配置。
同一失败提交会冷却 10 分钟后再试，新提交不受冷却影响。部署先完成镜像构建，再短暂重建
运行容器并执行数据、API、首页和语音配置冒烟检查；检查失败时会尝试恢复上一份已验证镜像与
Compose 清单。切换期间可能出现短暂连接中断。

腾讯云服务器若无法直连 Docker Hub，可将 `deploy/docker-daemon-tencent.json` 安装为
`/etc/docker/daemon.json` 并重启 Docker。该配置使用腾讯云内网镜像加速地址。
服务器访问 GitHub HTTPS 不稳定时，建议为本仓库配置服务器专用的只读 Deploy Key，并将
`origin` 切换为 `ssh://git@ssh.github.com:443/RinoPaw/xuhua.git`。私钥应只保存在
`/var/lib/xuhua/.ssh`，权限设为 `0600`；同时通过 `core.sshCommand` 固定该私钥、
`known_hosts` 和严格主机校验。Deploy Key 不应授予写权限，也不要提交到仓库。

首次部署需预先安装 Docker、Compose、Git、Python、`flock`、Nginx 与 Certbot，并建立运行账户及目录。
以下顺序先安装生产配置和 systemd 单元，再手动完成一次发布；只有首次发布验证成功后才启用自动更新：

```bash
sudo apt-get update
sudo apt-get install -y git python3 util-linux coreutils nginx certbot
sudo useradd --system --user-group --home-dir /var/lib/xuhua --create-home --shell /usr/sbin/nologin xuhua
sudo usermod -aG docker xuhua
sudo install -d -o xuhua -g xuhua -m 0750 /opt/xuhua /var/lib/xuhua
sudo install -d -o root -g xuhua -m 0750 /etc/xuhua
sudo -u xuhua git -c http.version=HTTP/1.1 clone -4 --branch main --single-branch https://github.com/RinoPaw/xuhua.git /opt/xuhua/repo
# 先把生产环境变量写入 /etc/xuhua/xuhua.env，并设置为 root:xuhua、0640。
sudo install -o root -g root -m 0644 /opt/xuhua/repo/deploy/xuhua-deploy.service /etc/systemd/system/
sudo install -o root -g root -m 0644 /opt/xuhua/repo/deploy/xuhua-deploy.timer /etc/systemd/system/
sudo systemd-analyze verify /etc/systemd/system/xuhua-deploy.service /etc/systemd/system/xuhua-deploy.timer
sudo systemctl daemon-reload
sudo systemctl start xuhua-deploy.service
sudo systemctl enable --now xuhua-deploy.timer
```

将生产配置写入 `/etc/xuhua/xuhua.env` 并设为 `root:xuhua`、`0640`。容器只绑定
`127.0.0.1:5050`，公网入口由 Nginx 提供。域名 `xuhua.520207.xyz` 的 DNS 必须指向源站；
使用 Cloudflare 代理时，SSL/TLS 模式应设为“完全（严格）”。仓库中的 HTTP 配置先提供应用和
ACME 校验路径，证书签发后再切换到 HTTPS：

```bash
sudo install -d -o www-data -g www-data -m 0755 /var/www/letsencrypt
sudo install -o root -g root -m 0644 /opt/xuhua/repo/deploy/nginx-xuhua-http.conf /etc/nginx/sites-available/xuhua
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sfn /etc/nginx/sites-available/xuhua /etc/nginx/sites-enabled/xuhua
sudo nginx -t
sudo systemctl enable --now nginx
sudo certbot certonly --webroot -w /var/www/letsencrypt --cert-name xuhua.520207.xyz -d xuhua.520207.xyz --agree-tos --non-interactive --register-unsafely-without-email
sudo install -o root -g root -m 0644 /opt/xuhua/repo/deploy/nginx-xuhua-https.conf /etc/nginx/sites-available/xuhua
sudo install -o root -g root -m 0755 /opt/xuhua/repo/deploy/reload-nginx.sh /etc/letsencrypt/renewal-hooks/deploy/reload-nginx
sudo nginx -t
sudo systemctl reload nginx
sudo systemctl enable --now certbot.timer
sudo certbot renew --dry-run
```

首次安装后可查看状态与日志：

```bash
sudo systemctl status xuhua-deploy.timer
sudo journalctl -u xuhua-deploy.service -n 100 --no-pager
sudo docker ps --filter name=xuhua
```

仓库里的 systemd 单元、Nginx 配置和证书续期钩子不会自动覆盖系统配置。相关文件发生变更时，
需要管理员先审阅，再重新执行对应的 `install`、配置检查和重载。维护期间应先执行：

```bash
sudo systemctl disable --now xuhua-deploy.timer
sudo systemctl stop xuhua-deploy.service
```

维护完成后用 `sudo systemctl enable --now xuhua-deploy.timer` 恢复自动更新。部署用户拥有
Docker 组权限，这等价于较高的宿主机权限，因此 GitHub `main` 的写权限必须严格控制。

## 安全

- 不要提交 `.env`、API Key、日志或本地语义索引。
- 大模型与 embedding 可能产生费用；公开部署前应在供应商侧设置额度与并发限制。
- 答案基于本地资料，但正式发布仍应复核来源、署名与使用授权。
