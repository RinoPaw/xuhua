const WAKE_WORD = "叙华";
const WAKE_PREFIX_TRIM = /^[\s，,。！？!?：:、~～]+/u;

export const PERSONA_RESPONSE_GRACE_MS = 7000;

export function isPersonaWakePhrase(value) {
  const text = String(value || "").replace(WAKE_PREFIX_TRIM, "").trim();
  return text.startsWith(WAKE_WORD);
}

function formatSleepDelay(milliseconds) {
  const seconds = Number(milliseconds || 0) / 1000;
  return Number.isInteger(seconds) ? `${seconds}s` : `${seconds.toFixed(1)}s`;
}

export class PersonaVoiceGate {
  constructor({
    sleepDelayMs = PERSONA_RESPONSE_GRACE_MS,
    setTimeoutFn = globalThis.setTimeout,
    clearTimeoutFn = globalThis.clearTimeout,
    log = console,
  } = {}) {
    this.sleepDelayMs = sleepDelayMs;
    this.setTimeoutFn = setTimeoutFn;
    this.clearTimeoutFn = clearTimeoutFn;
    this.log = log;
    this.sleeping = true;
    this.sleepTimer = null;
  }

  logState(message) {
    this.log?.info?.(`[叙华][persona] ${message}`);
  }

  clearCountdown() {
    if (this.sleepTimer === null) return false;
    this.clearTimeoutFn.call(globalThis, this.sleepTimer);
    this.sleepTimer = null;
    return true;
  }

  reset() {
    this.clearCountdown();
    this.sleeping = true;
  }

  wake(triggerText = "") {
    const wasSleeping = this.sleeping;
    this.clearCountdown();
    this.sleeping = false;
    const trigger = String(triggerText || "").trim();
    if (trigger) this.logState(`wake: ${trigger}`);
    if (wasSleeping) this.logState("awake");
  }

  noteUserActivity() {
    if (this.sleeping) return false;
    if (this.clearCountdown()) this.logState("awake");
    return true;
  }

  acceptTranscript(text) {
    if (!this.sleeping) {
      if (this.clearCountdown()) this.logState("awake");
      return "active";
    }
    if (!isPersonaWakePhrase(text)) return "ignore";
    this.wake(text);
    return "wake";
  }

  responseSettled() {
    if (this.sleeping) return false;
    this.clearCountdown();
    this.logState(`sleep countdown ${formatSleepDelay(this.sleepDelayMs)}`);
    this.sleepTimer = this.setTimeoutFn.call(globalThis, () => {
      this.sleepTimer = null;
      this.sleeping = true;
      this.logState("sleeping");
    }, this.sleepDelayMs);
    return true;
  }

  allowAssistantResponse() {
    return !this.sleeping;
  }

  dispose() {
    this.reset();
  }
}
