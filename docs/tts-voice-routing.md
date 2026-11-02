# 叙华多语言 TTS 路由（v0.2.14）

主站按照实际回复文本判断语种，逐段合成：

- 中文（zh-CN）：讯飞 TTS，默认音色 `x4_yezi`。
- 英语（en-US）：Edge `en-US-JennyNeural`。
- 日语（ja-JP）：Edge `ja-JP-NanamiNeural`。
- 韩语（ko-KR）：Edge `ko-KR-SunHiNeural`。
- 识诈项目（/shizha）：沿用 Edge `zh-CN-YunxiaNeural`。

## 实测证据

旧版将没有独立配置的英日韩语音都交给讯飞中文音色 `xiaoyan`。2026-11-02 腾讯云实际日志中，韩语回复的两个合成片段分别只有 864 和 1296 字节。直接在腾讯云运行 Edge TTS 测试时，英日韩三个音色全部返回约 20–25 KB 的 MP3 数据，耗时约 1.5–1.9 秒。

本次变更保持原有 TTS 票据、流式音频、容量限制和重试机制，只更新服务商与音色选择。四语种路由已加入回归测试，最终的手机端播放仍需实机验证。
