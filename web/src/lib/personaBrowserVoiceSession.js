import { isVoiceAssistantPending } from "../hooks/voiceState.js";
import { BrowserVoiceSession } from "./browserVoiceSession.js";
import { PersonaVoiceGate } from "./personaVoiceGate.js";

function logFinalText(log, speaker, text) {
  const content = String(text || "").trim();
  if (!content) return;
  log.info?.(`[叙华][persona] ${speaker}: ${content}`);
}

export class PersonaBrowserVoiceSession extends BrowserVoiceSession {
  constructor({ gate = new PersonaVoiceGate(), ...options } = {}) {
    super(options);
    this.gate = gate;
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
      logFinalText(this.log, "用户", message.text);
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

    const accepted = super.routeServerEvent(message);
    if (accepted && message?.type === "assistant.done") {
      logFinalText(this.log, "叙华", message.text);
    }
    return accepted;
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
    super.cleanup();
    this.gate.reset();
  }

  destroy() {
    super.destroy();
    this.gate.dispose();
  }
}

export default PersonaBrowserVoiceSession;
