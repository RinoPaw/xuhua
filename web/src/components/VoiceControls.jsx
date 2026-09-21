import { Microphone, MicrophoneSlash, SpinnerGap, X } from "@phosphor-icons/react";

import { REALTIME_VOICE_STATUS } from "../hooks/voiceState.js";
import "./VoiceControls.css";

export const VOICE_COPY = {
  [REALTIME_VOICE_STATUS.IDLE]: { label: "实时对话", detail: "等待开启", owner: "system" },
  [REALTIME_VOICE_STATUS.CONNECTING]: { label: "连接中", detail: "请允许使用麦克风", owner: "assistant" },
  [REALTIME_VOICE_STATUS.LISTENING]: { label: "等待语音", detail: "麦克风已就绪", owner: "user" },
  [REALTIME_VOICE_STATUS.USER_SPEAKING]: { label: "聆听中", detail: "继续说", owner: "user" },
  [REALTIME_VOICE_STATUS.TRANSCRIBING]: { label: "识别中", detail: "请稍候", owner: "user" },
  [REALTIME_VOICE_STATUS.THINKING]: { label: "生成回答中", detail: "查找资料中", owner: "assistant" },
  [REALTIME_VOICE_STATUS.RESPONDING]: { label: "播报中", detail: "可随时打断", owner: "assistant" },
  [REALTIME_VOICE_STATUS.ERROR]: { label: "语音不可用", detail: "请重试", owner: "assistant" },
};

export function friendlyVoiceError(error, available) {
  if (!available) return "实时语音暂未就绪。";
  const message = String(error?.message || "");
  if (/notallowed|permission|denied/i.test(message)) return "请允许浏览器使用麦克风。";
  if (/notfound|device|microphone/i.test(message)) return "没有找到可用的麦克风。";
  if (/生成等待过久|first.token.timeout/i.test(message)) return "回答生成超时，请再试一次。";
  if (/回答服务暂时不可用/i.test(message)) return "回答服务暂时不可用，请再试一次。";
  return "实时语音连接失败，请重试。";
}

export function VoiceControl({
  available,
  connected,
  microphoneEnabled,
  status,
  onStart,
  onToggleMicrophone,
  onEnd,
}) {
  const { label, detail } = VOICE_COPY[status] || VOICE_COPY[REALTIME_VOICE_STATUS.IDLE];
  const connecting = status === REALTIME_VOICE_STATUS.CONNECTING;
  const controlLabel = connected
    ? (microphoneEnabled ? "关闭麦克风，当前回答会继续" : "开启麦克风")
    : "开启连续实时对话";
  const controlTitle = connected
    ? (microphoneEnabled ? `${label} · 点击关闭麦克风` : "麦克风已关闭 · 点击重新开启")
    : (available ? "开启连续实时对话" : "实时语音暂未就绪");

  return (
    <div className={`voice-control-cluster ${connected ? "is-connected" : ""}`}>
      {connected && (
        <button
          type="button"
          className="voice-end-button"
          onClick={onEnd}
          aria-label="结束实时对话"
          title="结束实时对话"
        >
          <X />
        </button>
      )}
      <button
        type="button"
        className={`voice-orb ${connected && microphoneEnabled ? "active" : ""} ${connected && !microphoneEnabled ? "muted" : ""}`}
        onClick={connected ? onToggleMicrophone : onStart}
        disabled={!available || connecting}
        aria-label={controlLabel}
        aria-pressed={connected ? Boolean(microphoneEnabled) : undefined}
        title={controlTitle}
      >
        {connecting ? <SpinnerGap className="spin" /> : (
          connected
            ? (microphoneEnabled ? <Microphone /> : <MicrophoneSlash />)
            : <span className="voice-bars" aria-hidden="true"><i /><i /><i /><i /><i /></span>
        )}
        <span className="sr-only">{detail}</span>
      </button>
    </div>
  );
}

export function VoiceSpectrum({ values }) {
  return (
    <div className="voice-spectrum" aria-hidden="true">
      {(values?.length ? values : Array(24).fill(0)).map((value, index) => (
        <i key={index} style={{ "--level": Math.max(0.08, Number(value) || 0) }} />
      ))}
    </div>
  );
}

export function VoiceStatusRow({ status, connected, hasUserPartial, hasAssistantBubble }) {
  const copy = VOICE_COPY[status];
  const disconnectedActionableStatus = status === REALTIME_VOICE_STATUS.CONNECTING;
  if ((!connected && !disconnectedActionableStatus)
    || !copy
    || status === REALTIME_VOICE_STATUS.IDLE
    || status === REALTIME_VOICE_STATUS.ERROR) return null;

  const hasVisibleBubble = copy.owner === "user" ? hasUserPartial : hasAssistantBubble;
  if (hasVisibleBubble) return null;

  return (
    <article className={`message-row ${copy.owner} thinking-row voice-status-row`} aria-live="polite">
      {copy.owner === "assistant" && <span className="chat-avatar">叙</span>}
      <div className="message-content">
        {copy.owner === "assistant" && <span className="message-author">叙华</span>}
        <div className="thinking-status">
          <span>{copy.label}</span>
          <i /><i /><i />
        </div>
      </div>
    </article>
  );
}
