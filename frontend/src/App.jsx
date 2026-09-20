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
import { REALTIME_VOICE_STATUS, useVoiceConversation } from "./hooks/useVoiceConversation.js";
import {
  cancelTurnBestEffort,
  isTerminalTurnEvent,
  nextActiveTurnId,
} from "./lib/chatLifecycle.js";
import { createConversationSessionId } from "./lib/conversationSession.js";
import {
  conversationReducer,
  getSessionSeed,
  initialConversationState,
} from "./lib/conversationState.js";
import { composerAction, effectiveVoiceStatus } from "./lib/conversationUiState.js";
import { getLocaleHint, getPreferredLocales } from "./lib/locale.js";
import {
  mergePageItems,
  nextPageState,
  pageLimitForState,
  PROJECT_PAGE_SIZE,
} from "./lib/pagination.js";

const API_BASE = import.meta.env.VITE_API_BASE || "";
const LOCALE_HINT = getLocaleHint();
const PREFERRED_LOCALES = getPreferredLocales();
const apiUrl = (path) => `${API_BASE}${path}`;

function App() {
  const [pageSessionId] = useState(createConversationSessionId);
  const [state, dispatch] = useReducer(
    conversationReducer,
    { ...initialConversationState, sessionId: pageSessionId },
  );
  const [searchDraft, setSearchDraft] = useState("");
  const [questionDraft, setQuestionDraft] = useState("");
  const [searchQuery, setSearchQuery] = useState("");
  const [filters, setFilters] = useState({ category: "", level: "" });
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [hasMoreItems, setHasMoreItems] = useState(false);
  const [categories, setCategories] = useState([]);
  const [meta, setMeta] = useState(null);
  const [loading, setLoading] = useState(true);
  const [searchError, setSearchError] = useState("");
  const [leftOpen, setLeftOpen] = useState(false);
  const [rightOpen, setRightOpen] = useState(false);
  const [selected, setSelected] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [promptSeed] = useState(() => getSessionSeed());

  const abortRef = useRef(null);
  const turnRef = useRef(null);
  const requestRef = useRef(0);
  const searchAbort = useRef(null);
  const searchSeq = useRef(0);
  const detailAbort = useRef(null);
  const sourceListRef = useRef(null);
  const itemPageRef = useRef({
    key: "",
    nextOffset: 0,
    startOffset: 0,
    wrapped: false,
    hasMore: true,
    loading: false,
    requestId: 0,
  });
  const chatEnd = useRef(null);
  const sessionRef = useRef(pageSessionId);
  const realtimeRef = useRef(null);

  const cancelActive = useCallback(async () => {
    abortRef.current?.abort();
    const sessionId = sessionRef.current;
    const turnId = turnRef.current;
    turnRef.current = null;
    if (sessionId && turnId) {
      cancelTurnBestEffort({
        fetchFn: fetch,
        url: apiUrl(
          `/api/chat/${encodeURIComponent(sessionId)}/turn/${encodeURIComponent(turnId)}/cancel`,
        ),
      });
    }
  }, []);

  const prepareSubmission = useCallback(() => {
    requestRef.current += 1;
    realtimeRef.current?.stopSpeaking?.();
    return cancelActive();
  }, [cancelActive]);

  const cancelQuestion = useCallback(async () => {
    await prepareSubmission();
    dispatch({ type: "cancel" });
  }, [prepareSubmission]);

  const ask = useCallback(async (raw) => {
    const text = String(raw || "").trim();
    if (!text) return;
    const cancelPromise = prepareSubmission();
    const requestId = requestRef.current;
    const isCurrent = () => requestRef.current === requestId;
    await cancelPromise;
    if (!isCurrent()) return;

    const controller = new AbortController();
    abortRef.current = controller;
    dispatch({ type: "ask", text });
    console.info(`[叙华][trace=${requestId}] llm.request.client.start`);
    let buffer = "";
    let eventName = "message";
    let dataLines = [];
    let firstTextLogged = false;
    let terminalReceived = false;

    const consume = (block) => {
      if (!isCurrent()) return;
      for (const line of block.split(/\r?\n/)) {
        if (line.startsWith("event:")) eventName = line.slice(6).trim();
        if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
      }
      if (dataLines.length) {
        try {
          const event = JSON.parse(dataLines.join("\n"));
          const type = event.type || eventName;
          if (isTerminalTurnEvent(type)) terminalReceived = true;
          dispatch({ type: "event", event: { ...event, type } });
          if (type === "response.text.delta") {
            if (!firstTextLogged) {
              firstTextLogged = true;
              console.info(`[叙华][trace=${requestId}] llm.first_text_delta`);
            }
            realtimeRef.current?.appendSpeechDelta?.(
              event.payload?.delta || "",
              event.payload?.locale || LOCALE_HINT,
            );
          }
          if (type === "turn.completed") {
            console.info(`[叙华][trace=${requestId}] text.complete`);
            realtimeRef.current?.finishSpeechStream?.(
              event.payload?.answer || "",
              event.payload?.locale || LOCALE_HINT,
            );
          }
          if (["turn.failed", "turn.cancelled"].includes(type)) {
            realtimeRef.current?.stopSpeaking?.();
          }
          turnRef.current = nextActiveTurnId(turnRef.current, {
            type,
            turn_id: event.turn_id,
          });
        } catch {
          // Ignore malformed heartbeat frames.
        }
      }
      eventName = "message";
      dataLines = [];
    };

    try {
      const response = await fetch(apiUrl("/api/chat"), {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          question: text,
          session_id: sessionRef.current,
          category: filters.category,
          locale_hint: LOCALE_HINT,
        }),
        signal: controller.signal,
      });
      if (!response.ok || !response.body) throw new Error("request_failed");
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      while (true) {
        const { value, done } = await reader.read();
        buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
        const blocks = buffer.split(/\r?\n\r?\n/);
        buffer = blocks.pop() || "";
        blocks.forEach(consume);
        if (done) {
          if (buffer.trim()) consume(buffer);
          break;
        }
      }
      if (isCurrent() && !terminalReceived) throw new Error("stream_ended_before_terminal");
    } catch (error) {
      if (error?.name !== "AbortError" && isCurrent()) {
        realtimeRef.current?.stopSpeaking?.();
        dispatch({ type: "error", message: "回答服务暂时不可用" });
      }
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  }, [filters.category, prepareSubmission]);

  const recognitionContext = useMemo(() => ({
    category: filters.category,
    visibleItems: items
      .filter((item) => !filters.category || item.category === filters.category)
      .slice(0, 8),
    selectedItem: selected,
    sessionId: sessionRef.current,
    localeHint: LOCALE_HINT,
    preferredLocales: PREFERRED_LOCALES,
  }), [filters.category, items, selected]);

  const realtime = useVoiceConversation({
    websocketPath: apiUrl("/api/voice"),
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
      void cancelActive();
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
    const controller = new AbortController();
    Promise.all([
      fetch(apiUrl("/api/meta"), { signal: controller.signal }),
      fetch(apiUrl("/api/categories"), { signal: controller.signal }),
    ]).then(async ([metaResponse, categoriesResponse]) => {
      if (metaResponse.ok) setMeta(await metaResponse.json());
      else setMeta({ levels: [], capabilities: { realtime_voice: false } });
      if (categoriesResponse.ok) setCategories(await categoriesResponse.json());
    }).catch((error) => {
      if (error?.name !== "AbortError") {
        setMeta({ levels: [], capabilities: { realtime_voice: false } });
      }
    });
    return () => controller.abort();
  }, []);

  const fetchItemPage = useCallback(async ({ reset = false } = {}) => {
    const initialBrowse = !searchQuery && !filters.category && !filters.level;
    if (initialBrowse && meta === null) return;
    const key = JSON.stringify([searchQuery, filters.category, filters.level]);
    const page = itemPageRef.current;
    if (!reset && (page.loading || (!page.hasMore && !page.error) || page.key !== key)) return;

    const requestId = reset ? ++searchSeq.current : page.requestId;
    if (reset) {
      searchAbort.current?.abort();
      const itemCount = Math.max(0, Number(meta?.item_count) || 0);
      const startOffset = initialBrowse && itemCount > PROJECT_PAGE_SIZE
        ? promptSeed % (itemCount - PROJECT_PAGE_SIZE + 1)
        : 0;
      itemPageRef.current = {
        key,
        nextOffset: startOffset,
        startOffset,
        wrapped: false,
        hasMore: true,
        error: false,
        loading: true,
        requestId,
      };
      setItems([]);
      setTotal(0);
      setHasMoreItems(true);
      setSearchError("");
    } else {
      itemPageRef.current = { ...page, error: false, loading: true };
    }

    const controller = new AbortController();
    searchAbort.current = controller;
    setLoading(true);
    const currentPage = itemPageRef.current;
    const offset = currentPage.nextOffset;
    const pageLimit = pageLimitForState(currentPage);
    const query = new URLSearchParams({
      q: searchQuery,
      category: filters.category,
      level: filters.level,
      limit: String(pageLimit),
      offset: String(offset),
    });

    try {
      const response = await fetch(apiUrl(`/api/items?${query}`), { signal: controller.signal });
      if (!response.ok) throw new Error("search_failed");
      const data = await response.json();
      const current = itemPageRef.current;
      if (requestId !== searchSeq.current || current.key !== key) return;
      const incoming = Array.isArray(data.items) ? data.items : [];
      const pageState = nextPageState({
        offset: Number(data.offset ?? offset),
        limit: Number(data.limit ?? PROJECT_PAGE_SIZE),
        total: Number(data.total || 0),
        received: incoming.length,
        startOffset: current.startOffset,
        wrapped: current.wrapped,
      });
      setItems((previous) => (
        reset ? mergePageItems([], incoming) : mergePageItems(previous, incoming)
      ));
      setTotal(Number(data.total || 0));
      setHasMoreItems(pageState.hasMore);
      itemPageRef.current = {
        ...current,
        nextOffset: pageState.nextOffset,
        wrapped: pageState.wrapped,
        hasMore: pageState.hasMore,
        error: false,
        loading: false,
      };
    } catch (error) {
      if (error?.name !== "AbortError"
        && requestId === searchSeq.current
        && itemPageRef.current.key === key) {
        setSearchError("加载失败");
        itemPageRef.current = { ...itemPageRef.current, loading: false, error: true };
        setHasMoreItems(false);
      }
    } finally {
      if (requestId === searchSeq.current && itemPageRef.current.key === key) {
        itemPageRef.current = { ...itemPageRef.current, loading: false };
        setLoading(false);
      }
    }
  }, [filters, meta, promptSeed, searchQuery]);

  const searchItems = useCallback(() => fetchItemPage({ reset: true }), [fetchItemPage]);
  const loadMoreItems = useCallback(() => fetchItemPage(), [fetchItemPage]);

  useEffect(() => { void searchItems(); }, [searchItems]);
  useEffect(() => {
    const list = sourceListRef.current;
    if (!list || loading || !hasMoreItems || items.length === 0) return;
    if (list.scrollHeight <= list.clientHeight + 8) void loadMoreItems();
  }, [hasMoreItems, items.length, loadMoreItems, loading]);
  useEffect(() => {
    chatEnd.current?.scrollIntoView({ behavior: "auto", block: "end" });
  }, [state.messages]);
  useEffect(() => () => {
    abortRef.current?.abort();
    searchAbort.current?.abort();
    detailAbort.current?.abort();
    realtime.stop();
  }, [realtime.stop]);

  const openItem = useCallback(async (item) => {
    if (!item?.id) return;
    setRightOpen(true);
    setSelected(item);
    setDetailLoading(true);
    setDetailError("");
    detailAbort.current?.abort();
    const controller = new AbortController();
    detailAbort.current = controller;
    try {
      const response = await fetch(
        apiUrl(`/api/items/${encodeURIComponent(item.id)}`),
        { signal: controller.signal },
      );
      if (!response.ok) throw new Error("detail_failed");
      setSelected(await response.json());
    } catch (error) {
      if (error?.name !== "AbortError") setDetailError("暂时无法读取项目详情");
    } finally {
      if (detailAbort.current === controller) setDetailLoading(false);
    }
  }, []);

  const available = Boolean(meta?.capabilities?.realtime_voice);
  const connected = Boolean(realtime.isConnected);
  const voiceStatus = effectiveVoiceStatus(
    connected,
    realtime.status,
    REALTIME_VOICE_STATUS.IDLE,
  );
  const levels = Array.isArray(meta?.levels) ? meta.levels : [];
  const showLevelFilter = levels.length > 1;
  const results = items;
  const shownTotal = total;
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
    await prepareSubmission();
    if (interruptedTextTurn) dispatch({ type: "cancel" });
    dispatch({ type: "clear.error" });
    await realtime.start();
  };

  const stopVoice = () => {
    requestRef.current += 1;
    realtime.stop();
    void cancelActive();
    dispatch({ type: "clear.error" });
  };

  const submitQuestion = (raw) => {
    const text = String(raw || "").trim();
    if (!text || voiceStatus === REALTIME_VOICE_STATUS.CONNECTING) return false;
    if (connected) {
      void prepareSubmission();
      if (!realtime.sendText(text)) return false;
      dispatch({ type: "realtime.user", text });
      return true;
    }
    void ask(text);
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
    if (composerMode === "stop") void cancelQuestion();
  };

  const handleSourceScroll = useCallback((event) => {
    const list = event.currentTarget;
    if (loading || !hasMoreItems) return;
    if (list.scrollHeight - list.scrollTop - list.clientHeight < 180) void loadMoreItems();
  }, [hasMoreItems, loadMoreItems, loading]);

  const applyFilters = (next) => {
    setSelected(null);
    setSearchQuery(searchDraft.trim());
    setFilters(next);
  };

  const updateSearchDraft = (value) => {
    setSearchDraft(value);
    if (!value.trim()) setSearchQuery("");
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
                error={state.error || friendlyVoiceError(realtime.error, available)}
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
                  <VoiceSpectrum values={realtime.spectrum} />
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
                status={voiceStatus}
                onStart={startVoice}
                onStop={stopVoice}
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
              onBack={() => {
                detailAbort.current?.abort();
                detailAbort.current = null;
                setDetailLoading(false);
                setDetailError("");
                setSelected(null);
              }}
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
                    setSearchQuery(searchDraft.trim());
                    if (searchQuery === searchDraft.trim()) void searchItems();
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
                  <span>{loading && results.length === 0 ? "检索中" : `共 ${shownTotal} 项`}</span>
                  <span>{loading && results.length === 0 ? "载入中" : `已载入 ${results.length}`}</span>
                </div>
              </div>
              <div className="source-list-frame">
                <div
                  ref={sourceListRef}
                  className="source-list"
                  aria-busy={loading}
                  onScroll={handleSourceScroll}
                >
                  {results.map((item) => (
                    <SourceItem key={item.id} item={item} onOpen={openItem} />
                  ))}
                  {!loading && !searchError && results.length === 0 && (
                    <div className="empty-state">没有匹配项目</div>
                  )}
                  {loading && results.length > 0 && (
                    <div className="source-list-status" aria-live="polite">继续加载中</div>
                  )}
                  {!loading && searchError && (
                    <button
                      type="button"
                      className="source-list-retry"
                      onClick={() => {
                        setSearchError("");
                        void loadMoreItems();
                      }}
                    >
                      加载失败，点击重试
                    </button>
                  )}
                  {!loading && !searchError && !hasMoreItems && results.length > 0 && (
                    <div className="source-list-status">已显示全部 {shownTotal} 项</div>
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
