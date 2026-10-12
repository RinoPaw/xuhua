# 语音生命周期与验收

本文记录语音重构完成后的运行边界、资源所有权和自动化验收范围，供后续维护和设备联调使用。

## 资源所有权

| 阶段 | 资源 | 责任组件和清理方式 |
| --- | --- | --- |
| 休眠 / 本地唤醒 | 远端 WebSocket 关闭，Sherpa-ONNX 监听本地麦克风 | PersonaBrowserVoiceSession 负责切换；LocalWakeWordDetector.stop 释放麦克风，dispose 额外释放 WASM 资源 |
| 唤醒准备 | WASM 加载或浏览器授权未完成 | wakeStarting 与 wakeListening 分开上报；wakeGeneration 拒绝过期初始化和手动停止后的回调 |
| 远端对话 | WebSocket、MediaStream、AudioContext、AudioWorklet | VoiceConnectionController 管理连接；VoiceMediaController 管理采集资源及过期流释放 |
| ASR 转写 | 每段识别任务、finalizer、admission lease | 服务端以 utterance_id、批次 generation 隔离；关闭或取消必须释放流、任务和租约 |
| 回答与 TTS | 服务端回答任务、浏览器音频对象、TTS 请求与重试定时器 | turn_id 关联回答；TtsScheduler / VoiceOutputController 使用播放 generation 拒绝过期回调与旧 trace；首播使用渐进式 MP3，重试回退完整缓冲 |
| 播放完成 / 空闲 | 约 7 秒休眠倒计时 | PersonaVoiceGate 用倒计时代次屏蔽已经取消、但仍被调度的旧回调 |
| 显式停止 / 卸载 | WebSocket 和音频捕获均应关闭 | stop 失效化启动与计时器，destroy 额外清理 WASM 和 TTS 缓存 |

仅人物页启用本地唤醒与自动休眠；其他实时语音入口仍由 BrowserVoiceSession 直接管理连接。

## 事件与取消边界

- 客户端发送文字问题前预留 turn_id，服务端沿用该 ID。语音输入由服务端创建轮次。
- 局部识别、最终识别和识别错误以 utterance_id 与终止标记隔离。VoiceTranscriptPresenter 对逐字显示的 interval 也使用代次；旧回调不能修改新转写。
- barge_in 取消旧回答，但保留新语音识别；interrupt 还会取消 ASR。服务端在取消工作完成后发 interrupt.ack，携带 request_id、reason、turn_id、utterance_id 和 cancelled。客户端只接受尚在等待的确认，确认本身不能终止新 TTS。旧命令可以不携带 request_id。
- 取消 TTS 时停止音频、作废 source request、清除重试定时器并失效化 generation。请求的 trace_id 在开始时固定。首播 MP3 在服务端收到首个有效音频块之后才发送 HTTP 200；首块前异常仍可返回 502。若已传输音频时供应商出错，流会中断，不能保证浏览器播放完整，且不应自动重播已经听过的部分；带 tts_retry 的重试会使用完整缓冲。音频输出失败不应导致正常的远端 ASR/WebSocket 断开。
- 远端意外断连先清理连接与播放，再恢复本地监听；恢复成功后清除过期的远端故障 UI 标记。手动关闭或暂停不自动重连。
- 服务器 status 是建议性状态；浏览器本地媒体所有权、当前轮次与已接受的事件才决定 UI。

## 自动化验收

全链路模拟覆盖：两轮唤醒—ASR—回答—TTS—休眠、播报中抢话、重复及迟到的取消确认、ASR 乱序收尾、旧音频回调、断连后的本地监听恢复、过期休眠及转写计时器、麦克风启动取消、资源租约释放。

在仓库根目录执行 Python 测试和 Ruff：

    uv run pytest -q
    uv run ruff check server/src tools server/tests

在 web 目录执行：

    npm test
    npm run lint
    npm run build

这些用受控的异步任务、WebSocket、MediaStream 和音频对象模拟边界，可以验证状态机、事件隔离和资源释放逻辑。**它们不代表真实设备麦克风权限、Sherpa-ONNX 唤醒准确率、讯飞及 LLM 外部网络延迟已经验证**。设备联调需在正式上线前单独开展。

诊断和隐私规则见 [语音链路诊断](voice-observability.md)：默认日志只记录 ID、状态、耗时和长度，不记录原始 PCM、完整转写、TTS token 或密钥。

ASR 的 `finish_result()` 只等待讯飞最终识别文本，连接作用域继续拥有旧流与 admission lease；运行时先提交文字、启动回答，再由 finalizer 等待释放资源。兼容接口 `finish()` 仍在返回前关闭流。多段语音批次会等待所有段的最终文本，再按顺序合并，不能因一段提前返回而错误提交。


### ASR 达到容量上限时的恢复

同一语音 WebSocket 最多保留 3 个正在连接或最终收尾中的 ASR 操作，且每个操作继续受全局并发和速率预算限制。超过上限时，新语音段收到 `utterance.rejected`（带 `reason=voice_asr_capacity` / `voice_asr_client_rate` 等机器码），不关闭 WebSocket，不取消先前已受理的识别。被拒绝的音频及其结束事件被隔离，不可进入上一个 ASR；浏览器结束本地采集段并短暂抑制 VAD 重新触发。后台已有的 ASR finalizer 正常释放资源后，后续语音仍可继续；因分钟级速率限制被拒绝时必须等配额恢复。真正的传输失败或过量 PCM 缓冲仍会断连，以保护服务。
