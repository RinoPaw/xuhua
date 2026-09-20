import { useCallback, useEffect, useRef, useState } from "react";
import {
  REALTIME_VOICE_STATUS,
  VOICE_OUTPUT_PHASE,
  VOICE_TRANSPORT_PHASE,
} from "./voiceState.js";
import { useVoiceMachineState } from "./useVoiceMachineState.js";
import { BrowserVoiceSession } from "../lib/browserVoiceSession.js";
import { compactRecognitionContext } from "../lib/voiceProtocol.js";

export { REALTIME_VOICE_STATUS };

export function useVoiceConversation({
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

  const callbacksRef = useRef({
    onUserPartial,
    onUserTranscript,
    onAssistantTranscript,
    onBargeIn,
    onSources,
    onError,
  });
  callbacksRef.current = {
    onUserPartial,
    onUserTranscript,
    onAssistantTranscript,
    onBargeIn,
    onSources,
    onError,
  };

  const bindingsRef = useRef(null);
  bindingsRef.current = {
    dispatchVoice,
    dispatchMany,
    setError,
    setMuted,
    setSpectrum,
  };

  const sessionRef = useRef(null);
  if (!sessionRef.current) {
    sessionRef.current = new BrowserVoiceSession({
      websocketPath,
      getMachine: () => voiceMachineRef.current,
      dispatchVoice: (action) => bindingsRef.current.dispatchVoice(action),
      dispatchMany: (actions) => bindingsRef.current.dispatchMany(actions),
      getRecognitionContext: () => recognitionContextRef.current,
      getCallbacks: () => callbacksRef.current,
      onErrorState: (value) => bindingsRef.current.setError(value),
      onMutedChange: (value) => bindingsRef.current.setMuted(value),
      onSpectrum: (value) => bindingsRef.current.setSpectrum(value),
    });
  }
  sessionRef.current.setWebsocketPath(websocketPath);

  const start = useCallback(() => sessionRef.current.start(), []);
  const stop = useCallback(() => sessionRef.current.stop(), []);
  const toggleMute = useCallback(() => sessionRef.current.toggleMute(), []);
  const sendText = useCallback((value) => sessionRef.current.sendText(value), []);
  const cancelResponse = useCallback(() => sessionRef.current.cancelResponse(), []);
  const speak = useCallback((text, locale = "") => sessionRef.current.speak(text, locale), []);
  const stopSpeaking = useCallback(() => sessionRef.current.stopSpeech(false), []);
  const beginSpeechStream = useCallback(
    (locale = "") => sessionRef.current.beginSpeechStream(locale),
    [],
  );
  const appendSpeechDelta = useCallback(
    (text, locale = "") => sessionRef.current.appendSpeechDelta(text, locale),
    [],
  );
  const finishSpeechStream = useCallback(
    (text = "", locale = "") => sessionRef.current.finishSpeechStream(text, locale),
    [],
  );

  useEffect(() => {
    if (connected) sessionRef.current.syncRecognitionContext();
  }, [connected, recognitionContextKey]);

  useEffect(() => () => {
    sessionRef.current?.destroy();
  }, []);

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
    stopSpeaking,
    beginSpeechStream,
    appendSpeechDelta,
    finishSpeechStream,
    sendToolResult: () => false,
  };
}

export default useVoiceConversation;
