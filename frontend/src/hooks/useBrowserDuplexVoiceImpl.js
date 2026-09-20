import { useCallback, useEffect, useRef, useState } from "react";
import {
  deriveVoiceStatus,
  isVoiceAssistantPending,
  REALTIME_VOICE_STATUS,
  VOICE_OUTPUT_PHASE,
  VOICE_TRANSPORT_PHASE,
} from "./voiceState.js";
import { useVoiceMachineState } from "./useVoiceMachineState.js";
import {
  BARGE_IN_PHASE,
  beginBargeInCandidate as makeBargeInCandidate,
  confirmBargeIn,
  createBargeInState,
} from "./bargeInState.js";
import { VoiceConnectionController } from "../lib/voiceConnection.js";
import { routeVoiceServerEvent } from "../lib/voiceEventRouter.js";
import {
  createVoiceInputState,
  processVoiceInputFrame,
  resetVoiceInputPhase,
  resetVoiceOnset,
} from "../lib/voiceInput.js";
import { VoiceOutputController } from "../lib/voiceOutput.js";
import {
  compactRecognitionContext,
  VoiceTurnTracker,
} from "../lib/voiceProtocol.js";
import { VoiceTranscriptPresenter } from "../lib/voiceTranscriptPresenter.js";

export function useBrowserDuplexVoice({
  websocketPath = "/api/voice",
  recognitionContext = null,
  onUserPartial,
  onUserTranscript,
  onAssistantTranscript,
  onBargeIn,
  onSources,
  onError,
} = {}) {
  const {
    state: voiceMachine,
    stateRef: voiceMachineRef,
    status,
    dispatch: dispatchVoice,
    dispatchMany,
  } = useVoiceMachineState();
  const [error, setError] = useState(null);
  const [isMuted, setMuted] = useState(false);
  const [spectrum, setSpectrum] = useState(() => Array(24).fill(0));

  const connected = voiceMachine.transport === VOICE_TRANSPORT_PHASE.CONNECTED;
  const isPlaying = voiceMachine.output === VOICE_OUTPUT_PHASE.SPEAKING;
  const isSpeechPending = voiceMachine.output !== VOICE_OUTPUT_PHASE.IDLE;

  const recognitionContextRef = useRef(recognitionContext);
  recognitionContextRef.current = recognitionContext;
  const recognitionContextKey = JSON.stringify(compactRecognitionContext(recognitionContext));
  const voiceConnectionRef = useRef(null);
  const voiceInputRef = useRef(createVoiceInputState());
  const voiceOutputRef = useRef(null);
  const voiceTurnsRef = useRef(null);
  const voiceTranscriptRef = useRef(null);
  const mutedRef = useRef(false);
  const inputBlockedUntilRef = useRef(0);
  const bargeInRef = useRef(createBargeInState());
  const callbacks = useRef({
    onUserPartial,
    onUserTranscript,
    onAssistantTranscript,
    onBargeIn,
    onSources,
    onError,
  });
  callbacks.current = {
    onUserPartial,
    onUserTranscript,
    onAssistantTranscript,
    onBargeIn,
    onSources,
    onError,
  };

  if (!voiceConnectionRef.current) voiceConnectionRef.current = new VoiceConnectionController();
  if (!voiceTurnsRef.current) voiceTurnsRef.current = new VoiceTurnTracker();
  if (!voiceTranscriptRef.current) {
    voiceTranscriptRef.current = new VoiceTranscriptPresenter({
      getCallbacks: () => callbacks.current,
    });
  }

  const settleListening = useCallback(() => {
    if (voiceInputRef.current.utteranceActive
      || voiceOutputRef.current?.pipelineActive
      || isVoiceAssistantPending(voiceMachineRef.current)) return false;
    dispatchMany([
      { type: "fault.clear" },
      { type: "input.idle" },
      { type: "turn.idle" },
      { type: "output.idle" },
    ]);
    return true;
  }, [dispatchMany, voiceMachineRef]);

  const markThinking = useCallback(() => {
    dispatchMany([
      { type: "input.idle" },
      { type: "turn.thinking" },
    ]);
  }, [dispatchMany]);

  const reportError = useCallback((value) => {
    const next = value instanceof Error ? value : new Error(String(value || "voice_error"));
    setError(next);
    dispatchVoice({ type: "fault.raise" });
    callbacks.current.onError?.(next);
  }, [dispatchVoice]);

  if (!voiceOutputRef.current) {
    voiceOutputRef.current = new VoiceOutputController({
      websocketPath,
      getRecognitionContext: () => recognitionContextRef.current,
      onEvent: (event) => {
        const trace = voiceOutputRef.current?.traceId || "-";
        const elapsed = Number(event.elapsedMs || 0) / 1000;
        if (event.type === "request.start") {
          console.info(`[叙华][trace=${trace}] tts.request.start segment=${event.segment} reason=${event.reason}`);
        } else if (event.type === "first_audio_chunk") {
          console.info(`[叙华][trace=${trace}] tts.first_audio_chunk segment=${event.segment} +${elapsed.toFixed(3)}s`);
        } else if (event.type === "playing") {
          console.info(`[叙华][trace=${trace}] tts.playing segment=${event.segment} +${elapsed.toFixed(3)}s`);
          dispatchMany([
            { type: "turn.idle" },
            { type: "output.speaking" },
          ]);
        } else if (event.type === "segment.complete") {
          console.info(`[叙华][trace=${trace}] tts.sentence.complete segment=${event.segment} +${elapsed.toFixed(3)}s`);
        }
      },
      onPlayingChange: (playing) => {
        if (playing) {
          dispatchMany([
            { type: "turn.idle" },
            { type: "output.speaking" },
          ]);
        } else if (voiceOutputRef.current?.pipelineActive) {
          dispatchVoice({ type: "output.pending" });
        } else {
          dispatchVoice({ type: "output.idle" });
        }
      },
      onTerminal: ({ failed }) => {
        inputBlockedUntilRef.current = performance.now() + 450;
        settleListening();
        if (failed) reportError("speech_output_failed");
      },
    });
  }
  voiceOutputRef.current.setWebsocketPath(websocketPath);

  const send = useCallback((payload) => {
    return voiceConnectionRef.current?.sendJson(payload) ?? false;
  }, []);

  const sendRecognitionContext = useCallback(() => {
    return send({
      type: "context",
      ...compactRecognitionContext(recognitionContextRef.current),
    });
  }, [send]);

  const clearBargeInCandidate = useCallback(() => {
    bargeInRef.current = createBargeInState();
  }, []);

  const stopSpeech = useCallback((bargeIn = false, notifyServer = true) => {
    clearBargeInCandidate();
    voiceTurnsRef.current.ignoreActive();
    voiceOutputRef.current?.stop();
    dispatchMany([
      { type: "output.idle" },
      { type: "turn.idle" },
    ]);
    inputBlockedUntilRef.current = bargeIn ? 0 : performance.now() + 450;
    if (bargeIn) {
      if (notifyServer) send({ type: "barge_in" });
      callbacks.current.onBargeIn?.();
    }
  }, [clearBargeInCandidate, dispatchMany, send]);

  const confirmBargeInFromAsr = useCallback(() => {
    const confirmed = confirmBargeIn(bargeInRef.current);
    if (!confirmed.confirmed) return false;
    clearBargeInCandidate();
    stopSpeech(true, true);
    dispatchVoice({ type: "input.speaking" });
    return true;
  }, [clearBargeInCandidate, dispatchVoice, stopSpeech]);

  const beginBargeInCandidate = useCallback((utteranceId, startedAt) => {
    if (bargeInRef.current.phase === BARGE_IN_PHASE.TENTATIVE) return false;
    if (!voiceOutputRef.current?.pipelineActive
      && !isVoiceAssistantPending(voiceMachineRef.current)
      && !voiceOutputRef.current?.playing) return false;
    bargeInRef.current = makeBargeInCandidate(
      bargeInRef.current,
      utteranceId,
      startedAt,
    );
    return true;
  }, [voiceMachineRef]);

  const beginSpeechStream = useCallback((locale = "") => {
    dispatchMany([
      { type: "input.idle" },
      { type: "turn.thinking" },
      { type: "output.pending" },
    ]);
    const generation = voiceOutputRef.current?.begin(locale);
    resetVoiceOnset(voiceInputRef.current);
    return generation;
  }, [dispatchMany]);

  const appendSpeechDelta = useCallback((text, locale = "") => {
    const delta = String(text || "");
    if (!delta) return false;
    if (!voiceOutputRef.current?.pipelineActive) beginSpeechStream(locale);
    return voiceOutputRef.current?.append(delta, locale) ?? false;
  }, [beginSpeechStream]);

  const finishSpeechStream = useCallback((fallbackText = "", locale = "") => {
    if (!voiceOutputRef.current?.pipelineActive) beginSpeechStream(locale);
    return voiceOutputRef.current?.finish(fallbackText, locale) ?? false;
  }, [beginSpeechStream]);

  const speak = useCallback((text, locale = "") => {
    const content = String(text || "").trim();
    if (!content) return false;
    beginSpeechStream(locale);
    voiceOutputRef.current?.append(content, locale);
    return voiceOutputRef.current?.finish("", locale) ?? false;
  }, [beginSpeechStream]);

  const routeServerEvent = useCallback((message) => {
    const recognition = compactRecognitionContext(recognitionContextRef.current);
    return routeVoiceServerEvent(message, {
      state: {
        input: voiceInputRef.current,
        machine: voiceMachineRef.current,
        status: deriveVoiceStatus(voiceMachineRef.current),
        turns: voiceTurnsRef.current,
        output: voiceOutputRef.current,
        presenter: voiceTranscriptRef.current,
        bargeInPhase: bargeInRef.current.phase,
        localeHint: recognition.locale_hint,
      },
      actions: {
        dispatchMany,
        clearBargeInCandidate,
        confirmBargeInFromAsr,
        stopSpeech,
        settleListening,
        markThinking,
        appendSpeechDelta,
        finishSpeechStream,
        clearError: () => setError(null),
        reportError,
      },
      callbacks: callbacks.current,
    });
  }, [
    appendSpeechDelta,
    clearBargeInCandidate,
    confirmBargeInFromAsr,
    dispatchMany,
    finishSpeechStream,
    markThinking,
    reportError,
    settleListening,
    stopSpeech,
    voiceMachineRef,
  ]);

  const processAudio = useCallback((samples, inputRate) => {
    if (mutedRef.current) return;
    const connection = voiceConnectionRef.current;
    const input = voiceInputRef.current;
    const output = voiceOutputRef.current;
    const result = processVoiceInputFrame(input, {
      samples,
      inputRate,
      now: performance.now(),
      blockedUntil: inputBlockedUntilRef.current,
      transportReady: Boolean(connection?.connected),
      playbackActive: Boolean(output?.playing),
      agentBusy: Boolean(
        output?.pipelineActive
        || isVoiceAssistantPending(voiceMachineRef.current)
        || output?.playing
      ),
      bargeInTentative: bargeInRef.current.phase === BARGE_IN_PHASE.TENTATIVE,
    });

    if (result.spectrum) setSpectrum(result.spectrum);

    result.actions.forEach((action, index) => {
      if (!connection?.connected) return;
      if (action.kind === "json") connection.sendJson(action.payload);
      else connection.sendRaw(action.payload);

      if (index === 0 && result.started) {
        if (result.started.shouldInterrupt) {
          beginBargeInCandidate(result.started.utteranceId, input.utteranceStartedAt);
        } else if (result.nextStatus === "user_speaking") {
          dispatchVoice({ type: "input.speaking" });
        }
      }
    });

    if (!result.started && result.nextStatus === "transcribing") {
      dispatchVoice({ type: "input.transcribing" });
    }
  }, [beginBargeInCandidate, dispatchVoice, voiceMachineRef]);

  const cleanup = useCallback(() => {
    voiceTranscriptRef.current?.clear(true);
    stopSpeech(false);
    resetVoiceInputPhase(voiceInputRef.current, {
      resetIds: true,
      discardResampler: true,
    });
    clearBargeInCandidate();
    voiceConnectionRef.current?.stop();
    dispatchVoice({ type: "transport.idle" });
  }, [clearBargeInCandidate, dispatchVoice, stopSpeech]);

  const start = useCallback(async () => {
    const connection = voiceConnectionRef.current;
    if (connected
      || connection?.starting
      || connection?.connected
      || deriveVoiceStatus(voiceMachineRef.current) === REALTIME_VOICE_STATUS.CONNECTING) return;

    voiceTranscriptRef.current?.clear(true);
    resetVoiceInputPhase(voiceInputRef.current, {
      resetIds: true,
      discardResampler: true,
    });
    setError(null);
    dispatchVoice({ type: "transport.connecting" });

    try {
      const started = await connection.start(websocketPath, {
        onOpen: sendRecognitionContext,
        onMessage: routeServerEvent,
        onSamples: processAudio,
        onClose: (event) => {
          const statusBeforeClose = deriveVoiceStatus(voiceMachineRef.current);
          cleanup();
          if (event.code !== 1000 && statusBeforeClose !== REALTIME_VOICE_STATUS.IDLE) {
            reportError("voice_socket_closed");
          }
        },
      });
      if (!started) return;

      dispatchVoice({ type: "transport.connected" });
      settleListening();
    } catch (startError) {
      cleanup();
      reportError(startError);
    }
  }, [
    cleanup,
    connected,
    dispatchVoice,
    processAudio,
    reportError,
    routeServerEvent,
    sendRecognitionContext,
    settleListening,
    voiceMachineRef,
    websocketPath,
  ]);

  const stop = useCallback(() => {
    cleanup();
    setError(null);
  }, [cleanup]);

  const toggleMute = useCallback(() => {
    const next = !mutedRef.current;
    mutedRef.current = next;
    setMuted(next);
    if (next) {
      voiceInputRef.current.resampler?.reset();
      resetVoiceOnset(voiceInputRef.current);
    }
    voiceConnectionRef.current?.media.setMuted(next);
    return next;
  }, []);

  useEffect(() => {
    if (connected) sendRecognitionContext();
  }, [connected, recognitionContextKey, sendRecognitionContext]);

  const sendText = useCallback((value) => {
    const text = String(value || "").trim();
    if (!text) return false;
    stopSpeech(true);
    const sent = send({ type: "text", text });
    if (sent) markThinking();
    return sent;
  }, [markThinking, send, stopSpeech]);

  const cancelResponse = useCallback(() => {
    stopSpeech(true);
    settleListening();
    return true;
  }, [settleListening, stopSpeech]);

  useEffect(() => () => {
    cleanup();
  }, [cleanup]);

  return {
    status,
    error,
    isMuted,
    isConnected: connected,
    isPlaying,
    isSpeechPending,
    spectrum,
    start,
    stop,
    toggleMute,
    mute: toggleMute,
    sendText,
    cancelResponse,
    speakText: speak,
    stopSpeaking: () => stopSpeech(false),
    beginSpeechStream,
    appendSpeechDelta,
    finishSpeechStream,
    sendToolResult: () => false,
  };
}

export default useBrowserDuplexVoice;
