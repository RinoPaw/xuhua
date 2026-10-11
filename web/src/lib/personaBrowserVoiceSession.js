import { isVoiceAssistantPending } from "../hooks/voiceState.js";
import { BrowserVoiceSession } from "./browserVoiceSession.js";
import { LocalWakeWordDetector } from "./localWakeWordDetector.js";
import { PersonaVoiceGate } from "./personaVoiceGate.js";

export class PersonaBrowserVoiceSession extends BrowserVoiceSession {
  constructor({ gate = null, wakeDetector = null, ...options } = {}) {
    super(options);
    this.gate = gate || new PersonaVoiceGate({ log: this.log });
    this.wakeDetector = wakeDetector || new LocalWakeWordDetector({ log: this.log });
    this.autoWakeEnabled = false;
    this.wakeGeneration = 0;
    this.armingWake = null;
    this.waking = false;
    this.disposed = false;
    this.gate.setOnSleep?.(() => this.enterSleep());
  }

  async armWake() {
    if (this.disposed || this.connection.connected || !this.gate.sleeping) return false;
    // Both the metadata effect and a failed-connection retry can request local
    // listening. They must share one initialization instead of invalidating
    // each other's generation and stopping the newer microphone.
    if (this.armingWake) return this.armingWake;
    this.autoWakeEnabled = true;
    const generation = ++this.wakeGeneration;
    const pending = (async () => {
      try {
        const started = await this.wakeDetector.start((keyword) => this.handleLocalWake(keyword));
        // A stale operation never stops a detector owned by a newer attempt.
        if (generation !== this.wakeGeneration) return false;
        if (!started || this.disposed || !this.autoWakeEnabled || !this.gate.sleeping) {
          this.wakeDetector.stop();
          return false;
        }
        return true;
      } catch (error) {
        if (generation === this.wakeGeneration && this.autoWakeEnabled && !this.disposed) {
          this.reportInputError(error);
        }
        return false;
      }
    })();
    this.armingWake = pending;
    try {
      return await pending;
    } finally {
      if (this.armingWake === pending) this.armingWake = null;
    }
  }

  async handleLocalWake(keyword) {
    if (this.disposed || !this.autoWakeEnabled || !this.gate.sleeping || this.waking) {
      return false;
    }
    const generation = ++this.wakeGeneration;
    this.waking = true;
    this.wakeDetector.stop();
    this.gate.wake(keyword);
    try {
      const started = await super.start();
      if (this.disposed || !this.autoWakeEnabled || generation !== this.wakeGeneration) {
        if (started) super.stop();
        return false;
      }
      if (!started) {
        this.gate.reset();
        return this.armWake();
      }
      // The provider is only contacted once the local wake phrase is heard.
      // This acknowledgement never starts an LLM turn on the server.
      if (!this.send({ type: "wake" })) return this.handleTransportFailure();
      return true;
    } finally {
      this.waking = false;
    }
  }

  async enterSleep() {
    if (this.disposed || !this.autoWakeEnabled) return false;
    // Closing the remote connection cancels outstanding ASR/LLM work. The
    // local detector will own microphone capture while we are asleep.
    super.stop();
    return this.armWake();
  }

  async start() {
    this.autoWakeEnabled = true;
    this.wakeGeneration += 1;
    this.wakeDetector.stop();
    this.gate.wake("手动开启");
    const started = await super.start();
    if (!started && !this.connection.connected) this.gate.reset();
    return started;
  }

  pauseMicrophone() {
    const paused = super.pauseMicrophone();
    if (paused) {
      this.autoWakeEnabled = false;
      this.gate.clearCountdown();
    }
    return paused;
  }

  async resumeMicrophone() {
    this.autoWakeEnabled = true;
    this.gate.wake("手动开启");
    return super.resumeMicrophone();
  }

  processAudio(samples, inputRate) {
    const result = super.processAudio(samples, inputRate);
    const started = result?.actions?.some(
      (action) => action?.kind === "json" && action?.payload?.type === "utterance.start",
    );
    if (started) this.gate.noteUserActivity();
    return result;
  }

  routeServerEvent(message) {
    if (message?.type === "user.partial") {
      this.gate.noteUserActivity();
    }

    if (message?.type === "user.transcript") {
      const decision = this.gate.acceptTranscript(message.text);
      const accepted = super.routeServerEvent(message);
      if (decision === "ignore" && accepted) this.cancelSleepingTurn();
      return accepted;
    }

    if (
      (message?.type === "assistant.delta" || message?.type === "assistant.done")
      && !this.gate.allowAssistantResponse()
    ) {
      if (message.turn_id) this.turns.ignore(message.turn_id);
      return true;
    }

    return super.routeServerEvent(message);
  }

  cancelSleepingTurn() {
    if (!this.connection.connected) return false;
    this.input.clearBargeInCandidate();
    this.turns.ignoreActive();
    this.output?.stop();
    this.dispatchMany([
      { type: "input.idle" },
      { type: "turn.idle" },
      { type: "output.idle" },
    ]);
    const sent = this.send({ type: "interrupt" });
    if (!sent) return this.handleTransportFailure();
    this.settleListening();
    return true;
  }

  sendText(value) {
    const text = String(value || "").trim();
    if (!text || !this.connection.connected) return false;
    const sent = super.sendText(text);
    if (sent) this.gate.wake("文字提问");
    return sent;
  }

  handleOutputTerminal(result = {}) {
    super.handleOutputTerminal(result);
    this.gate.responseSettled();
  }

  stopSpeech(bargeIn = false, notifyServer = true) {
    const hadResponse = Boolean(
      this.output?.pipelineActive
      || this.output?.playing
      || isVoiceAssistantPending(this.getMachine()),
    );
    const result = super.stopSpeech(bargeIn, notifyServer);
    if (hadResponse) {
      this.gate.responseSettled();
      if (bargeIn && this.input.utteranceActive) this.gate.noteUserActivity();
    }
    return result;
  }

  cleanup() {
    super.cleanup();
    this.gate.reset();
  }

  stop() {
    this.autoWakeEnabled = false;
    this.wakeGeneration += 1;
    this.wakeDetector.stop();
    return super.stop();
  }

  destroy() {
    this.disposed = true;
    this.autoWakeEnabled = false;
    this.wakeGeneration += 1;
    this.wakeDetector.dispose();
    super.destroy();
    this.gate.dispose();
  }
}

export default PersonaBrowserVoiceSession;
