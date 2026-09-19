import { useCallback, useEffect, useRef, useState } from "react";
import {
  normalizeVoiceId,
  normalizeVoiceText,
  REALTIME_VOICE_STATUS,
} from "./voiceState.js";
import {
  BARGE_IN_PHASE,
  beginBargeInCandidate as makeBargeInCandidate,
  confirmBargeIn,
  createBargeInState,
  shouldConfirmBargeInText,
} from "./bargeInState.js";
import {
  applyFinalReveal,
  applyPartialReveal,
  createPartialRevealState,
  resetPartialReveal,
} from "../lib/partialReveal.js";
import {
  acceptAssistantTurn,
  assistantEventLocale,
  compactRecognitionContext,
  rememberIgnoredTurn,
} from "../lib/voiceProtocol.js";
import {
  acceptVoiceUtteranceMessage,
  createVoiceInputState,
  processVoiceInputFrame,
  resetVoiceInputPhase,
  resetVoiceOnset,
} from "../lib/voiceInput.js";
import { VoiceMediaController } from "../lib/voiceMedia.js";
import { VoiceOutputController } from "../lib/voiceOutput.js";
import {
  acceptServerVoiceError,
  acceptServerVoiceStatus,
} from "../lib/voiceServerEvents.js";
import {
  openVoiceSocket,
  parseSocketMessage,
  sendSocketJson,
} from "../lib/voiceTransport.js";

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
  const [status, setStatus] = useState(REALTIME_VOICE_STATUS.IDLE);
  const [error, setError] = useState(null);
  const [isMuted, setMuted] = useState(false);
  const [connected, setConnected] = useState(false);
  const [isPlaying, setIsPlaying] = useState(false);
  const [isSpeechPending, setSpeechPending] = useState(false);
  const [spectrum, setSpectrum] = useState(() => Array(24).fill(0));

  const socketRef = useRef(null);
  const recognitionContextRef = useRef(recognitionContext);
  recognitionContextRef.current = recognitionContext;
  const recognitionContextKey = JSON.stringify(compactRecognitionContext(recognitionContext));
  const transportGenerationRef = useRef(0);
  const statusRef = useRef(status);
  const voiceInputRef = useRef(createVoiceInputState());
  const voiceMediaRef = useRef(null);
  const voiceOutputRef = useRef(null);
  const mutedRef = useRef(false);
  const inputBlockedUntilRef = useRef(0);
  const assistantPendingRef = useRef(false);
  const bargeInRef = useRef(createBargeInState());
  const assistantTurnRef = useRef("");
  const ignoredAssistantTurnsRef = useRef(new Set());
  const partialRevealRef = useRef(createPartialRevealState());
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

  if (!voiceMediaRef.current) voiceMediaRef.current = new VoiceMediaController();

  const clearPartialReveal = useCallback((resetText = false) => {
    const reveal = partialRevealRef.current;
    if (reveal.timer !== null) {
      window.clearInterval(reveal.timer);
      reveal.timer = null;
    }
    resetPartialReveal(reveal, { clearText: resetText });
  }, []);

  const publishUserPartial = useCallback((message) => {
    const reveal = partialRevealRef.current;
    const applied = applyPartialReveal(reveal, message);
    if (!applied.accepted) return false;
    if (applied.startsNew) clearPartialReveal(false);
    callbacks.current.onUserPartial?.(reveal.visible, message);

    if (reveal.timer === null && reveal.visible.length < reveal.target.length) {
      reveal.timer = window.setInterval(() => {
        const current = partialRevealRef.current;
        if (current.visible.length >= current.target.length) {
          window.clearInterval(current.timer);
          current.timer = null;
          return;
        }
        current.visible += current.target[current.visible.length];
        callbacks.current.onUserPartial?.(current.visible, current.event);
      }, 26);
    }
    return true;
  }, [clearPartialReveal]);

  const publishUserTranscript = useCallback((message, transcript) => {
    const reveal = partialRevealRef.current;
    if (!applyFinalReveal(reveal, message, transcript)) return false;
    clearPartialReveal(false);
    callbacks.current.onUserTranscript?.(reveal.visible, message);
    return true;
  }, [clearPartialReveal]);

  const setStatusValue = useCallback((value) => {
    if (value === REALTIME_VOICE_STATUS.LISTENING
      && (voiceInputRef.current.utteranceActive
        || voiceOutputRef.current?.pipelineActive
        || assistantPendingRef.current)) return;
    statusRef.current = value;
    setStatus(value);
  }, []);

  const acceptUtteranceMessage = useCallback((message, options) => {
    return acceptVoiceUtteranceMessage(voiceInputRef.current, message, options);
  }, []);

  const reportError = useCallback((value) => {
    const next = value instanceof Error ? value : new Error(String(value || "voice_error"));
    setError(next);
    setStatusValue(REALTIME_VOICE_STATUS.ERROR);
    callbacks.current.onError?.(next);
  }, [setStatusValue]);

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
          setStatusValue(REALTIME_VOICE_STATUS.RESPONDING);
        } else if (event.type === "segment.complete") {
          console.info(`[叙华][trace=${trace}] tts.sentence.complete segment=${event.segment} +${elapsed.toFixed(3)}s`);
        }
      },
      onPlayingChange: (playing) => setIsPlaying(playing),
      onTerminal: ({ failed }) => {
        assistantPendingRef.current = false;
        setSpeechPending(false);
        inputBlockedUntilRef.current = performance.now() + 450;
        setStatusValue(REALTIME_VOICE_STATUS.LISTENING);
        if (failed) reportError("speech_output_failed");
      },
    });
  }
  voiceOutputRef.current.setWebsocketPath(websocketPath);

  const send = useCallback((payload) => {
    return sendSocketJson(socketRef.current, payload);
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
    rememberIgnoredTurn(ignoredAssistantTurnsRef.current, assistantTurnRef.current);
    assistantTurnRef.current = "";
    voiceOutputRef.current?.stop();
    assistantPendingRef.current = false;
    setSpeechPending(false);
    inputBlockedUntilRef.current = bargeIn ? 0 : performance.now() + 450;
    if (bargeIn) {
      if (notifyServer) send({ type: "barge_in" });
      callbacks.current.onBargeIn?.();
    }
  }, [clearBargeInCandidate, send]);

  const confirmBargeInFromAsr = useCallback(() => {
    const confirmed = confirmBargeIn(bargeInRef.current);
    if (!confirmed.confirmed) return false;
    clearBargeInCandidate();
    stopSpeech(true, true);
    setStatusValue(REALTIME_VOICE_STATUS.USER_SPEAKING);
    return true;
  }, [clearBargeInCandidate, setStatusValue, stopSpeech]);

  const beginBargeInCandidate = useCallback((utteranceId, startedAt) => {
    if (bargeInRef.current.phase === BARGE_IN_PHASE.TENTATIVE) return false;
    if (!voiceOutputRef.current?.pipelineActive
      && !assistantPendingRef.current
      && !voiceOutputRef.current?.playing) return false;
    bargeInRef.current = makeBargeInCandidate(
      bargeInRef.current,
      utteranceId,
      startedAt,
    );
    return true;
  }, []);

  const beginSpeechStream = useCallback((locale = "") => {
    assistantPendingRef.current = true;
    setSpeechPending(true);
    const generation = voiceOutputRef.current?.begin(locale);
    resetVoiceOnset(voiceInputRef.current);
    setStatusValue(REALTIME_VOICE_STATUS.THINKING);
    return generation;
  }, [setStatusValue]);

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

  const processAudio = useCallback((samples, inputRate) => {
    if (mutedRef.current) return;
    const socket = socketRef.current;
    const input = voiceInputRef.current;
    const output = voiceOutputRef.current;
    const result = processVoiceInputFrame(input, {
      samples,
      inputRate,
      now: performance.now(),
      blockedUntil: inputBlockedUntilRef.current,
      transportReady: Boolean(socket && socket.readyState === WebSocket.OPEN),
      playbackActive: Boolean(output?.playing),
      agentBusy: Boolean(output?.pipelineActive || assistantPendingRef.current || output?.playing),
      bargeInTentative: bargeInRef.current.phase === BARGE_IN_PHASE.TENTATIVE,
    });

    if (result.spectrum) setSpectrum(result.spectrum);

    result.actions.forEach((action, index) => {
      if (!socket || socket.readyState !== WebSocket.OPEN) return;
      if (action.kind === "json") socket.send(JSON.stringify(action.payload));
      else socket.send(action.payload);

      if (index === 0 && result.started) {
        if (result.started.shouldInterrupt) {
          beginBargeInCandidate(result.started.utteranceId, input.utteranceStartedAt);
        } else if (result.nextStatus === "user_speaking") {
          setStatusValue(REALTIME_VOICE_STATUS.USER_SPEAKING);
        }
      }
    });

    if (!result.started && result.nextStatus === "transcribing") {
      setStatusValue(REALTIME_VOICE_STATUS.TRANSCRIBING);
    }
  }, [beginBargeInCandidate, setStatusValue]);

  const cleanup = useCallback(() => {
    transportGenerationRef.current += 1;
    clearPartialReveal(true);
    stopSpeech(false);
    resetVoiceInputPhase(voiceInputRef.current, {
      resetIds: true,
      discardResampler: true,
    });
    clearBargeInCandidate();
    voiceMediaRef.current?.stop();
    const socket = socketRef.current;
    socketRef.current = null;
    if (socket && socket.readyState < WebSocket.CLOSING) {
      socket.close(1000, "client_stop");
    }
    setConnected(false);
  }, [clearBargeInCandidate, clearPartialReveal, stopSpeech]);

  const start = useCallback(async () => {
    if (connected || statusRef.current === REALTIME_VOICE_STATUS.CONNECTING) return;
    const generation = transportGenerationRef.current + 1;
    transportGenerationRef.current = generation;
    clearPartialReveal(true);
    resetVoiceInputPhase(voiceInputRef.current, {
      resetIds: true,
      discardResampler: true,
    });
    setError(null);
    setStatusValue(REALTIME_VOICE_STATUS.CONNECTING);

    try {
      const stream = await voiceMediaRef.current.requestStream();
      if (transportGenerationRef.current !== generation) {
        voiceMediaRef.current.stop();
        return;
      }

      const socket = await openVoiceSocket(websocketPath);
      socketRef.current = socket;
      if (transportGenerationRef.current !== generation) {
        socket.close(1000, "stale_voice_start");
        voiceMediaRef.current.stop();
        return;
      }

      sendRecognitionContext();
      socket.onmessage = (event) => {
        if (socketRef.current !== socket) return;
        const message = parseSocketMessage(event);
        if (!message) return;

        if (message.type === "status") {
          const decision = acceptServerVoiceStatus(message, {
            inputState: voiceInputRef.current,
            currentStatus: statusRef.current,
            bargeInTentative: bargeInRef.current.phase === BARGE_IN_PHASE.TENTATIVE,
            activeTurn: assistantTurnRef.current,
            assistantPending: assistantPendingRef.current,
            ignoredTurns: ignoredAssistantTurnsRef.current,
            speechPipeline: Boolean(voiceOutputRef.current?.pipelineActive),
            speechActive: Boolean(voiceOutputRef.current?.playing),
          });
          if (!decision.accepted) return;
          assistantTurnRef.current = decision.activeTurn;
          setStatusValue(decision.status);
          return;
        }

        if (message.type === "user.transcript") {
          if (!acceptUtteranceMessage(message)) return;
          voiceInputRef.current.activeUtteranceId = 0;
          const transcript = normalizeVoiceText(message.text);
          if (!transcript) {
            const wasCandidate = bargeInRef.current.phase === BARGE_IN_PHASE.TENTATIVE;
            if (wasCandidate) clearBargeInCandidate();
            if (!wasCandidate) setStatusValue(REALTIME_VOICE_STATUS.LISTENING);
            return;
          }

          if (bargeInRef.current.phase === BARGE_IN_PHASE.TENTATIVE) {
            confirmBargeInFromAsr();
          } else if (voiceOutputRef.current?.pipelineActive || voiceOutputRef.current?.playing) {
            stopSpeech(true, false);
          } else {
            rememberIgnoredTurn(ignoredAssistantTurnsRef.current, assistantTurnRef.current);
            assistantTurnRef.current = "";
          }
          assistantPendingRef.current = true;
          setStatusValue(REALTIME_VOICE_STATUS.THINKING);
          publishUserTranscript(message, transcript);
          return;
        }

        if (message.type === "user.partial") {
          if (!acceptUtteranceMessage(message)) return;
          if (bargeInRef.current.phase === BARGE_IN_PHASE.TENTATIVE) {
            if (!shouldConfirmBargeInText(message.text)) return;
            confirmBargeInFromAsr();
          }
          publishUserPartial(message);
          return;
        }

        if (message.type === "assistant.delta") {
          if (!acceptAssistantTurn(
            message,
            assistantTurnRef,
            ignoredAssistantTurnsRef.current,
          )) return;
          const locale = assistantEventLocale(
            message,
            compactRecognitionContext(recognitionContextRef.current).locale_hint,
          );
          callbacks.current.onAssistantTranscript?.(
            message.text || "",
            { done: false, locale },
          );
          appendSpeechDelta(message.text || "", locale);
          return;
        }

        if (message.type === "assistant.done") {
          if (!acceptAssistantTurn(
            message,
            assistantTurnRef,
            ignoredAssistantTurnsRef.current,
          )) return;
          const locale = assistantEventLocale(
            message,
            compactRecognitionContext(recognitionContextRef.current).locale_hint,
          );
          callbacks.current.onAssistantTranscript?.(
            message.text || "",
            { done: true, locale },
          );
          assistantPendingRef.current = false;
          finishSpeechStream(message.text || "", locale);
          const turnId = normalizeVoiceId(message.turn_id);
          if (turnId) {
            rememberIgnoredTurn(ignoredAssistantTurnsRef.current, turnId);
            if (assistantTurnRef.current === turnId) assistantTurnRef.current = "";
          }
          return;
        }

        if (message.type === "utterance.rejected") {
          if (!acceptUtteranceMessage(message)) return;
          const wasCandidate = bargeInRef.current.phase === BARGE_IN_PHASE.TENTATIVE;
          if (wasCandidate) clearBargeInCandidate();
          if (!wasCandidate) setStatusValue(REALTIME_VOICE_STATUS.LISTENING);
          voiceInputRef.current.activeUtteranceId = 0;
          return;
        }

        if (message.type === "sources") {
          if (!acceptAssistantTurn(
            message,
            assistantTurnRef,
            ignoredAssistantTurnsRef.current,
          )) return;
          callbacks.current.onSources?.(message.items || []);
          return;
        }

        if (message.type === "error") {
          if (!acceptServerVoiceError(message, {
            activeTurn: assistantTurnRef.current,
            assistantPending: assistantPendingRef.current,
            ignoredTurns: ignoredAssistantTurnsRef.current,
          })) return;
          stopSpeech(false, false);
          reportError(message.message || "voice_error");
        }
      };

      socket.onclose = (event) => {
        const isCurrentSocket = socketRef.current === socket;
        if (isCurrentSocket) cleanup();
        if (isCurrentSocket
          && event.code !== 1000
          && statusRef.current !== REALTIME_VOICE_STATUS.IDLE) {
          reportError("voice_socket_closed");
        }
      };

      await voiceMediaRef.current.attachProcessor(processAudio);
      if (transportGenerationRef.current !== generation) {
        voiceMediaRef.current.stop();
        return;
      }

      setConnected(true);
      setStatusValue(REALTIME_VOICE_STATUS.LISTENING);
    } catch (startError) {
      if (transportGenerationRef.current !== generation) return;
      cleanup();
      reportError(startError);
    }
  }, [
    acceptUtteranceMessage,
    appendSpeechDelta,
    cleanup,
    clearBargeInCandidate,
    clearPartialReveal,
    connected,
    confirmBargeInFromAsr,
    finishSpeechStream,
    processAudio,
    publishUserPartial,
    publishUserTranscript,
    reportError,
    sendRecognitionContext,
    setStatusValue,
    stopSpeech,
    websocketPath,
  ]);

  const stop = useCallback(() => {
    cleanup();
    setError(null);
    setStatusValue(REALTIME_VOICE_STATUS.IDLE);
  }, [cleanup, setStatusValue]);

  const toggleMute = useCallback(() => {
    const next = !mutedRef.current;
    mutedRef.current = next;
    setMuted(next);
    if (next) {
      voiceInputRef.current.resampler?.reset();
      resetVoiceOnset(voiceInputRef.current);
    }
    voiceMediaRef.current?.setMuted(next);
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
    if (sent) {
      assistantPendingRef.current = true;
      setStatusValue(REALTIME_VOICE_STATUS.THINKING);
    }
    return sent;
  }, [send, setStatusValue, stopSpeech]);

  const cancelResponse = useCallback(() => {
    stopSpeech(true);
    setStatusValue(REALTIME_VOICE_STATUS.LISTENING);
    return true;
  }, [setStatusValue, stopSpeech]);

  useEffect(() => () => {
    clearPartialReveal(true);
    cleanup();
  }, [clearPartialReveal, cleanup]);

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
