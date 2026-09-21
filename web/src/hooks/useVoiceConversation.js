import { useCallback, useEffect, useRef, useState } from "react";
import {
  REALTIME_VOICE_STATUS,
  VOICE_OUTPUT_PHASE,
  VOICE_TRANSPORT_PHASE,
} from "./voiceState.js";
import { useVoiceMachineState } from "./useVoiceMachineState.js";
import { BrowserVoiceSession } from "../lib/browserVoiceSession.js";

export { REALTIME_VOICE_STATUS };

function createDefaultVoiceSession(options) {
  return new BrowserVoiceSession(options);
}

export function useVoiceConversation({
  websocketPath = "/api/voice",
  recognitionContext = null,
  onUserPartial,
  onUserTranscript,
  onAssistantTranscript,
  onBargeIn,
  onSources,
  onError,
  createSession = createDefaultVoiceSession,
} = {}) {
  const {
    state: voiceMachine,
    stateRef: voiceMachineRef,
    status,
    dispatch: dispatchVoice,
    dispatchMany,
  } = useVoiceMachineState();
  const [error, setError] = useState(null);
  const [spectrum, setSpectrum] = useState(() => Array(24).fill(0));
  const [microphoneEnabled, setMicrophoneEnabled] = useState(false);

  const connected = voiceMachine.transport === VOICE_TRANSPORT_PHASE.CONNECTED;
  const isPlaying = voiceMachine.output === VOICE_OUTPUT_PHASE.SPEAKING;
  const isSpeechPending = voiceMachine.output !== VOICE_OUTPUT_PHASE.IDLE;

  const recognitionContextRef = useRef(recognitionContext);
  recognitionContextRef.current = recognitionContext;

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
    setSpectrum,
    setMicrophoneEnabled,
  };

  const sessionRef = useRef(null);
  if (!sessionRef.current) {
    sessionRef.current = createSession({
      websocketPath,
      getMachine: () => voiceMachineRef.current,
      dispatchVoice: (action) => bindingsRef.current.dispatchVoice(action),
      dispatchMany: (actions) => bindingsRef.current.dispatchMany(actions),
      getRecognitionContext: () => recognitionContextRef.current,
      getCallbacks: () => callbacksRef.current,
      onErrorState: (value) => bindingsRef.current.setError(value),
      onSpectrum: (value) => bindingsRef.current.setSpectrum(value),
      onMicrophoneEnabledChange: (value) => bindingsRef.current.setMicrophoneEnabled(value),
    });
  }
  sessionRef.current.setWebsocketPath(websocketPath);

  const start = useCallback(() => sessionRef.current.start(), []);
  const stop = useCallback(() => sessionRef.current.stop(), []);
  const toggleMicrophone = useCallback(() => sessionRef.current.toggleMicrophone(), []);
  const pauseMicrophone = useCallback(() => sessionRef.current.pauseMicrophone(), []);
  const resumeMicrophone = useCallback(() => sessionRef.current.resumeMicrophone(), []);
  const sendText = useCallback((value) => sessionRef.current.sendText(value), []);
  const stopSpeaking = useCallback(() => sessionRef.current.stopSpeech(false), []);
  const appendSpeechDelta = useCallback(
    (text, locale = "") => sessionRef.current.appendSpeechDelta(text, locale),
    [],
  );
  const finishSpeechStream = useCallback(
    (text = "", locale = "") => sessionRef.current.finishSpeechStream(text, locale),
    [],
  );

  useEffect(() => {
    if (connected) sessionRef.current.syncRecognitionContext(recognitionContext);
  }, [connected, recognitionContext]);

  useEffect(() => () => {
    sessionRef.current?.destroy();
  }, []);

  return {
    status,
    error,
    isConnected: connected,
    isMicrophoneEnabled: microphoneEnabled,
    isPlaying,
    isSpeechPending,
    spectrum,
    start,
    stop,
    toggleMicrophone,
    pauseMicrophone,
    resumeMicrophone,
    sendText,
    stopSpeaking,
    appendSpeechDelta,
    finishSpeechStream,
  };
}

export default useVoiceConversation;
