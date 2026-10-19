# 语音链路诊断

服务器、浏览器分别使用 Python logging / browser console 记录阶段事件，无需新增第三方监控服务。独立 Uvicorn 启动时，如果根 logger 没有 handler，应用会启用带时间戳的 INFO 标准错误输出；若宿主已有 logging 配置则遵循宿主配置，不修改其 handler。

## 关联一次语音会话

- WebSocket 服务端消息有 `connection_id` 和递增 `sequence`；单次 ASR 以 `utterance_id` 区分，助手回答以 `turn_id` 区分。
- 服务端按 `connection=<id>` 过滤，依次找 `voice.connection.open`、`voice.asr.connect.*`、`voice.asr.finalize`、`voice.asr.release`、`voice.llm.first_delta`、`voice.llm.finish`、`voice.chat.release`、`voice.connection.close`。
- 浏览器控制台的 `[叙华][latency ...]` 把 `connection`、`utterance`、`turn`、`tts_trace` 放在同一行；用 `tts_trace` 在服务器中查找 `tts.request.start`、`tts.first_audio_chunk`、`tts.complete`、`tts.finish`。
- 浏览器额外记录 `[叙华][voice.outcome ...] result=<状态>`，覆盖成功、失败、被拒绝、取消、打断、断连与被新语音取代，不因尚未播放就丢失样本。每次有效语音只生成一条终态记录；已经开始播放的尝试另有一条首播放延迟记录。
- `voice.asr.release` 和 `voice.chat.release` 记录真实租约持有时长，包括取消与断连；`remaining` 是该连接作用域尚未释放的 ASR 资源数，不是所有客户端的并发数。

## 聊天页短呼叫

聊天页开启麦克风后保持连续对话，不进入 Persona 的空闲休眠。聊天页复用现有 ASR 的短呼叫判断，不另外占用独立讯飞唤醒终端：单独叫“叙华”“你好叙华”“叙华你在吗”，服务端记录 `voice.address.classification decision=ack` 和 `voice.address.ack`，直接返回带 `acknowledgement: true` 的 `assistant.delta/done`，不请求检索或模型，也不写入模型会话历史。带实际问题的呼叫仍走正常问答。

两页都在用户点击开启麦克风时解锁音频。短呼叫播放缓存的小露“我在。”音频，结束后立即继续听，不采用普通长回答结束后的 450ms 输入屏蔽。该路径仍需等 ASR 完成，耗时应与 Persona 原生唤醒分开统计。

验收：开启聊天页麦克风，连续两次单独叫名字，每次应只回一句“我在。”；接着说“叙华，介绍一下剪纸”和不带名字的问题，应正常回答；在“我在。”播放中提问，应能替换旧音频；关闭麦克风后应停止采集，恢复后继续对话。自动测试覆盖服务端分类及浏览器控制器生命周期，真实设备的权限和声音仍需实际试听。

## 耗时口径

| 字段 | 口径 |
| --- | --- |
| `voice.connection.close duration_ms` | WebSocket 会话存续时间，包含资源清理 |
| `voice.asr.connect.ready` | 单次讯飞连接建立耗时（秒） |
| `voice.asr.finalize finalize_ms` | ASR 收尾任务启动至完成/失败/取消，包含等待建立连接 |
| `voice.asr.release held_ms` | ASR 从创建任务到释放租约 |
| `voice.llm.first_delta elapsed_ms` | 服务端回答任务开始到首次非空文本增量；包含检索等上游工作，不单指模型生成时间 |
| `voice.llm.finish elapsed_ms` | 服务端回答任务至结束、取消或失败 |
| `voice.chat.release held_ms` | 回答租约持有时长 |
| `tts.first_audio_chunk` / `tts.complete` | 服务端收到 TTS 请求后到第一块音频 / 全部音频生成耗时（秒） |
| `tts.finish outcome elapsed_ms bytes first_chunk` | TTS 生成流程的终态：`completed`、`failed` 或 `cancelled`，包含流式取消与中途失败，统计已生成字节数，不含音频正文 |
| `[叙华][latency ...]` | 浏览器使用 `performance.now()` 记录语音结束、识别完成、回答首段、TTS 请求、`loadeddata` 与实际 `playing`；均为浏览器本地毫秒差，`first_audio` 代表 HTMLAudioElement 已加载可解码数据，不能视为服务器网络首块 |
| `[叙华][voice.outcome ...]` | 从上一次本地语音活动到终态的经过时间、结果类别、各阶段是否到达；未完成播放的尝试也要计入统计分母 |

服务端与浏览器各自使用单调时钟，**不要直接相减跨机器的时间戳**。某个环节未发生（例如没有流式增量）时，浏览器以 `-` 标记未知，而非编造零毫秒。

