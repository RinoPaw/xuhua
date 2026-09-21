import {
  deriveVoiceStatus,
  isVoiceAssistantPending,
  REALTIME_VOICE_STATUS,
  VOICE_TRANSPORT_PHASE,
} from "../hooks/voiceState.js";
import { VoiceConnectionController } from "./voiceConnection.js";
import { routeVoiceServerEvent } from "./voiceEventRouter.js";
import { VoiceInputController } from "./voiceInputController.js";
import { VoiceLatencyTrace } from "./voiceLatency.js";
import { VoiceOutputController } from "./voiceOutput.js";
import {
  compactRecognitionContext,
  VoiceTurnTracker,
} from "./voiceProtocol.js";
import { VoiceTranscriptPresenter } from "./voiceTranscriptPresenter.js";

const ACKNOWLEDGEMENT_TEXT = "我在。";

function noop() {}

function logFinalVoiceText(log, speaker, text) {
  const content = String(text || "").trim();
  if (!content) return;
  log.info?.(`[叙华][voice] ${speaker}: ${content}`);
}

/**
 * Browser-side realtime voice session coordinator.
 *
 * React supplies state-machine bindings and UI callbacks. This object owns the
 * long-lived voice collaborators and all cross-controller orchestration.
 */
export class BrowserVoiceSession {
  constructor({
    websocketPath = "/api/voice",
    getMachine = () => ({}),
    dispatchVoice = noop,
    dispatchMany = noop,
    getRecognitionContext = () => null,
    getCallbacks = () => ({}),
    onErrorState = noop,
    onSpectrum = noop,
    onMicrophoneEnabledChange = noop,
    connection = new VoiceConnectionController(),
    input = new VoiceInputController(),
    turns = new VoiceTurnTracker(),
    transcript = null,
    latency = null,
    createOutput = (options) => new VoiceOutputController(options),
    log = console,
  } = {}) {
    this.websocketPath = websocketPath;
    this.getMachine = getMachine;
    this.dispatchVoice = dispatchVoice;
    this.dispatchMany = dispatchMany;
    this.getRecognitionContext = getRecognitionContext;
    this.getCallbacks = getCallbacks;
    this.onErrorState = onErrorState;
    this.onSpectrum = onSpectrum;
    this.onMicrophoneEnabledChange = onMicrophoneEnabledChange;
    this.connection = connection;
    this.input = input;
    this.turns = turns;
    this.log = log;
    this.latency = latency || new VoiceLatencyTrace({ log });
    this.transcript = transcript || new VoiceTranscriptPresenter({ getCallbacks });
    this.microphoneEnabled = false;
    this.output = createOutput({
      websocketPath,
      getRecognitionContext,
      onEvent: (event) => this.handleOutputEvent(event),
      onPlayingChange: (playing) => this.handlePlayingChange(playing),
      onTerminal: (result) => this.handleOutputTerminal(result),
    });
  }

  setWebsocketPath(path) {
    this.websocketPath = String(path || "/api/voice");
    this.output.setWebsocketPath(this.websocketPath);
  }

  setMicrophoneEnabled(value) {
    const enabled = Boolean(value);
    if (this.microphoneEnabled === enabled) return enabled;
    this.microphoneEnabled = enabled;
    this.onMicrophoneEnabledChange(enabled);
    return enabled;
  }

  prewarmAcknowledgement() {
    const locale = compactRecognitionContext(this.getRecognitionContext()).locale_hint;
    const pending = this.output?.prewarm?.(ACKNOWLEDGEMENT_TEXT, locale);
    if (pending?.catch) void pending.catch(() => {});
  }

  handleOutputEvent(event) {
    const trace = this.output?.traceId || "-";
    const elapsed = Number(event?.elapsedMs || 0) / 1000;
    if (event?.type === "request.start") {
      if (event.segment === 0) this.latency.markTtsRequest();
      this.log.info?.(`[叙华][trace=${trace}] tts.request.start segment=${event.segment} reason=${event.reason}`);
    } else if (event?.type === "first_audio_chunk") {
      if (event.segment === 0) this.latency.markFirstAudio();
      this.log.info?.(`[叙华][trace=${trace}] tts.first_audio_chunk segment=${event.segment} +${elapsed.toFixed(3)}s`);
    } else if (event?.type === "playing" || event?.type === "fallback.playing") {
      if (event.segment === 0) this.latency.markPlaying(trace);
      this.log.info?.(`[叙华][trace=${trace}] tts.${event.type} segment=${event.segment} +${elapsed.toFixed(3)}s`);
      this.dispatchMany([
        { type: "turn.idle" },
        { type: "output.speaking" },
      ]);
    } else if (event?.type === "segment.complete") {
      this.log.info?.(`[叙华][trace=${trace}] tts.segment.complete segment=${event.segment} +${elapsed.toFixed(3)}s`);
    }
  }

  handlePlayingChange(playing) {
    if (playing) {
      this.dispatchMany([
        { type: "turn.idle" },
        { type: "output.speaking" },
      ]);
    } else if (this.output?.pipelineActive) {
      this.dispatchVoice({ type: "output.pending" });
    } else {
      this.dispatchVoice({ type: "output.idle" });
    }
  }

