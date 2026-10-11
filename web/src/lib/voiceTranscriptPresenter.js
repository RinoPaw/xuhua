import {
  applyFinalReveal,
  applyPartialReveal,
  createPartialRevealState,
  resetPartialReveal,
} from "./partialReveal.js";

export class VoiceTranscriptPresenter {
  constructor({
    getCallbacks = () => ({}),
    scheduleInterval = (callback, delay) => globalThis.setInterval(callback, delay),
    clearScheduledInterval = (timer) => globalThis.clearInterval(timer),
    intervalMs = 26,
  } = {}) {
    this.getCallbacks = getCallbacks;
    this.scheduleInterval = scheduleInterval;
    this.clearScheduledInterval = clearScheduledInterval;
    this.intervalMs = intervalMs;
    this.reveal = createPartialRevealState();
    this.timerGeneration = 0;
  }

  clear(resetText = false) {
    // An interval tick may already be queued even after clearInterval().
    // Invalidate the callback before a new utterance can reuse this state.
    this.timerGeneration += 1;
    if (this.reveal.timer !== null) {
      this.clearScheduledInterval(this.reveal.timer);
      this.reveal.timer = null;
    }
    resetPartialReveal(this.reveal, { clearText: resetText });
    return this.reveal;
  }

  publishPartial(message) {
    const applied = applyPartialReveal(this.reveal, message);
    if (!applied.accepted) return false;
    if (applied.startsNew) this.clear(false);
    this.getCallbacks().onUserPartial?.(this.reveal.visible, message);

    if (this.reveal.timer === null && this.reveal.visible.length < this.reveal.target.length) {
      const generation = this.timerGeneration;
      this.reveal.timer = this.scheduleInterval(() => {
        if (generation !== this.timerGeneration) return;
        if (this.reveal.visible.length >= this.reveal.target.length) {
          this.clear();
          return;
        }
        this.reveal.visible += this.reveal.target[this.reveal.visible.length];
        this.getCallbacks().onUserPartial?.(this.reveal.visible, this.reveal.event);
      }, this.intervalMs);
    }
    return true;
  }

  publishTranscript(message, transcript) {
    if (!applyFinalReveal(this.reveal, message, transcript)) return false;
    this.clear(false);
    this.getCallbacks().onUserTranscript?.(this.reveal.visible, message);
    return true;
  }

  reject(message) {
    this.clear(true);
    this.getCallbacks().onUserPartial?.("", message);
    return true;
  }

  dispose() {
    this.clear(true);
  }
}
