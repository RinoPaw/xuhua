import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { ArrowUp, ChatText, Microphone, MicrophoneSlash, SpinnerGap, X } from "@phosphor-icons/react";

import DigitalHuman from "../components/DigitalHuman.jsx";
import { Markdown } from "../components/ConversationMessage.jsx";
import { friendlyVoiceError } from "../components/VoiceControls.jsx";
import { useTextConversation } from "../hooks/useTextConversation.js";
import { REALTIME_VOICE_STATUS, useVoiceConversation } from "../hooks/useVoiceConversation.js";
import { createConversationSessionId } from "../lib/conversationSession.js";
import { conversationReducer, initialConversationState } from "../lib/conversationState.js";
import { personaDisplayState } from "../lib/displayMode.js";
import { getLocaleHint, getPreferredLocales } from "../lib/locale.js";
import { PersonaBrowserVoiceSession } from "../lib/personaBrowserVoiceSession.js";
import "./PersonaDisplayPage.css";

const LOCALE_HINT = getLocaleHint();
const PREFERRED_LOCALES = getPreferredLocales();

export function PersonaDisplayPage({ search = globalThis.location?.search || "" }) {
  const [sessionId] = useState(createConversationSessionId);
  const [conversation, dispatch] = useReducer(conversationReducer, {
    ...initialConversationState,
    sessionId,
  });
  const [composerOpen, setComposerOpen] = useState(false);
  const [draft, setDraft] = useState("");
  const personaSessionRef = useRef(null);
  const realtimeRef = useRef(null);
  const inputRef = useRef(null);
  const previewMode = personaDisplayState(search);
  const recognitionContext = useMemo(() => ({
    sessionId,
    localeHint: LOCALE_HINT,
    preferredLocales: PREFERRED_LOCALES,
  }), [sessionId]);
  const createSession = useCallback((options) => {
    const session = new PersonaBrowserVoiceSession(options);
    personaSessionRef.current = session;
    return session;
  }, []);

  const { ask: askText, interrupt: interruptText } = useTextConversation({
    sessionId,
    localeHint: LOCALE_HINT,
    onSubmit: (text) => dispatch({ type: "ask", text }),
    onEvent: (event) => dispatch({ type: "event", event }),
    onSpeechDelta: (text, locale) => realtimeRef.current?.appendSpeechDelta(text, locale),
    onSpeechDone: (text, locale) => realtimeRef.current?.finishSpeechStream(text, locale),
    onSpeechStop: () => realtimeRef.current?.stopSpeaking(),
    onError: () => dispatch({ type: "error", message: "回答服务暂时不可用" }),
  });

  const realtime = useVoiceConversation({
    websocketPath: "/api/voice",
    recognitionContext,
    createSession,
    onUserPartial: (text, event) => {
      if (personaSessionRef.current?.gate.sleeping) return;
      dispatch({
        type: "realtime.user.partial",
        text,
        utteranceId: event?.utterance_id,
        revision: event?.revision,
      });
    },
    onUserTranscript: (text, event) => {
      if (personaSessionRef.current?.gate.sleeping) return;
      dispatch({
        type: "realtime.user",
        text,
        utteranceId: event?.utterance_id,
        revision: event?.revision,
      });
    },
    onAssistantTranscript: (text, event) => dispatch({
      type: event?.done ? "realtime.answer.done" : "realtime.answer.delta",
      text,
    }),
    onBargeIn: () => {
      interruptText();
      dispatch({ type: "realtime.interrupted" });
    },
    onError: (error) => dispatch({
      type: "error",
      message: friendlyVoiceError(error, true),
    }),
  });
  realtimeRef.current = realtime;

  useEffect(() => {
    void realtime.start();
  }, [realtime.start]);

  useEffect(() => {
    if (composerOpen) inputRef.current?.focus();
  }, [composerOpen]);

  const mode = realtime.isPlaying ? "speaking" : previewMode;
  const lastUserIndex = conversation.messages.findLastIndex((message) => message.role === "user");
  const userMessage = lastUserIndex < 0 ? null : conversation.messages[lastUserIndex];
  const assistantMessage = lastUserIndex < 0
    ? conversation.messages.findLast((message) => message.role === "assistant")
    : conversation.messages.slice(lastUserIndex + 1).find((message) => message.role === "assistant");
  const connecting = realtime.status === REALTIME_VOICE_STATUS.CONNECTING;
  const voiceActive = realtime.isConnected && realtime.isMicrophoneEnabled;

  const handleVoice = () => {
    dispatch({ type: "clear.error" });
    if (realtime.isConnected) {
      void realtime.toggleMicrophone();
      return;
    }
    interruptText();
    if (["retrieving", "composing", "streaming"].includes(conversation.phase)) {
      dispatch({ type: "cancel" });
    }
    void realtime.start();
  };

  const submitText = (event) => {
    event.preventDefault();
    const text = draft.trim();
    if (!text || connecting) return;
    interruptText();
    if (realtime.isConnected) {
      if (!realtime.sendText(text)) return;
      dispatch({ type: "realtime.user", text });
    } else {
      void askText(text);
    }
    setDraft("");
    setComposerOpen(false);
  };

  return (
    <main className="app-shell persona-display" aria-label="叙华人物展示">
      <div className="workspace persona-display-workspace">
        <section className="left-panel persona-display-panel" aria-label="叙华对话">
          <DigitalHuman mode={mode} showBrand={false} />

          <div className="persona-dialogue" aria-live="polite">
            {userMessage && (
              <div className="persona-bubble persona-bubble-user">
                <Markdown text={userMessage.content} status={userMessage.status} />
              </div>
            )}
            {assistantMessage && (
              <div className="persona-bubble persona-bubble-assistant">
                <Markdown text={assistantMessage.content} status={assistantMessage.status} />
              </div>
            )}
          </div>

          {conversation.error && (
            <div className="persona-error" role="alert">{conversation.error}</div>
          )}

          {composerOpen && (
            <form className="persona-composer" onSubmit={submitText}>
              <button className="persona-composer-close" type="button" onClick={() => setComposerOpen(false)} aria-label="关闭文字输入"><X /></button>
              <input
                ref={inputRef}
                value={draft}
                onChange={(event) => setDraft(event.target.value)}
                maxLength={500}
                placeholder="向叙华提问"
                aria-label="向叙华提问"
              />
              <button className="persona-send" type="submit" disabled={!draft.trim() || connecting} aria-label="发送问题"><ArrowUp /></button>
            </form>
          )}

          <button
            className={`persona-action persona-text-action ${composerOpen ? "is-active" : ""}`}
            type="button"
            onClick={() => setComposerOpen((open) => !open)}
            aria-label={composerOpen ? "收起文字输入" : "打开文字输入"}
            aria-expanded={composerOpen}
          ><ChatText /></button>
          <button
            className={`persona-action persona-voice-action ${voiceActive ? "is-active" : ""}`}
            type="button"
            onClick={handleVoice}
            disabled={connecting}
            aria-label={realtime.isConnected
              ? (voiceActive ? "关闭麦克风" : "开启麦克风")
              : "开启语音对话"}
            aria-pressed={realtime.isConnected ? voiceActive : undefined}
          >{connecting ? <SpinnerGap className="spin" /> : realtime.isConnected && !voiceActive
            ? <MicrophoneSlash /> : <Microphone />}</button>
          <p className="sr-only" role="status" aria-live="polite">{conversation.announcement}</p>
        </section>
      </div>
    </main>
  );
}

export default PersonaDisplayPage;
