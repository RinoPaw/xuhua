import { useCallback, useEffect, useMemo, useReducer, useRef, useState } from "react";
import { ArrowUp, Stop, X } from "@phosphor-icons/react";

import DigitalHuman from "./components/DigitalHuman.jsx";
import { ConversationMessage, PromptChips } from "./components/ConversationMessage.jsx";
import { ItemDetail, SourceItem } from "./components/HeritageBrowser.jsx";
import {
  friendlyVoiceError,
  VoiceControl,
  VoiceSpectrum,
  VoiceStatusRow,
} from "./components/VoiceControls.jsx";
import { useHeritageBrowser } from "./hooks/useHeritageBrowser.js";
import { useTextConversation } from "./hooks/useTextConversation.js";
import { REALTIME_VOICE_STATUS, useVoiceConversation } from "./hooks/useVoiceConversation.js";
import { apiEndpoint } from "./lib/apiEndpoint.js";
import { createConversationSessionId } from "./lib/conversationSession.js";
import {
  conversationReducer,
  getSessionSeed,
  initialConversationState,
} from "./lib/conversationState.js";
import { composerAction, effectiveVoiceStatus } from "./lib/conversationUiState.js";
import { getLocaleHint, getPreferredLocales } from "./lib/locale.js";

const API_BASE = import.meta.env.VITE_API_BASE || "";
const LOCALE_HINT = getLocaleHint();
const PREFERRED_LOCALES = getPreferredLocales();

