const WAKE_WORD = "叙华";
const WAKE_PREFIX_TRIM = /^[\s，,。！？!?：:、~～]+/u;

export const PERSONA_RESPONSE_GRACE_MS = 7000;

export function isPersonaWakePhrase(value) {
  const text = String(value || "").replace(WAKE_PREFIX_TRIM, "").trim();
  return text.startsWith(WAKE_WORD);
}

export class PersonaVoiceGate {
  constructor({
    sleepDelayMs = PERSONA_RESPONSE_GRACE_MS,
    setTimeoutFn = globalThis.setTimeout,
    clearTimeoutFn = globalThis.clearTimeout,
  } = {}) {
    this.sleepDelayMs = sleepDelayMs;
    this.setTimeoutFn = setTimeoutFn;
    this.clearTimeoutFn = clearTimeoutFn;
    this.sleeping = true;
    this.sleepTimer = null;
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

  wake() {
    this.clearCountdown();
    this.sleeping = false;
  }

  noteUserActivity() {
    if (this.sleeping) return false;
    this.clearCountdown();
    return true;
  }

  acceptTranscript(text) {
    if (!this.sleeping) {
      this.clearCountdown();
      return "active";
    }
    if (!isPersonaWakePhrase(text)) return "ignore";
    this.wake();
    return "wake";
  }

  responseSettled() {
    if (this.sleeping) return false;
    this.clearCountdown();
    this.sleepTimer = this.setTimeoutFn.call(globalThis, () => {
      this.sleepTimer = null;
      this.sleeping = true;
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
