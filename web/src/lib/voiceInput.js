import {
  advanceVADGate,
  createVADGateState,
  getVADOnsetPolicy,
} from "./vadOnsetGate.js";
import { encodePcm, StatefulPcmResampler } from "./pcmResampler.js";
import { appendPreRoll, createPreRollState, drainPreRoll, PRE_ROLL_MS } from "./pcmPreRoll.js";
import { rms, spectrumBars } from "./voiceAudio.js";
import {
  normalizeUtteranceId,
  shouldAcceptUtteranceEvent,
} from "../hooks/voiceState.js";

const TARGET_RATE = 16000;
const NORMAL_VAD_POLICY = getVADOnsetPolicy(false);
const SILENCE_MS = 420;
const MAX_UTTERANCE_MS = 20000;
const SPECTRUM_INTERVAL_MS = 50;
const PLAYBACK_PRE_ROLL_MS = 80;

export function createVoiceInputState() {
  return {
    utteranceActive: false,
    utteranceStartedAt: 0,
    lastVoiceAt: 0,
    gate: createVADGateState(),
    preRoll: createPreRollState(),
    resampler: null,
    spectrumUpdatedAt: 0,
    latestUtteranceId: 0,
    activeUtteranceId: 0,
    nextUtteranceId: 0,
    minimumUtteranceId: 1,
  };
}

export function resetVoiceInputPhase(state, { resetIds = false, discardResampler = false } = {}) {
  state.utteranceActive = false;
  state.utteranceStartedAt = 0;
  state.lastVoiceAt = 0;
  state.gate = createVADGateState();
  state.preRoll = createPreRollState();
  state.resampler?.reset();
  if (discardResampler) state.resampler = null;
  if (resetIds) {
    state.latestUtteranceId = 0;
    state.activeUtteranceId = 0;
    state.nextUtteranceId = 0;
    state.minimumUtteranceId = 1;
  }
  return state;
}

export function supersedeVoiceUtterance(state) {
  const lastIssued = Math.max(
    Number(state.latestUtteranceId) || 0,
    Number(state.activeUtteranceId) || 0,
    Number(state.nextUtteranceId) || 0,
    (Number(state.minimumUtteranceId) || 1) - 1,
  );
  resetVoiceInputPhase(state);
  state.nextUtteranceId = lastIssued;
  state.activeUtteranceId = 0;
  state.minimumUtteranceId = lastIssued + 1;
  return state.minimumUtteranceId;
}

export function resetVoiceOnset(state) {
  state.gate = createVADGateState();
  state.preRoll = createPreRollState();
  return state;
}

export function acceptVoiceUtteranceMessage(state, message, { required = true } = {}) {
  const id = normalizeUtteranceId(message?.utterance_id);
  if (!id) return !required;
  if (id < (Number(state.minimumUtteranceId) || 1)) return false;
  if (!shouldAcceptUtteranceEvent(id, state.latestUtteranceId, state.activeUtteranceId)) {
    return false;
  }
  state.latestUtteranceId = Math.max(state.latestUtteranceId, id);
  state.nextUtteranceId = Math.max(state.nextUtteranceId, id);
  return true;
}

function ensureResampler(state, inputRate) {
  if (!state.resampler || state.resampler.inputRate !== inputRate) {
    state.resampler = new StatefulPcmResampler(inputRate, TARGET_RATE);
  }
  return state.resampler;
}

/**
 * Advance browser microphone/VAD state for one AudioWorklet block.
 *
 * The function owns no browser transport. It returns the exact JSON and PCM
 * frames that the caller should send, plus UI transition hints. This keeps the
 * timing-sensitive VAD rules testable without coupling them to React or a
 * WebSocket instance.
 */
export function processVoiceInputFrame(state, {
  samples,
  inputRate,
  now,
  blockedUntil = 0,
  transportReady = true,
  playbackActive = false,
  agentBusy = false,
  bargeInTentative = false,
} = {}) {
  const actions = [];
  let spectrum = null;
  let started = null;
  let nextStatus = null;

  if (now < blockedUntil) {
    state.gate = createVADGateState();
    state.preRoll = createPreRollState();
    state.resampler?.reset();
    return { actions, spectrum, started, nextStatus };
  }
  if (!transportReady || !samples || !(inputRate > 0)) {
    return { actions, spectrum, started, nextStatus };
  }

  const playbackOnset = !state.utteranceActive && playbackActive;
  const pcm = encodePcm(samples, inputRate, ensureResampler(state, inputRate));
  state.preRoll = appendPreRoll(
    state.preRoll,
    pcm,
    (samples.length / inputRate) * 1000,
    playbackOnset ? PLAYBACK_PRE_ROLL_MS : PRE_ROLL_MS,
  );

  const level = rms(samples);
  const shouldInterrupt = !state.utteranceActive && agentBusy;
  const onsetPolicy = getVADOnsetPolicy(playbackOnset);
  const threshold = onsetPolicy.threshold;
  state.gate = advanceVADGate(state.gate, {
    isAboveThreshold: level >= threshold,
    samplesLength: samples.length,
    inputRate,
    thresholdMs: onsetPolicy.thresholdMs,
  });

  if (now - state.spectrumUpdatedAt >= SPECTRUM_INTERVAL_MS) {
    state.spectrumUpdatedAt = now;
    const showInput = !playbackOnset || level >= threshold;
    spectrum = showInput ? spectrumBars(samples) : Array(24).fill(0);
  }

  if (!state.utteranceActive && state.gate.onset) {
    const utteranceId = Math.max(
      state.nextUtteranceId,
      state.latestUtteranceId,
      state.minimumUtteranceId - 1,
    ) + 1;
    state.nextUtteranceId = utteranceId;
    state.activeUtteranceId = utteranceId;
    actions.push({
      kind: "json",
      payload: {
        type: "utterance.start",
        interrupt: shouldInterrupt,
        level: Number(level.toFixed(4)),
        threshold: Number(threshold.toFixed(4)),
      },
    });
    state.utteranceActive = true;
    state.utteranceStartedAt = now;
    state.lastVoiceAt = now;
    started = { utteranceId, shouldInterrupt };
    if (!shouldInterrupt) nextStatus = "user_speaking";

    for (const frame of drainPreRoll(state.preRoll).chunks) {
      actions.push({ kind: "binary", payload: frame });
    }
    state.preRoll = createPreRollState();
    return { actions, spectrum, started, nextStatus };
  }

  if (!state.utteranceActive) {
    return { actions, spectrum, started, nextStatus };
  }

  if (pcm.byteLength > 0) actions.push({ kind: "binary", payload: pcm });
  if (level >= NORMAL_VAD_POLICY.threshold) state.lastVoiceAt = now;

  const timedOut = now - state.utteranceStartedAt >= MAX_UTTERANCE_MS;
  if (timedOut || now - state.lastVoiceAt > SILENCE_MS) {
    actions.push({ kind: "json", payload: { type: "utterance.end" } });
    state.utteranceActive = false;
    state.utteranceStartedAt = 0;
    state.gate = createVADGateState();
    state.preRoll = createPreRollState();
    if (!bargeInTentative) nextStatus = "transcribing";
  }

  return { actions, spectrum, started, nextStatus };
}

export const VOICE_INPUT_LIMITS = Object.freeze({
  targetRate: TARGET_RATE,
  silenceMs: SILENCE_MS,
  maxUtteranceMs: MAX_UTTERANCE_MS,
  spectrumIntervalMs: SPECTRUM_INTERVAL_MS,
  playbackPreRollMs: PLAYBACK_PRE_ROLL_MS,
});
