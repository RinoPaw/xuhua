import { isVoiceAssistantPending } from "../hooks/voiceState.js";
import { BrowserVoiceSession } from "./browserVoiceSession.js";
import { LocalWakeWordDetector } from "./localWakeWordDetector.js";
import { PersonaVoiceGate } from "./personaVoiceGate.js";

export class PersonaBrowserVoiceSession extends BrowserVoiceSession {
  constructor({ gate = null, wakeDetector = null, ...options } = {}) {
    super(options);
    this.gate = gate || new PersonaVoiceGate({ log: this.log });
    this.wakeDetector = wakeDetector || new LocalWakeWordDetector({ log: this.log });
    this.wakeHandoffPending = false;
    this.gate.setOnSleep(() => this.enterLocalSleep());
  }

  async startLocalWakeListening() {
    if (this.wakeDetector.active) return true;
    try {
      await this.wakeDetector.start((keyword) => this.handleLocalWake(keyword));
      return true;
    } catch (error) {
      this.log.error?.("[叙华][wake] local KWS unavailable", error);
      this.reportInputError(error);
      return false;
    }
  }

  async start() {
    this.prewarmAcknowledgement();
    this.clearError();
    return this.startLocalWakeListening();
  }

  sendWake() {
    if (!this.connection.connected) return false;
    const sent = this.send({ type: "wake" });
    if (!sent) return this.handleTransportFailure();
    this.latency.clear();
    this.transcript.clear(true);
    this.input.supersedeUtterance();
    this.stopSpeech(true, false);
    this.markThinking();
    return true;
  }

  async handleLocalWake(keyword = "叙华") {
    if (this.wakeHandoffPending) return false;
    this.wakeHandoffPending = true;
    try {
      this.wakeDetector.stop();
      this.gate.wake(keyword);

      if (!this.connection.connected) {
        const started = await super.start();
        if (!started && !this.connection.connected) return false;
      } else if (!this.microphoneEnabled) {
        const resumed = await this.resumeMicrophone();
        if (!resumed) return false;
      }

      if (!this.connection.connected) return false;
      return this.sendWake();
    } finally {
      this.wakeHandoffPending = false;
    }
  }

  async enterLocalSleep() {
    if (!this.gate.sleeping) return false;
    if (this.connection.connected && this.microphoneEnabled) {
      const paused = this.pauseMicrophone();
      if (!paused) return false;
    }
    return this.startLocalWakeListening();
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
    this.wakeDetector.stop();
    super.cleanup();
    this.gate.reset();
    this.wakeHandoffPending = false;
  }

  stop() {
    this.wakeDetector.stop();
    return super.stop();
  }

  destroy() {
    super.destroy();
    this.wakeDetector.dispose();
    this.gate.dispose();
  }
}

export default PersonaBrowserVoiceSession;
