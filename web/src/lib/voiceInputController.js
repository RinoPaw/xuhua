import {
  BARGE_IN_PHASE,
  beginBargeInCandidate as makeBargeInCandidate,
  confirmBargeIn,
  createBargeInState,
} from "../hooks/bargeInState.js";
import {
  createVoiceInputState,
  processVoiceInputFrame,
  resetVoiceInputPhase,
  resetVoiceOnset,
  supersedeVoiceUtterance,
} from "./voiceInput.js";

function defaultNow() {
  return globalThis.performance?.now?.() ?? Date.now();
}

/** Owns browser microphone/VAD state, barge-in onset state, and input gating. */
export class VoiceInputController {
  constructor({ now = defaultNow, processFrame = processVoiceInputFrame } = {}) {
    this.now = now;
    this.processFrame = processFrame;
    this.state = createVoiceInputState();
    this.bargeIn = createBargeInState();
    this.blockedUntil = 0;
  }

  get bargeInPhase() {
    return this.bargeIn.phase;
  }

  get utteranceActive() {
    return this.state.utteranceActive;
  }

  reset({ resetIds = true, discardResampler = true } = {}) {
    resetVoiceInputPhase(this.state, { resetIds, discardResampler });
    this.clearBargeInCandidate();
    return this.state;
  }

  supersedeUtterance() {
    supersedeVoiceUtterance(this.state);
    this.clearBargeInCandidate();
    return this.state;
  }

  resetOnset() {
    resetVoiceOnset(this.state);
    return this.state;
  }

  clearBargeInCandidate() {
    this.bargeIn = createBargeInState();
    return true;
  }

  beginBargeInCandidate(utteranceId, startedAt) {
    if (this.bargeIn.phase === BARGE_IN_PHASE.TENTATIVE) return false;
    this.bargeIn = makeBargeInCandidate(this.bargeIn, utteranceId, startedAt);
    return true;
  }

  confirmBargeInCandidate() {
    const confirmed = confirmBargeIn(this.bargeIn);
    if (!confirmed.confirmed) return false;
    this.bargeIn = confirmed.state;
    return true;
  }

  blockFor(durationMs = 450) {
    this.blockedUntil = this.now() + Math.max(0, Number(durationMs) || 0);
    return this.blockedUntil;
  }

  unblock() {
    this.blockedUntil = 0;
  }

  finishActiveUtterance({
    connection,
    onTranscribing = () => {},
    onTransportFailure = () => {},
  } = {}) {
    if (!this.state.utteranceActive) {
      this.resetOnset();
      return true;
    }
    if (!connection?.connected || !connection.sendJson({ type: "utterance.end" })) {
      onTransportFailure();
      return false;
    }
    const wasBargeInCandidate = this.bargeIn.phase === BARGE_IN_PHASE.TENTATIVE;
    resetVoiceInputPhase(this.state);
    if (!wasBargeInCandidate) onTranscribing();
    return true;
  }

  process(samples, inputRate, {
    connection,
    output,
    assistantPending = false,
    onSpectrum = () => {},
    onSpeaking = () => {},
    onTranscribing = () => {},
    onTransportFailure = () => {},
  } = {}) {
    const result = this.processFrame(this.state, {
      samples,
      inputRate,
      now: this.now(),
      blockedUntil: this.blockedUntil,
      transportReady: Boolean(connection?.connected),
      playbackActive: Boolean(output?.playing),
      agentBusy: Boolean(output?.pipelineActive || assistantPending || output?.playing),
      bargeInTentative: this.bargeIn.phase === BARGE_IN_PHASE.TENTATIVE,
    });

    if (result.spectrum) onSpectrum(result.spectrum);

    for (let index = 0; index < result.actions.length; index += 1) {
      const action = result.actions[index];
      if (!connection?.connected) {
        onTransportFailure();
        break;
      }
      const sent = action.kind === "json"
        ? connection.sendJson(action.payload)
        : connection.sendRaw(action.payload);
      if (!sent) {
        onTransportFailure();
        break;
      }

      if (index === 0 && result.started) {
        if (result.started.shouldInterrupt) {
          this.beginBargeInCandidate(result.started.utteranceId, this.state.utteranceStartedAt);
        } else if (result.nextStatus === "user_speaking") {
          onSpeaking();
        }
      }
    }

    if (!result.started && result.nextStatus === "transcribing") onTranscribing();
    return result;
  }
}
