import { useCallback, useEffect, useRef } from "react";

import TextConversationSession from "../lib/textConversationSession.js";

function noop() {}

export function useTextConversation({
  apiBase = "",
  fetchFn = globalThis.fetch,
  sessionId = "",
  category = "",
  localeHint = "",
  onSubmit = noop,
  onEvent = noop,
  onSpeechDelta = noop,
  onSpeechDone = noop,
  onSpeechStop = noop,
  onError = noop,
  log = console,
} = {}) {
  const contextRef = useRef(null);
  contextRef.current = { sessionId, category, localeHint };

  const callbacksRef = useRef(null);
  callbacksRef.current = {
    onSubmit,
    onEvent,
    onSpeechDelta,
    onSpeechDone,
    onSpeechStop,
    onError,
  };

  const sessionRef = useRef(null);
  if (!sessionRef.current) {
    sessionRef.current = new TextConversationSession({
      apiBase,
      fetchFn,
      getContext: () => contextRef.current,
      onSubmit: (text) => callbacksRef.current.onSubmit(text),
      onEvent: (event) => callbacksRef.current.onEvent(event),
      onSpeechDelta: (text, locale) => callbacksRef.current.onSpeechDelta(text, locale),
      onSpeechDone: (text, locale) => callbacksRef.current.onSpeechDone(text, locale),
      onSpeechStop: () => callbacksRef.current.onSpeechStop(),
      onError: (error) => callbacksRef.current.onError(error),
      log,
    });
  }
  sessionRef.current.setApiBase(apiBase);
  sessionRef.current.fetchFn = fetchFn;
  sessionRef.current.log = log;

  const ask = useCallback((text) => sessionRef.current.ask(text), []);
  const interrupt = useCallback(
    (options) => sessionRef.current.supersede(options),
    [],
  );

  useEffect(() => () => {
    sessionRef.current?.destroy();
  }, []);

  return { ask, interrupt };
}

export default useTextConversation;
