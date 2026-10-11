export const PERSONA_DISPLAY_PATH = "/persona";
export const LEGACY_PERSONA_DISPLAY_PATH = "/display/persona";

export function isPersonaDisplayPath(pathname = "") {
  const normalized = String(pathname || "/").trim().replace(/\/+$/u, "") || "/";
  return normalized === PERSONA_DISPLAY_PATH || normalized === LEGACY_PERSONA_DISPLAY_PATH;
}

export function isLegacyPersonaDisplayPath(pathname = "") {
  const normalized = String(pathname || "/").trim().replace(/\/+$/u, "") || "/";
  return normalized === LEGACY_PERSONA_DISPLAY_PATH;
}

export function personaDisplayState(search = "") {
  const query = String(search || "").replace(/^\?/u, "");
  const params = new URLSearchParams(query);
  return params.get("state") === "speaking" ? "speaking" : "idle";
}


/** Report actual capture separately from local WASM/permission startup. */
export function personaVoiceControlState({
  connected = false,
  microphoneEnabled = false,
  wakeListening = false,
  wakeStarting = false,
  available = true,
} = {}) {
  const active = Boolean(wakeListening || (connected && microphoneEnabled));
  const preparing = Boolean(!connected && wakeStarting);
  const label = connected
    ? (microphoneEnabled ? "关闭麦克风" : "开启麦克风")
    : !available ? "语音服务暂不可用"
      : wakeListening ? "关闭本地唤醒监听"
        : preparing ? "取消本地唤醒准备" : "开启本地唤醒监听";
  return { active, preparing, label };
}
