export function getSessionSeed(cryptoLike = globalThis.crypto) {
  if (typeof cryptoLike?.getRandomValues === "function") {
    return cryptoLike.getRandomValues(new Uint32Array(1))[0];
  }
  return Math.floor(Math.random() * 0x1_0000_0000);
}

export function rotateAndLimit(values, seed, limit = 3) {
  const unique = [...new Set(
    (Array.isArray(values) ? values : [])
      .map((value) => String(value || "").trim())
      .filter(Boolean),
  )];
  if (unique.length <= 1) return unique.slice(0, limit);
  const offset = Math.abs(Number(seed) || 0) % unique.length;
  const rotated = [...unique.slice(offset), ...unique.slice(0, offset)];
  return rotated.slice(0, limit);
}

export const initialConversationState = {
  sessionId: null,
  turnId: null,
  phase: "idle",
  sources: [],
  error: "",
  announcement: "",
  sequence: 0,
  messages: [],
};

function updateLastAssistant(messages, patch) {
  const last = messages.at(-1);
  if (last?.role !== "assistant") return messages;
  return [...messages.slice(0, -1), { ...last, ...patch(last) }];
}

function upsertCurrentAssistant(messages, sequence, patch) {
  const last = messages.at(-1);
  if (last?.role === "assistant") return updateLastAssistant(messages, patch);
  const assistant = {
    id: `a-${sequence}`,
    role: "assistant",
    content: "",
    status: "streaming",
    sources: [],
    suggestions: [],
  };
  return [...messages, { ...assistant, ...patch(assistant) }];
}

function appendTurn(state, text, phase) {
  const sequence = state.sequence + 1;
  return {
    ...state,
    sequence,
    phase,
    sources: [],
    error: "",
    announcement: "",
    turnId: null,
    messages: [...state.messages, {
      id: `u-${sequence}`,
      role: "user",
      content: text,
      status: "complete",
    }],
  };
}

function discardRealtimeUserPartial(messages) {
  const last = messages.at(-1);
  return last?.role === "user" && last.status === "transcribing"
    ? messages.slice(0, -1)
    : messages;
}

function updateRealtimeUserPartial(state, text) {
  const content = String(text || "").trim();
  const last = state.messages.at(-1);
  if (!content) {
    if (last?.role !== "user" || last.status !== "transcribing") return state;
    return {
      ...state,
      phase: "realtime",
      error: "",
      messages: discardRealtimeUserPartial(state.messages),
    };
  }
  if (last?.role === "user" && last.status === "transcribing") {
    return {
      ...state,
      phase: "realtime",
      error: "",
      messages: [...state.messages.slice(0, -1), { ...last, content }],
    };
  }
  const sequence = state.sequence + 1;
  return {
    ...state,
    sequence,
    phase: "realtime",
    error: "",
    messages: [...state.messages, {
      id: `u-${sequence}`,
      role: "user",
      content,
      status: "transcribing",
    }],
  };
}

function completeRealtimeUser(state, text) {
  const content = String(text || "").trim();
  const last = state.messages.at(-1);
  if (!content) return state;
  if (last?.role !== "user" || last.status !== "transcribing") {
    return appendTurn(state, content, "realtime");
  }
  return {
    ...state,
    phase: "realtime",
    sources: [],
    error: "",
    messages: [...state.messages.slice(0, -1), { ...last, content, status: "complete" }],
  };
}

function normalizeSuggestions(values) {
  return Array.isArray(values)
    ? [...new Set(values.map((value) => String(value || "").trim()).filter(Boolean))]
    : [];
}

export function conversationReducer(state, action) {
  if (action.type === "ask") return appendTurn(state, action.text, "retrieving");
  if (action.type === "realtime.user.partial") return updateRealtimeUserPartial(state, action.text);
  if (action.type === "realtime.user") return completeRealtimeUser(state, action.text);

  if (action.type === "event") {
    const { event } = action;
    const payload = event.payload || {};
    const next = {
      ...state,
      sessionId: event.session_id || state.sessionId,
      turnId: event.turn_id || state.turnId,
    };

    if (event.type === "retrieval.started") return { ...next, phase: "retrieving" };
    if (event.type === "retrieval.completed") return { ...next, phase: "composing" };

    if (event.type === "response.text.delta") {
      next.phase = "streaming";
      next.messages = upsertCurrentAssistant(state.messages, state.sequence, (message) => ({
        content: `${message.content}${payload.delta || ""}`,
        status: "streaming",
        sources: message.sources?.length ? message.sources : state.sources,
      }));
    }

    if (event.type === "response.sources") {
      const sources = Array.isArray(payload.sources) ? payload.sources : [];
      next.sources = sources;
      next.messages = updateLastAssistant(next.messages, () => ({ sources }));
    }

    if (event.type === "turn.completed") {
      const answer = String(payload.answer || "");
      const suggestions = normalizeSuggestions(payload.suggested_questions);
      return {
        ...next,
        phase: "complete",
        announcement: answer,
        messages: upsertCurrentAssistant(next.messages, state.sequence, (message) => ({
          content: answer || message.content,
          status: "complete",
          suggestions,
          sources: message.sources?.length ? message.sources : next.sources,
        })),
      };
    }

    if (event.type === "turn.failed") {
      return {
        ...next,
        phase: "error",
        error: payload.code === "question_too_long"
          ? `问题过长（最多 ${payload.max_chars} 字）`
          : "暂时无法回答",
        messages: updateLastAssistant(next.messages, () => ({ status: "error" })),
      };
    }

    if (event.type === "turn.cancelled") {
      return {
        ...next,
        phase: "cancelled",
        messages: updateLastAssistant(next.messages, () => ({ status: "cancelled" })),
      };
    }

    return next;
  }

  if (action.type === "realtime.answer.delta") {
    return {
      ...state,
      phase: "realtime",
      messages: upsertCurrentAssistant(state.messages, state.sequence, (message) => ({
        content: `${message.content}${action.text}`,
        status: "realtime",
        sources: message.sources?.length ? message.sources : state.sources,
      })),
    };
  }

  if (action.type === "realtime.answer.done") {
    const answer = String(action.text || "");
    const last = state.messages.at(-1);
    const previous = last?.role === "assistant" ? last.content || "" : "";
    const completed = answer || previous;
    return {
      ...state,
      phase: "complete",
      announcement: answer,
      messages: upsertCurrentAssistant(state.messages, state.sequence, (message) => ({
        content: completed || message.content,
        status: "complete",
        sources: message.sources?.length ? message.sources : state.sources,
      })),
    };
  }

  if (action.type === "realtime.sources") {
    const sources = Array.isArray(action.sources) ? action.sources : [];
    return {
      ...state,
      sources,
      messages: updateLastAssistant(state.messages, () => ({ sources })),
    };
  }

  if (action.type === "realtime.interrupted") {
    return { ...state, phase: "realtime", error: "" };
  }
  if (action.type === "error") {
    return {
      ...state,
      phase: "error",
      error: action.message || "连接暂时不可用",
      messages: discardRealtimeUserPartial(state.messages),
    };
  }
  if (action.type === "clear.error") {
    return {
      ...state,
      error: "",
      phase: state.phase === "error" ? "idle" : state.phase,
    };
  }
  if (action.type === "cancel") {
    return {
      ...state,
      phase: "cancelled",
      error: "",
      messages: updateLastAssistant(state.messages, () => ({ status: "cancelled" })),
    };
  }

  return state;
}