## 隐私与测试边界

诊断日志只需 ID、状态、耗时和文字长度，避免记录原始语音 PCM、完整 ASR 转写、提示词、回答正文、鉴权材料或 TTS ticket token。服务器仍可能由第三方库独立打印日志，部署时要检查整体日志收集策略。

CI 校验日志结构与模拟生命周期；它无法证明真实设备的麦克风权限、WASM 模型加载、讯飞与 DeepSeek 的网络性能。

## 低延迟路径的诊断

- 首次 TTS 播放请求可带 `stream=1`。服务端只等第一块有效 MP3 就开始传输；`tts.first_audio_chunk` 记录开始生成到首块，`tts.complete` 记录供应商完整生成的时间，两者差值体现原先完整缓冲路径的可重叠部分。
- HTTP 流开始后若供应商失败，服务器记录 `tts.provider.interrupted` 并中断响应。首块前失败仍是 HTTP 502；`tts_retry` 请求自动使用完整缓冲。不要把首块到达服务器的时间等同于浏览器实际开始播放。
- ASR `voice.asr.finished` 为最终识别结果已经取得的时间；`voice.asr.release` 是后续连接关闭与租约释放完成的时间，允许发生在 `voice.llm.first_delta` 之后。不要用较晚的 release 时间推断回答还未开始。
- 对比优化前后应收集同设备、同网络、相近提问的多个样本（至少观察 P50/P95、首音频开始时间和出错率）。CI 只覆盖受控模拟，不验证 Chromium 真机渐进缓冲行为或外部网络性能。


## 怎样采集与核对日志

- 本地启动（仓库根目录）：`uv run --env-file .env uvicorn heritage_explorer.api:app --host 127.0.0.1 --port 5050`。服务端诊断写入标准错误输出；需要保留记录时可用 `2>&1 | tee voice-server.log`（请勿提交日志文件或共享原始日志）。
- 在浏览器开发者工具 Console 启用 **Info** 并打开 **Preserve log**，连续执行多轮“唤醒—提问—回答—打断—断连”，导出或保存控制台消息用于本地分析。浏览器端日志不自动持久保存，也不上传远端；页面刷新可能丢失历史记录。
- 对每一次成功首播，找到 `[叙华][latency ...]` 与相应 `[叙华][voice.outcome ...]`；用 `connection`、`turn`、`utterance` 关联服务端 ASR/LLM，用 `tts_trace` 关联服务端 TTS。服务器与浏览器必须分别计算各阶段用时。
- 不应只对成功播放样本计算总延迟；统计 P50/P95 时同时报告 `voice.outcome` 的总尝试数、成功/失败/取消数，并单独计算成功首播的总延迟 P50/P95。网络失败、打断和未播放的尝试没有完整延迟值，不能记为 0。
- `tts.finish outcome=cancelled` 表示上游合成在取消或关闭时结束；不一定意味着用户主动中断，原因要结合浏览器 `voice.outcome` 与 WebSocket 关闭日志判断。

日志安全：`reason` 仅允许固定格式的短运行状态码，其他内容统一标作 `unknown`，不会把浏览器遇到的完整异常信息直接写入延迟汇总。应用自身的诊断日志不记录转写、回答、音频和 TTS ticket；如需向他人提供日志，还应先检查代理及第三方库产生的其他内容。


## 排查 Edge TTS WebSocket 握手失败

当日志出现 `tts.provider.failed reason=WSServerHandshakeError` 时，服务端会同时记录安全的 `status=<HTTP 状态码或 ->`，例如 `status=403`。这是供应商握手失败，不是本地 `/api/tts/{token}` 路由的 HTTP 502 本身。为保护凭据，不能记录原始异常的 URL 或查询串。若 `status=403`，优先排查 Edge TTS 上游鉴权、IP/地区限制和依赖版本；若 `status=429`，排查请求速率。单次失败不能证明并发或短句就是原因。

中文首播不会再把不足 6 个字符的已完成短句单独提交 TTS；需要等待更多文字以合并成一段（如果整条回答已结束，仍会完整合成短回答）。这样避免极短首段带来的额外网络握手，但不保证消除上游握手失败。保留 `segment=0/1`、`trace`、`chars`，便于比较前后实际失败率和首播延迟。


## TTS Ticket 的访问日志脱敏

Uvicorn 的默认访问日志可能显示 `GET /api/tts/<token>?stream=1`；即使业务代码从不主动记录 token，这条 HTTP 访问日志也会泄露一次性票据。应用启动时会对 `uvicorn.access` 添加幂等过滤器，将实际票据路径统一记录为 `GET /api/tts/<redacted>`，仍保留 HTTP 状态码。此过滤器不影响代理服务器、反向代理、自定义 ASGI server 或浏览器网络面板各自产生的日志；公开分享历史日志前请单独清理旧票据。


