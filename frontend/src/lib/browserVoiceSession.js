import {
  deriveVoiceStatus,
  isVoiceAssistantPending,
  REALTIME_VOICE_STATUS,
  VOICE_TRANSPORT_PHASE,
} from "../hooks/voiceState.js";
import { VoiceConnectionController } from "./voiceConnection.js";
import { routeVoiceServerEvent } from "./voiceEventRouter.js";
import { VoiceInputController } from "./voiceInputController.js";
import { VoiceOutputController } from "./voiceOutput.js";
import {
  compactRecognitionContext,
  VoiceTurnTracker,
} from "./voiceProtocol.js";
import { VoiceTranscriptPresenter } from "./voiceTranscriptPresenter.js";

function noop() {}

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
    connection = new VoiceConnectionController(),
    input = new VoiceInputController(),
    turns = new VoiceTurnTracker(),
    transcript = null,
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
    this.connection = connection;
    this.input = input;
    this.turns = turns;
    this.log = log;
    this.transcript = transcript || new VoiceTranscriptPresenter({ getCallbacks });
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

  handleOutputEvent(event) {
    const trace = this.output?.traceId || "-";
    const elapsed = Number(event?.elapsedMs || 0) / 1000;
    if (event?.type === "request.start") {
      this.log.info?.(`[叙华][trace=${trace}] tts.request.start segment=${event.segment} reason=${event.reason}`);
    } else if (event?.type === "first_audio_chunk") {
      this.log.info?.(`[叙华][trace=${trace}] tts.first_audio_chunk segment=${event.segment} +${elapsed.toFixed(3)}s`);
    } else if (event?.type === "playing") {
      this.log.info?.(`[叙华][trace=${trace}] tts.playing segment=${event.segment} +${elapsed.toFixed(3)}s`);
      this.dispatchMany([
        { type: "turn.idle" },
        { type: "output.speaking" },
      ]);
    } else if (event?.type === "segment.complete") {
      this.log.info?.(`[叙华][trace=${trace}] tts.sentence.complete segment=${event.segment} +${elapsed.toFixed(3)}s`);
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

  handleOutputTerminal({ failed } = {}) {
    this.input.blockFor(450);
    this.settleListening();
    if (failed) this.reportError("speech_output_failed");
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
    return this.sendRecognitionContext(context);
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
    if (bargeIn) {
      if (notifyServer) this.send({ type: "barge_in" });
      this.getCallbacks()?.onBargeIn?.();
    }
    return true;
  }

  confirmBargeInFromAsr() {
    if (!this.input.confirmBargeInCandidate()) return false;
    this.stopSpeech(true, true);
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
    return routeVoiceServerEvent(message, {
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
        appendSpeechDelta: (...args) => this.appendSpeechDelta(...args),
        finishSpeechStream: (...args) => this.finishSpeechStream(...args),
        clearError: () => this.clearError(),
        reportError: (value) => this.reportError(value),
      },
      callbacks: this.getCallbacks(),
    });
  }

  processAudio(samples, inputRate) {
    return this.input.process(samples, inputRate, {
      connection: this.connection,
      output: this.output,
      assistantPending: isVoiceAssistantPending(this.getMachine()),
      onSpectrum: (value) => this.onSpectrum(value),
      onSpeaking: () => this.dispatchVoice({ type: "input.speaking" }),
      onTranscribing: () => this.dispatchVoice({ type: "input.transcribing" }),
    });
  }

  cleanup() {
    this.transcript.clear(true);
    this.stopSpeech(false);
    this.input.reset({ resetIds: true, discardResampler: true });
    this.connection.stop();
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
    this.clearError();
    this.dispatchVoice({ type: "transport.connecting" });

    try {
      const started = await this.connection.start(this.websocketPath, {
        onOpen: () => this.sendRecognitionContext(),
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
    if (!text) return false;
    this.stopSpeech(true);
    const sent = this.send({ type: "text", text });
    if (sent) this.markThinking();
    return sent;
  }

  destroy() {
    this.cleanup();
  }
}