  handleOutputTerminal({ failed, reason } = {}) {
    this.input.blockFor(450);
    this.dispatchMany([
      { type: "turn.idle" },
      { type: "output.idle" },
    ]);

    // TTS is an output capability, not the realtime session transport. A
    // provider/audio failure must stop this playback attempt without poisoning
    // the microphone, ASR, WebSocket, or the next turn. Keep the session in a
    // listening-capable state and surface the problem as a recoverable error.
    if (failed) {
      this.reportOutputError(reason || "speech_output_failed");
      this.settleListening();
      return;
    }
    this.settleListening();
  }

  clearError() {
    this.onErrorState(null);
  }

  reportError(value) {
    const error = value instanceof Error ? value : new Error(String(value || "voice_error"));
    this.onErrorState(error);
    this.dispatchVoice({ type: "fault.raise" });
    this.getCallbacks()?.onError?.(error);
    return error;
  }

  reportOutputError(value) {
    const error = value instanceof Error ? value : new Error(String(value || "speech_output_failed"));
    this.onErrorState(error);
    this.getCallbacks()?.onError?.(error);
    return error;
  }

  reportInputError(value) {
    const error = value instanceof Error ? value : new Error(String(value || "voice_input_error"));
    this.onErrorState(error);
    this.getCallbacks()?.onError?.(error);
    return error;
  }

  handleTransportFailure() {
    this.cleanup();
    this.reportError("voice_socket_send_failed");
    return false;
  }

  settleListening() {
    if (this.input.utteranceActive
      || this.output?.pipelineActive
      || isVoiceAssistantPending(this.getMachine())) return false;
    this.dispatchMany([
      { type: "fault.clear" },
      { type: "input.idle" },
      { type: "turn.idle" },
      { type: "output.idle" },
    ]);
    return true;
  }

  markThinking() {
    this.dispatchMany([
      { type: "input.idle" },
      { type: "turn.thinking" },
    ]);
  }

  send(payload) {
    return this.connection.sendJson(payload);
  }

  sendRecognitionContext(context = this.getRecognitionContext()) {
    return this.send({
      type: "context",
      ...compactRecognitionContext(context),
    });
  }

  syncRecognitionContext(context = this.getRecognitionContext()) {
    if (!this.connection.connected) return false;
    return this.sendRecognitionContext(context) || this.handleTransportFailure();
  }

  clearBargeInCandidate() {
    return this.input.clearBargeInCandidate();
  }

  stopSpeech(bargeIn = false, notifyServer = true) {
    this.input.clearBargeInCandidate();
    this.turns.ignoreActive();
    this.output?.stop();
    this.dispatchMany([
      { type: "output.idle" },
      { type: "turn.idle" },
    ]);
    if (bargeIn) this.input.unblock();
    else this.input.blockFor(450);
    let sent = true;
    if (bargeIn) {
      if (notifyServer) sent = this.send({ type: "barge_in" });
      this.getCallbacks()?.onBargeIn?.();
    }
    if (!sent) return this.handleTransportFailure();
    return true;
  }

  confirmBargeInFromAsr() {
    if (!this.input.confirmBargeInCandidate()) return false;
    if (!this.stopSpeech(true, true)) return false;
    this.dispatchVoice({ type: "input.speaking" });
    return true;
  }

  beginSpeechStream(locale = "") {
    this.dispatchMany([
      { type: "input.idle" },
      { type: "turn.thinking" },
      { type: "output.pending" },
    ]);
    const generation = this.output?.begin(locale);
    this.input.resetOnset();
    return generation;
  }

  appendSpeechDelta(text, locale = "") {
    const delta = String(text || "");
    if (!delta) return false;
    if (!this.output?.pipelineActive) this.beginSpeechStream(locale);
    return this.output?.append(delta, locale) ?? false;
  }

  finishSpeechStream(fallbackText = "", locale = "") {
    if (!this.output?.pipelineActive) this.beginSpeechStream(locale);
    return this.output?.finish(fallbackText, locale) ?? false;
  }

  routeServerEvent(message) {
    const recognition = compactRecognitionContext(this.getRecognitionContext());
    const machine = this.getMachine();
    const accepted = routeVoiceServerEvent(message, {
      state: {
        input: this.input.state,
        machine,
        status: deriveVoiceStatus(machine),
        turns: this.turns,
        output: this.output,
        presenter: this.transcript,
        bargeInPhase: this.input.bargeInPhase,
        localeHint: recognition.locale_hint,
      },
      actions: {
        dispatchMany: (actions) => this.dispatchMany(actions),
        clearBargeInCandidate: () => this.clearBargeInCandidate(),
        confirmBargeInFromAsr: () => this.confirmBargeInFromAsr(),
        stopSpeech: (...args) => this.stopSpeech(...args),
        settleListening: () => this.settleListening(),
        markThinking: () => this.markThinking(),
        appendSpeechDelta: (...args) => {
          this.latency.markFirstDelta();
          return this.appendSpeechDelta(...args);
        },
        finishSpeechStream: (...args) => this.finishSpeechStream(...args),
        clearError: () => this.clearError(),
        reportError: (value) => this.reportError(value),
      },
      callbacks: this.getCallbacks(),
    });
    if (accepted && message?.type === "user.transcript") {
      this.latency.markTranscript();
      logFinalVoiceText(this.log, "用户", message.text);
    } else if (accepted && message?.type === "assistant.done") {
      logFinalVoiceText(this.log, "叙华", message.text);
    }
    return accepted;
  }

