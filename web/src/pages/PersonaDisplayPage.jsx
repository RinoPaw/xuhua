import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { ArrowUp, ChatText, Microphone, MicrophoneSlash, SpinnerGap, X } from "@phosphor-icons/react";

import DigitalHuman from "../components/DigitalHuman.jsx";
import { Markdown } from "../components/ConversationMessage.jsx";
import { friendlyVoiceError } from "../components/VoiceControls.jsx";
import { useTextConversation } from "../hooks/useTextConversation.js";
import { REALTIME_VOICE_STATUS, useVoiceConversation } from "../hooks/useVoiceConversation.js";
import { createConversationSessionId } from "../lib/conversationSession.js";
import { conversationReducer, initialConversationState } from "../lib/conversationState.js";
import { personaDisplayState, personaVoiceControlState } from "../lib/displayMode.js";
import { getLocaleHint, getPreferredLocales } from "../lib/locale.js";
import { PersonaBrowserVoiceSession } from "../lib/personaBrowserVoiceSession.js";
import { activateWakeDevice, activationErrorMessage, consumeWakeActivationLink } from "../lib/wakeActivation.js";
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
  const [voiceAvailable, setVoiceAvailable] = useState(null);
  const [cloudWake, setCloudWake] = useState(false);
  const [wakeAuthorized, setWakeAuthorized] = useState(false);
  const [activationOpen, setActivationOpen] = useState(false);
  const [activationInput, setActivationInput] = useState("");
  const [activationBusy, setActivationBusy] = useState(false);
  const [activationError, setActivationError] = useState("");
  const activationRequestRef = useRef(null);
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
    const controller = new AbortController();
    void fetch("/api/meta", { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("voice_metadata_unavailable");
        return response.json();
      })
      .then(async (meta) => {
        if (controller.signal.aborted) return;
        const available = meta?.capabilities?.realtime_voice === true;
        if (meta?.capabilities?.wake_provider === "xfyun") {
          personaSessionRef.current?.configureWake("xfyun");
          const response = await fetch("/api/wake/status", { signal: controller.signal, credentials: "same-origin", cache: "no-store" });
          if (!response.ok) throw new Error("wake_status_unavailable");
          const state = await response.json();
          if (controller.signal.aborted) return;
          setWakeAuthorized(state.authorized === true);
          setCloudWake(true);
        } else if (available) void personaSessionRef.current?.armWake();
        setVoiceAvailable(available);
      })
      .catch((error) => {
        if (!controller.signal.aborted) {
          setVoiceAvailable(false);
          console.warn("[叙华][persona] voice capability unavailable", error);
        }
      });
    return () => {
      controller.abort();
      personaSessionRef.current?.stop();
    };
  }, []);

  const activateDevice = useCallback(async (value) => {
    activationRequestRef.current?.abort();
    const controller = new AbortController();
    activationRequestRef.current = controller;
    setActivationBusy(true);
    setActivationError("");
    try {
      await activateWakeDevice(value, { signal: controller.signal });
      if (controller.signal.aborted) return false;
      setWakeAuthorized(true);
      setActivationOpen(false);
      setActivationInput("");
      dispatch({ type: "clear.error" });
      return true;
    } catch (error) {
      if (!controller.signal.aborted) {
        setActivationOpen(true);
        setActivationInput(value);
        setActivationError(activationErrorMessage(error));
      }
      return false;
    } finally {
      if (activationRequestRef.current === controller && !controller.signal.aborted) setActivationBusy(false);
    }
  }, []);

  useEffect(() => {
    if (!cloudWake) return;
    const consume = () => { void consumeWakeActivationLink({
      location: globalThis.location, history: globalThis.history, activate: activateDevice,
    }); };
    globalThis.addEventListener("hashchange", consume);
    consume();
    return () => globalThis.removeEventListener("hashchange", consume);
  }, [cloudWake, activateDevice]);

  useEffect(() => () => activationRequestRef.current?.abort(), []);

  useEffect(() => {
    if (composerOpen) inputRef.current?.focus();
  }, [composerOpen]);

  const mode = realtime.isPlaying ? "speaking" : previewMode;
  const dialogueTurns = useMemo(() => {
    const turns = [];
    for (const message of conversation.messages) {
      if (message.role !== "user" && message.role !== "assistant") continue;
      if (message.role === "user" || turns.length === 0) {
        turns.push({ id: message.id, user: null, assistant: null });
      }
      turns.at(-1)[message.role] = message;
    }
    return turns.slice(-2);
  }, [conversation.messages]);
  const connecting = realtime.status === REALTIME_VOICE_STATUS.CONNECTING;
  const voiceControl = personaVoiceControlState({
    connected: realtime.isConnected,
    microphoneEnabled: realtime.isMicrophoneEnabled,
    wakeListening: realtime.isWakeListening,
    wakeStarting: realtime.isWakeStarting,
    available: voiceAvailable !== false,
  });
  const voiceActive = voiceControl.active;
  const voiceHint = !cloudWake ? "" : activationBusy ? "正在启用语音…"
    : !wakeAuthorized ? "点击麦克风，首次启用语音"
    : realtime.isWakeListening ? "叫我叙华"
      : realtime.isWakeStarting ? "正在准备语音…"
        : connecting ? "我在，正在连接…"
          : realtime.isPlaying ? "正在回答"
            : realtime.status === REALTIME_VOICE_STATUS.THINKING ? "正在思考"
              : realtime.isConnected ? "我在听" : "点击开启语音";

  const handleVoice = () => {
    dispatch({ type: "clear.error" });
    if (voiceAvailable === false) return;
    if (cloudWake && !wakeAuthorized) {
      setActivationOpen(true);
      return;
    }
    if (realtime.isConnected) {
      void realtime.toggleMicrophone();
      return;
    }
    if (realtime.isWakeListening || realtime.isWakeStarting) {
      personaSessionRef.current?.stop();
      return;
    }
    // Manual activation while asleep must enable local wake detection,
    // never open remote ASR before the wake phrase.
    interruptText();
    if (["retrieving", "composing", "streaming"].includes(conversation.phase)) {
      dispatch({ type: "cancel" });
    }
    realtime.unlockOutput();
    void personaSessionRef.current?.armWake();
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
            {dialogueTurns.map((turn) => (
              <div className="persona-dialogue-turn" key={turn.id}>
                {turn.assistant && (
                  <div className="persona-bubble persona-bubble-assistant" aria-label="叙华的话">
                    <Markdown text={turn.assistant.content} status={turn.assistant.status} />
                  </div>
                )}
                {turn.user && (
                  <div className="persona-bubble persona-bubble-user" aria-label="用户的话">
                    <Markdown text={turn.user.content} status={turn.user.status} />
                  </div>
                )}
              </div>
            ))}
          </div>

          {conversation.error && (
            <div className="persona-error" role="alert">{conversation.error}</div>
          )}

          {activationOpen && !wakeAuthorized && (
            <form className="persona-activation" aria-label="首次启用语音" onSubmit={(event) => {
              event.preventDefault();
              void activateDevice(activationInput);
            }}>
              <div className="persona-activation-heading">
                <strong>首次启用语音</strong>
                <button type="button" aria-label="关闭语音激活" onClick={() => setActivationOpen(false)}><X /></button>
              </div>
              <p>粘贴激活码或完整链接，这个浏览器只需启用一次。</p>
              <label className="sr-only" htmlFor="wake-activation">语音激活码或完整链接</label>
              <input id="wake-activation" type="password" autoComplete="off" maxLength={2048}
                placeholder="激活码或完整链接" value={activationInput}
                onChange={(event) => setActivationInput(event.target.value)} disabled={activationBusy} />
              <button className="persona-activation-submit" type="submit" disabled={activationBusy || !activationInput.trim()}>
                {activationBusy ? "正在启用…" : "启用此浏览器"}
              </button>
              {activationError && <p className="persona-activation-error" role="alert">{activationError}</p>}
            </form>
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
            disabled={voiceAvailable === null || voiceAvailable === false || activationBusy}
            aria-label={cloudWake ? (voiceActive || realtime.isWakeStarting || connecting ? "关闭语音" : "开启唤醒监听") : voiceControl.label}
            aria-pressed={voiceActive}
          >{connecting || voiceControl.preparing ? <SpinnerGap className="spin" /> : realtime.isConnected && !voiceActive
            ? <MicrophoneSlash /> : <Microphone />}</button>
          {voiceHint && !conversation.error && !activationOpen && <p className="persona-wake-status" role="status" aria-live="polite">{voiceHint}</p>}
          <p className="sr-only" role="status" aria-live="polite">
            {realtime.isWakeListening ? "正在监听唤醒词叙华"
              : realtime.isWakeStarting ? "正在准备本地唤醒监听" : conversation.announcement}
          </p>
        </section>
      </div>
    </main>
  );
}

export default PersonaDisplayPage;
