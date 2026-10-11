# 语音链路诊断

服务器、浏览器使用现有 Python logging / browser console 记录阶段事件，无需新增第三方监控服务。

## 关联一次语音会话

- WebSocket 服务端消息有 `connection_id` 和递增 `sequence`；单次 ASR 以 `utterance_id` 区分，助手回答以 `turn_id` 区分。
- 服务端按 `connection=<id>` 过滤，依次找 `voice.connection.open`、`voice.asr.connect.*`、`voice.asr.finalize`、`voice.asr.release`、`voice.llm.first_delta`、`voice.llm.finish`、`voice.chat.release`、`voice.connection.close`。
- 浏览器控制台的 `[叙华][latency ...]` 把 `connection`、`utterance`、`turn`、`tts_trace` 放在同一行；用 `tts_trace` 在服务器中查找 `tts.request.start`、`tts.first_audio_chunk`、`tts.complete`。
- `voice.asr.release` 和 `voice.chat.release` 记录真实租约持有时长，包括取消与断连；`remaining` 是该连接作用域尚未释放的 ASR 资源数，不是所有客户端的并发数。

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
| `[叙华][latency ...]` | 浏览器使用 `performance.now()` 记录语音结束、识别完成、回答首段、TTS 请求、首音频、实际播放；均为浏览器本地毫秒差 |

服务端与浏览器各自使用单调时钟，**不要直接相减跨机器的时间戳**。某个环节未发生（例如没有流式增量）时，浏览器以 `-` 标记未知，而非编造零毫秒。

## 隐私与测试边界

诊断日志只需 ID、状态、耗时和文字长度，避免记录原始语音 PCM、完整 ASR 转写、提示词、回答正文、鉴权材料或 TTS ticket token。服务器仍可能由第三方库独立打印日志，部署时要检查整体日志收集策略。

CI 校验日志结构与模拟生命周期；它无法证明真实设备的麦克风权限、WASM 模型加载、讯飞与 DeepSeek 的网络性能。