  processAudio(samples, inputRate) {
    const result = this.input.process(samples, inputRate, {
      connection: this.connection,
      output: this.output,
      assistantPending: isVoiceAssistantPending(this.getMachine()),
      onSpectrum: (value) => this.onSpectrum(value),
      onSpeaking: () => this.dispatchVoice({ type: "input.speaking" }),
      onTranscribing: () => this.dispatchVoice({ type: "input.transcribing" }),
      onTransportFailure: () => this.handleTransportFailure(),
    });
    const ended = result?.actions?.some(
      (action) => action?.kind === "json" && action?.payload?.type === "utterance.end",
    );
    if (ended) this.latency.markSpeechEnd(this.input.state.lastVoiceAt);
    return result;
  }

  pauseMicrophone() {
    if (!this.connection.connected) return false;
    const speechEndedAt = Number(this.input.state?.lastVoiceAt || 0);
    const finished = this.input.finishActiveUtterance({
      connection: this.connection,
      onTranscribing: () => this.dispatchVoice({ type: "input.transcribing" }),
      onTransportFailure: () => this.handleTransportFailure(),
    });
    if (!finished || !this.connection.connected) return false;
    if (speechEndedAt > 0) this.latency.markSpeechEnd(speechEndedAt);
    if (!this.connection.pauseInput()) return false;
    this.setMicrophoneEnabled(false);
    this.onSpectrum(Array(24).fill(0));
    return true;
  }

  async resumeMicrophone() {
    if (!this.connection.connected) return false;
    if (this.microphoneEnabled) return true;
    try {
      const resumed = await this.connection.resumeInput(
        (samples, inputRate) => this.processAudio(samples, inputRate),
      );
      if (!resumed) return false;
      this.input.resetOnset();
      this.clearError();
      this.setMicrophoneEnabled(true);
      this.settleListening();
      return true;
    } catch (error) {
      this.reportInputError(error);
      return false;
    }
  }

  toggleMicrophone() {
    return this.microphoneEnabled ? this.pauseMicrophone() : this.resumeMicrophone();
  }

  cleanup() {
    this.latency.clear();
    this.transcript.clear(true);
    this.stopSpeech(false);
    this.turns.reset();
    this.input.reset({ resetIds: true, discardResampler: true });
    this.connection.stop();
    this.setMicrophoneEnabled(false);
    this.onSpectrum(Array(24).fill(0));
    this.dispatchVoice({ type: "transport.idle" });
  }

  async start() {
    const machine = this.getMachine();
    if (machine?.transport === VOICE_TRANSPORT_PHASE.CONNECTED
      || this.connection.starting
      || this.connection.connected
      || deriveVoiceStatus(machine) === REALTIME_VOICE_STATUS.CONNECTING) return false;

    this.transcript.clear(true);
    this.input.reset({ resetIds: true, discardResampler: true });
    this.latency.clear();
    this.clearError();
    this.dispatchVoice({ type: "transport.connecting" });
    this.prewarmAcknowledgement();

    try {
      const started = await this.connection.start(this.websocketPath, {
        onOpen: () => {
          if (!this.sendRecognitionContext()) throw new Error("voice_socket_send_failed");
        },
        onMessage: (message) => this.routeServerEvent(message),
        onSamples: (samples, inputRate) => this.processAudio(samples, inputRate),
        onClose: (event) => {
          const statusBeforeClose = deriveVoiceStatus(this.getMachine());
          this.cleanup();
          if (event.code !== 1000 && statusBeforeClose !== REALTIME_VOICE_STATUS.IDLE) {
            this.reportError("voice_socket_closed");
          }
        },
      });
      if (!started) return false;
      this.dispatchVoice({ type: "transport.connected" });
      this.setMicrophoneEnabled(true);
      this.settleListening();
      return true;
    } catch (error) {
      this.cleanup();
      this.reportError(error);
      return false;
    }
  }

  stop() {
    this.cleanup();
    this.clearError();
    return true;
  }

  sendText(value) {
    const text = String(value || "").trim();
    if (!text || !this.connection.connected) return false;
    const sent = this.send({ type: "text", text });
    if (!sent) return this.handleTransportFailure();
    this.latency.clear();
    this.transcript.clear(true);
    this.input.supersedeUtterance();
    this.stopSpeech(true, false);
    this.markThinking();
    return true;
  }

  destroy() {
    this.cleanup();
    this.output?.dispose?.();
  }
}

export { ACKNOWLEDGEMENT_TEXT };