## 连续短语音的 VAD 收尾

真实日志中短暂停顿导致同一问题多次开启讯飞 ASR、并出现 0 字结果。现在短语音（累计发声时间少于 1200ms）采用 720ms 静音截止，较长语音保留 420ms 静音截止；这是稳定性与响应延迟之间的权衡，实际效果需要通过新日志比较。同一发言中的续说在截止前复用当前 ASR 连接。回答正在生成或等待 TTS 的阶段也采用较严格的打断起始门槛（0.022 RMS、160ms 连续超阈值），以降低微弱音量误唤起；明显的人声仍可打断。上述阈值不是声纹识别或回声消除，不应把所有打断都视为噪声。


## 本地开发：不依赖 Console 的完整诊断

Windows `tools/dev/start.bat` 会对本地运行的服务设置 `XUHUA_LOCAL_VOICE_DIAGNOSTICS=1`。从此 Python 终端会额外出现 `voice.dialogue`：每个 ASR 段的原始文本、最终合并的 raw/canonical 文本、`voice.address.classification` 的 ack/question 决策、固定应答以及 LLM 最终回答。由此可以判断“叙华”被误转写成了什么、为什么没有唤醒。

同时，浏览器通过同源本地 HTTP 诊断接口向服务端报告本地 Sherpa-ONNX 唤醒监听/检测、疑似人声未命中、远端连接状态、TTS 实际播放/失败等事件，打印为 `voice.browser`；即使远端 WebSocket 尚未建立，也能看到本地唤醒事件。此接口仅在显式开启环境变量且请求来自 loopback 时启用，严格限制事件名称、字段长度、来源与数值范围；不接收音频正文或任意异常详情。

**注意隐私**：这里会把语音识别内容和叙华回答写入标准错误输出；仅供本机开发，生产环境默认关闭。不要把原始日志公开上传。若只需阶段耗时，把 `XUHUA_LOCAL_VOICE_DIAGNOSTICS` 关闭即可。



## 2026-10-12：实测的短唤醒词误识别

本地日志中，讯飞多次将独立呼叫“叙华”转写为“姓华。”、“玉华。”或仅“华。”；此前这些结果进入普通 LLM 提问。现在仅对**整个独立中文语音片段**执行受限的唤醒词恢复：这些精确写法在 ASR 最终结果里规范为“叙华”，回复固定的“我在。”，不调用 LLM。原始识别仍保留在 `user.transcript.raw_text` 与本地诊断日志中，修复原因标为 `isolated-voice-address-recovery`。用户打字提问、带其他内容的完整句子、“我姓华”、谈论“玉华”人名等均不触发这一恢复；孤立“华”会有歧义，应结合后续日志评估误触发率。

这是对**远端讯飞识别结果**的补偿；离线 Sherpa-ONNX 唤醒模型在 WebSocket 尚未建立时不使用这些规则，不能据此宣称离线唤醒率也提高。


## TTS 供应商（讯飞在线语音合成流式版）

- 使用讯飞官方 WebSocket `wss://tts-api.xfyun.cn/v2/tts`，服务端签名握手，`aue=lame` 与 `sfl=1` 返回可逐块传输的 MP3。浏览器不直接接触讯飞 API 凭据，沿用短期 ticket 与首块预取保护。
- 可在 `.env` 设置 `XF_TTS_APP_ID`、`XF_TTS_API_KEY`、`XF_TTS_API_SECRET`。留空时复用 `XF_APP_ID`、`XF_API_KEY`、`XF_API_SECRET`，但讯飞语音识别与合成服务权限是分别管理的。
- 默认普通话发音人已改为**聆小瑜**：`XF_TTS_VOICE_ZH=x4_lingxiaoyu_assist`，其他语种和粤语使用各自的 `XF_TTS_VOICE_*` 配置。只有在讯飞控制台获得对应的 `vcn` 使用权限时才应填写该值，不能使用原有 Edge Neural 音色 ID。
- 供应商未开通、发音人无权限或鉴权失败会返回 HTTP 502，并记录 `tts.provider.failed`，具体应根据讯飞平台的服务授权与错误码排查。自动化测试模拟协议与失败路径，不包含真实供应商连通性验证。
- 由于句段拆分，完整一轮回答最多生成两次独立 TTS 请求；多语种质量取决于发音人是否支持。固定“我在。”提示音仍可从浏览器本地预置素材播放，不依赖在线 TTS。