function App() {
  const [pageSessionId] = useState(createConversationSessionId);
  const [state, dispatch] = useReducer(
    conversationReducer,
    { ...initialConversationState, sessionId: pageSessionId },
  );
  const [questionDraft, setQuestionDraft] = useState("");
  const [leftOpen, setLeftOpen] = useState(false);
  const [rightOpen, setRightOpen] = useState(false);
  const [promptSeed] = useState(() => getSessionSeed());

  const chatEnd = useRef(null);
  const realtimeRef = useRef(null);

  const {
    searchDraft,
    filters,
    items,
    total,
    hasMoreItems,
    categories,
    meta,
    loading,
    searchError,
    selected,
    detailLoading,
    detailError,
    sourceListRef,
    openItem: openBrowserItem,
    closeItem,
    applyFilters,
    updateSearchDraft,
    submitSearch,
    retryItems,
    handleSourceScroll,
  } = useHeritageBrowser({ apiBase: API_BASE, promptSeed });

  const openItem = useCallback((item) => {
    if (!item?.id) return;
    setRightOpen(true);
    void openBrowserItem(item);
  }, [openBrowserItem]);

  const { ask: askText, interrupt: interruptText } = useTextConversation({
    apiBase: API_BASE,
    sessionId: pageSessionId,
    category: filters.category,
    localeHint: LOCALE_HINT,
    onSubmit: (text) => dispatch({ type: "ask", text }),
    onEvent: (event) => dispatch({ type: "event", event }),
    onSpeechDelta: (text, locale) => {
      realtimeRef.current?.appendSpeechDelta?.(text, locale);
    },
    onSpeechDone: (text, locale) => {
      realtimeRef.current?.finishSpeechStream?.(text, locale);
    },
    onSpeechStop: () => {
      realtimeRef.current?.stopSpeaking?.();
    },
    onError: () => {
      dispatch({ type: "error", message: "回答服务暂时不可用" });
    },
  });

  const cancelQuestion = useCallback(() => {
    interruptText();
    dispatch({ type: "cancel" });
  }, [interruptText]);

  const recognitionContext = useMemo(() => ({
    category: filters.category,
    visibleItems: items
      .filter((item) => !filters.category || item.category === filters.category)
      .slice(0, 8),
    selectedItem: selected,
    sessionId: pageSessionId,
    localeHint: LOCALE_HINT,
    preferredLocales: PREFERRED_LOCALES,
  }), [filters.category, items, pageSessionId, selected]);

  const realtime = useVoiceConversation({
    websocketPath: apiEndpoint(API_BASE, "/api/voice"),
    recognitionContext,
    onUserPartial: (text, event) => dispatch({
      type: "realtime.user.partial",
      text,
      utteranceId: event?.utterance_id,
      revision: event?.revision,
    }),
    onUserTranscript: (text, event) => dispatch({
      type: "realtime.user",
      text,
      utteranceId: event?.utterance_id,
      revision: event?.revision,
    }),
    onAssistantTranscript: (text, event) => dispatch({
      type: event?.done ? "realtime.answer.done" : "realtime.answer.delta",
      text,
    }),
    onBargeIn: () => {
      dispatch({ type: "realtime.interrupted" });
      interruptText();
    },
    onSources: (sources) => dispatch({ type: "realtime.sources", sources }),
    onError: (error) => dispatch({
      type: "error",
      message: friendlyVoiceError(error, Boolean(meta?.capabilities?.realtime_voice)),
    }),
  });

  useEffect(() => {
    realtimeRef.current = realtime;
  }, [realtime]);

  useEffect(() => {
    if (state.messages.at(-1)) {
      chatEnd.current?.scrollIntoView({ behavior: "auto", block: "end" });
    }
  }, [state.messages]);

  const available = Boolean(meta?.capabilities?.realtime_voice);
  const connected = Boolean(realtime.isConnected);
  const microphoneEnabled = Boolean(realtime.isMicrophoneEnabled);
  const voiceStatus = effectiveVoiceStatus(
    connected,
    realtime.status,
    REALTIME_VOICE_STATUS.IDLE,
  );
  const levels = Array.isArray(meta?.levels) ? meta.levels : [];
  const showLevelFilter = levels.length > 1;
  const personaMode = realtime.isPlaying ? "speaking" : "idle";
  const welcomePrompts = useMemo(() => {
    const visibleItems = items.filter((item) => item?.title);
    const category = categories.length ? categories[promptSeed % categories.length] : null;
    const item = visibleItems.length ? visibleItems[(promptSeed * 7) % visibleItems.length] : null;
    return [
      category ? `有哪些${category.name}项目值得了解？` : "按类别浏览国家级非遗项目",
      item ? `${item.title}有什么特点？` : "查找一个非遗项目",
    ];
  }, [categories, items, promptSeed]);

  const startVoice = async () => {
    if (!available) {
      dispatch({ type: "error", message: friendlyVoiceError(null, false) });
      return;
    }
    const interruptedTextTurn = ["retrieving", "composing", "streaming"].includes(state.phase);
    interruptText();
    if (interruptedTextTurn) dispatch({ type: "cancel" });
    dispatch({ type: "clear.error" });
    await realtime.start();
  };

  const toggleVoiceMicrophone = () => {
    void realtime.toggleMicrophone();
    dispatch({ type: "clear.error" });
  };

  const stopVoice = () => {
    realtime.stop();
    interruptText({ stopSpeech: false });
    dispatch({ type: "realtime.interrupted" });
    dispatch({ type: "clear.error" });
  };

  const submitQuestion = (raw) => {
    const text = String(raw || "").trim();
    if (!text || voiceStatus === REALTIME_VOICE_STATUS.CONNECTING) return false;
    if (connected) {
      interruptText();
      if (!realtime.sendText(text)) return false;
      dispatch({ type: "realtime.user", text });
      return true;
    }
    void askText(text);
    return true;
  };

  const submit = (event) => {
    event.preventDefault();
    const form = event.currentTarget;
    const text = String(form.elements.question.value || "").trim();
    if (!submitQuestion(text)) return;
    setQuestionDraft("");
  };

  const answerInProgress = ["retrieving", "composing", "streaming"].includes(state.phase);
  const speechInProgress = Boolean(realtime.isSpeechPending || realtime.isPlaying);
  const composerMode = composerAction({
    connected,
    draft: questionDraft,
    answerInProgress,
    speechInProgress,
  });
  const stopComposer = () => {
    if (composerMode === "stop") cancelQuestion();
  };

  const waitingForFirstToken = !connected
    && ["retrieving", "composing"].includes(state.phase)
    && state.messages.at(-1)?.role === "user";
  const latestMessage = state.messages.at(-1);
  const hasUserPartial = latestMessage?.role === "user"
    && latestMessage.status === "transcribing"
    && Boolean(String(latestMessage.content || "").trim());
  const hasAssistantBubble = latestMessage?.role === "assistant"
    && Boolean(String(latestMessage.content || "").trim());
  const showConversationEmpty = state.messages.length === 0
    && voiceStatus === REALTIME_VOICE_STATUS.IDLE
    && !state.error;
  const showVoiceStatusOnly = state.messages.length === 0 && !showConversationEmpty;

  return (
    <main className={`app-shell voice-${voiceStatus}`}>
      <div className="mobile-toggle-row">
        <button
          type="button"
          aria-expanded={leftOpen}
          onClick={() => setLeftOpen((value) => !value)}
        >叙华</button>
        <button
          type="button"
          aria-expanded={rightOpen}
          onClick={() => setRightOpen((value) => !value)}
        >项目库</button>
      </div>

      <div className="workspace">
        <aside className={`left-panel ${leftOpen ? "is-open" : ""}`}>
          <button
            className="panel-dismiss"
            type="button"
            onClick={() => setLeftOpen(false)}
            aria-label="关闭叙华人物面板"
          ><X /></button>
          <DigitalHuman mode={personaMode} />
        </aside>

        <section className="center-panel">
          <div className="conversation-toolbar">
            <span className="conversation-title">与叙华对话</span>
          </div>

          <div className="chat-timeline">
            <div className={`message-stack ${showConversationEmpty ? "is-empty" : ""} ${showVoiceStatusOnly ? "is-status-only" : ""}`}>
              {showConversationEmpty && (
                <section className="conversation-empty" aria-label="开始对话">
                  <h1>想从哪项非遗开始？</h1>
                  <PromptChips
                    prompts={welcomePrompts}
                    rotationSeed={promptSeed}
                    onAsk={submitQuestion}
                    className="starter-row"
                  />
                </section>
              )}
              {state.messages.map((message) => (
                <ConversationMessage
                  key={message.id}
                  message={message}
                  onOpen={openItem}
                  onAsk={submitQuestion}
                  rotationSeed={promptSeed + Number(String(message.id).replace(/\D/g, ""))}
                />
              ))}
              {waitingForFirstToken && (
                <article className="message-row assistant thinking-row" aria-live="polite">
                  <span className="chat-avatar">叙</span>
                  <div className="message-content">
                    <span className="message-author">叙华</span>
                    <div className="thinking-status">
                      <span>{state.phase === "retrieving" ? "查找资料中" : "生成回答中"}</span>
                      <i /><i /><i />
                    </div>
                  </div>
                </article>
              )}
              <VoiceStatusRow
                status={voiceStatus}
                connected={connected}
                hasUserPartial={hasUserPartial}
                hasAssistantBubble={hasAssistantBubble}
              />
              {state.error && voiceStatus !== REALTIME_VOICE_STATUS.ERROR && (
                <div className="error-banner" role="alert">{state.error}</div>
              )}
              <div ref={chatEnd} />
            </div>
          </div>

          <p className="sr-only" role="status" aria-live="polite">{state.announcement}</p>
          <div className="composer-card">
            <div className="composer-row">
              <form onSubmit={submit} className="composer-form">
                {connected ? (
                  <VoiceSpectrum values={microphoneEnabled ? realtime.spectrum : Array(24).fill(0)} />
                ) : (
                  <textarea
                    name="question"
                    rows="1"
                    maxLength="500"
                    value={questionDraft}
                    onChange={(event) => setQuestionDraft(event.target.value)}
                    placeholder="向叙华提问"
                    aria-label="输入问题"
                  />
                )}
                {!connected && (
                  <button
                    className={`send-button ${composerMode === "stop" ? "is-stop" : ""}`}
                    type={composerMode === "stop" ? "button" : "submit"}
                    onClick={composerMode === "stop" ? stopComposer : undefined}
                    aria-label={composerMode === "stop" ? "停止" : "发送"}
                  >
                    {composerMode === "stop" ? <Stop /> : <ArrowUp />}
                  </button>
                )}
              </form>
              <VoiceControl
                available={available}
                connected={connected}
                microphoneEnabled={microphoneEnabled}
                status={voiceStatus}
                onStart={startVoice}
                onToggleMicrophone={toggleVoiceMicrophone}
                onEnd={stopVoice}
              />
            </div>
          </div>
        </section>

        <aside className={`right-panel ${rightOpen ? "is-open" : ""}`}>
          <button
            className="panel-dismiss"
            type="button"
            onClick={() => setRightOpen(false)}
            aria-label="关闭项目库"
          ><X /></button>
          {selected ? (
            <ItemDetail
              item={selected}
              loading={detailLoading}
              error={detailError}
              onBack={closeItem}
            />
          ) : (
            <>
              <div className="right-tools">
                <div className="right-heading">
                  <h2>非遗项目</h2>
                  <span>{levels.length === 1 ? `${levels[0]}名录` : "资料库"}</span>
                </div>
                <form
                  className="search-form"
                  onSubmit={(event) => {
                    event.preventDefault();
                    submitSearch();
                  }}
                >
                  <input
                    value={searchDraft}
                    onChange={(event) => updateSearchDraft(event.target.value)}
                    placeholder="搜索项目、地区或关键词"
                    aria-label="搜索非遗项目"
                  />
                  <button type="submit">搜索</button>
                </form>
                <div className={`filter-row ${showLevelFilter ? "" : "single-filter"}`}>
                  {showLevelFilter && (
                    <label className="filter-select">
                      <span className="sr-only">非遗级别</span>
                      <select
                        value={filters.level}
                        onChange={(event) => applyFilters({ ...filters, level: event.target.value })}
                      >
                        <option value="">全部级别</option>
                        {levels.map((level) => <option key={level} value={level}>{level}</option>)}
                      </select>
                    </label>
                  )}
                  <label className="filter-select">
                    <span className="sr-only">非遗类别</span>
                    <select
                      value={filters.category}
                      onChange={(event) => applyFilters({ ...filters, category: event.target.value })}
                    >
                      <option value="">全部类别</option>
                      {categories.map((category) => (
                        <option key={category.id || category.name} value={category.name}>
                          {category.name}
                        </option>
                      ))}
                    </select>
                  </label>
                </div>
                <div className="result-head">
                  <span>{loading && items.length === 0 ? "检索中" : `共 ${total} 项`}</span>
                  <span>{loading && items.length === 0 ? "载入中" : `已载入 ${items.length}`}</span>
                </div>
              </div>
              <div className="source-list-frame">
                <div
                  ref={sourceListRef}
                  className="source-list"
                  aria-busy={loading}
                  onScroll={handleSourceScroll}
                >
                  {items.map((item) => (
                    <SourceItem key={item.id} item={item} onOpen={openItem} />
                  ))}
                  {!loading && !searchError && items.length === 0 && (
                    <div className="empty-state">没有匹配项目</div>
                  )}
                  {loading && items.length > 0 && (
                    <div className="source-list-status" aria-live="polite">继续加载中</div>
                  )}
                  {!loading && searchError && (
                    <button
                      type="button"
                      className="source-list-retry"
                      onClick={retryItems}
                    >
                      加载失败，点击重试
                    </button>
                  )}
                  {!loading && !searchError && !hasMoreItems && items.length > 0 && (
                    <div className="source-list-status">已显示全部 {total} 项</div>
                  )}
                </div>
              </div>
            </>
          )}
        </aside>
      </div>
    </main>
  );
}

export { App };
