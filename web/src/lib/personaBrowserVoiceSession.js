import { isVoiceAssistantPending, VOICE_INPUT_PHASE } from "../hooks/voiceState.js";
import { BrowserVoiceSession } from "./browserVoiceSession.js";
import { LocalWakeWordDetector } from "./localWakeWordDetector.js";
import { PersonaVoiceGate } from "./personaVoiceGate.js";

export class PersonaBrowserVoiceSession extends BrowserVoiceSession {
  constructor({ gate = null, wakeDetector = null, onWakeListeningChange = () => {}, onWakeStartingChange = () => {}, ...options } = {}) {
    super(options);
    this.gate = gate || new PersonaVoiceGate({ log: this.log });
    this.wakeDetector = wakeDetector || new LocalWakeWordDetector({ log: this.log });
    this.wakeDetector.onDiagnostic = (event, details) => this.recordDiagnostic(event, details);
    this.autoWakeEnabled = false;
    this.wakeListening = false;
    this.wakeStarting = false;
    this.onWakeListeningChange = onWakeListeningChange;
    this.onWakeStartingChange = onWakeStartingChange;
    this.wakeGeneration = 0;
    this.armingWake = null;
    this.waking = false;
    this.disposed = false;
    this.gate.setOnSleep?.(() => this.enterSleep());
  }

  setWakeListening(value) {
    const active = Boolean(value);
    if (this.wakeListening === active) return;
    this.wakeListening = active;
    this.onWakeListeningChange(active);
  }

  setWakeStarting(value) {
    const active = Boolean(value);
    if (this.wakeStarting === active) return;
    this.wakeStarting = active;
    this.onWakeStartingChange(active);
  }

  async armWake() {
    if (this.disposed || this.connection.connected || !this.gate.sleeping) return false;
    // Both the metadata effect and a failed-connection retry can request local
    // listening. They must share one initialization instead of invalidating
    // each other's generation and stopping the newer microphone.
    if (this.armingWake) return this.armingWake;
    this.autoWakeEnabled = true;
    const generation = ++this.wakeGeneration;
    this.setWakeStarting(true);
    const pending = (async () => {
      try {
        const started = await this.wakeDetector.start((keyword) => this.handleLocalWake(keyword));
        // A stale operation never stops a detector owned by a newer attempt.
        if (generation !== this.wakeGeneration) return false;
        if (!started || this.disposed || !this.autoWakeEnabled || !this.gate.sleeping) {
          this.wakeDetector.stop();
          this.setWakeListening(false);
          return false;
        }
        this.setWakeListening(true);
        // The remote socket may have failed, but successfully restored local
        // wake capture is an operational idle state, not a fatal UI fault.
        this.clearError();
        this.dispatchVoice({ type: "fault.clear" });
        return true;
      } catch (error) {
        if (generation === this.wakeGeneration && this.autoWakeEnabled && !this.disposed) {
          this.setWakeListening(false);
          this.reportInputError(error);
        }
        return false;
      }
    })();
    this.armingWake = pending;
    try {
      return await pending;
    } finally {
      if (this.armingWake === pending) {
        this.armingWake = null;
        this.setWakeStarting(false);
      }
    }
  }

  async handleLocalWake(keyword) {
    if (this.disposed || !this.autoWakeEnabled || !this.gate.sleeping || this.waking) {
      return false;
    }
    const generation = ++this.wakeGeneration;
    this.waking = true;
    this.setWakeStarting(false);
    this.wakeDetector.stop();
    this.setWakeListening(false);
    this.gate.wake(keyword);
    try {
      const started = await super.start();
      if (this.disposed || !this.autoWakeEnabled || generation !== this.wakeGeneration) {
        if (started) super.stop();
        return false;
      }
      if (!started) {
        this.recordDiagnostic("wake.remote.failed");
        this.gate.reset();
        return this.armWake();
      }
      // The provider is only contacted once the local wake phrase is heard.
      // This acknowledgement never starts an LLM turn on the server.
      if (!this.send({ type: "wake" })) return this.handleTransportFailure();
      this.recordDiagnostic("wake.remote.connected");
      return true;
    } finally {
      this.waking = false;
    }
  }

  handleConnectionClosed(event) {
    if (this.disposed || !this.autoWakeEnabled) return;
    this.log.info?.(`[叙华][persona] remote connection closed code=${event?.code ?? "-"}; restoring local wake`);
    void this.armWake();
  }

  handleTransportFailure() {
    const shouldRecover = this.autoWakeEnabled && !this.disposed;
    const result = super.handleTransportFailure();
    if (shouldRecover) void this.armWake();
    return result;
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
    this.armingWake = null;
    this.setWakeStarting(false);
    this.wakeDetector.stop();
    this.setWakeListening(false);
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

  // Sleeping closes the remote socket. No second "remote ASR while asleep"
  // branch is needed; accept events only from the active connected session.
  routeServerEvent(message) {
    const accepted = super.routeServerEvent(message);
    if (!accepted) return false;

    if (message?.type === "user.partial" || message?.type === "user.transcript") {
      this.gate.noteUserActivity();
    } else if (["assistant.cancelled", "utterance.rejected", "error"].includes(message?.type)) {
      // Failure/rejection can terminate a turn without triggering audio output.
      this.scheduleSleepIfIdle();
    }
    return true;
  }

  scheduleSleepIfIdle() {
    const machine = this.getMachine();
    if (this.disposed || !this.autoWakeEnabled || this.gate.sleeping
      || !this.connection.connected || this.input.utteranceActive
      || machine?.input === VOICE_INPUT_PHASE.SPEAKING
      || machine?.input === VOICE_INPUT_PHASE.TRANSCRIBING
      || this.output?.pipelineActive || this.output?.playing
      || isVoiceAssistantPending(machine)
      || this.gate.sleepTimer !== null) return false;
    return this.gate.responseSettled();
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
    this.scheduleSleepIfIdle();
  }

  stopSpeech(bargeIn = false, notifyServer = true) {
    const hadResponse = Boolean(
      this.output?.pipelineActive
      || this.output?.playing
      || isVoiceAssistantPending(this.getMachine()),
    );
    const result = super.stopSpeech(bargeIn, notifyServer);
    if (hadResponse) {
      if (bargeIn && this.input.utteranceActive) this.gate.noteUserActivity();
      else this.scheduleSleepIfIdle();
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
    this.armingWake = null;
    this.setWakeStarting(false);
    this.wakeDetector.stop();
    this.setWakeListening(false);
    return super.stop();
  }

  destroy() {
    this.disposed = true;
    this.autoWakeEnabled = false;
    this.wakeGeneration += 1;
    this.armingWake = null;
    this.setWakeStarting(false);
    this.wakeDetector.dispose();
    this.setWakeListening(false);
    super.destroy();
    this.gate.dispose();
  }
}

export default PersonaBrowserVoiceSession;
