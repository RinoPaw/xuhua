import { apiEndpoint, normalizeApiBase } from "./apiEndpoint.js";
import {
  cancelTurnBestEffort,
  isTerminalTurnEvent,
  nextActiveTurnId,
} from "./chatLifecycle.js";

function noop() {}

export function decodeSseBlock(block) {
  let eventName = "message";
  const dataLines = [];
  for (const line of String(block || "").split(/\r?\n/)) {
    if (line.startsWith("event:")) eventName = line.slice(6).trim();
    if (line.startsWith("data:")) dataLines.push(line.slice(5).trimStart());
  }
  if (!dataLines.length) return null;
  try {
    const event = JSON.parse(dataLines.join("\n"));
    if (!event || typeof event !== "object" || Array.isArray(event)) return null;
    return { ...event, type: event.type || eventName };
  } catch {
    return null;
  }
}

export class SseEventDecoder {
  constructor() {
    this.buffer = "";
  }

  push(chunk, { final = false } = {}) {
    this.buffer += String(chunk || "");
    const blocks = this.buffer.split(/\r?\n\r?\n/);
    this.buffer = blocks.pop() || "";
    if (final && this.buffer.trim()) {
      blocks.push(this.buffer);
      this.buffer = "";
    }
    return blocks.map(decodeSseBlock).filter(Boolean);
  }
}

/**
 * Browser-side owner for one foreground text conversation stream.
 *
 * UI state and speech output stay external. This object owns only request
 * generation, AbortController, SSE decoding and the server turn identity.
 */
export class TextConversationSession {
  constructor({
    apiBase = "",
    fetchFn = globalThis.fetch,
    getContext = () => ({}),
    onSubmit = noop,
    onEvent = noop,
    onSpeechDelta = noop,
    onSpeechDone = noop,
    onSpeechStop = noop,
    onError = noop,
    log = console,
  } = {}) {
    this.apiBase = normalizeApiBase(apiBase);
    this.fetchFn = fetchFn;
    this.getContext = getContext;
    this.onSubmit = onSubmit;
    this.onEvent = onEvent;
    this.onSpeechDelta = onSpeechDelta;
    this.onSpeechDone = onSpeechDone;
    this.onSpeechStop = onSpeechStop;
    this.onError = onError;
    this.log = log;
    this.generation = 0;
    this.controller = null;
    this.activeTurnId = null;
  }

  setApiBase(value) {
    this.apiBase = normalizeApiBase(value);
  }

  url(path) {
    return apiEndpoint(this.apiBase, path);
  }

  isCurrent(generation) {
    return this.generation === generation;
  }

  cancelActive() {
    this.controller?.abort();
    this.controller = null;
    const turnId = this.activeTurnId;
    this.activeTurnId = null;
    const sessionId = String(this.getContext()?.sessionId || "").trim();
    if (sessionId && turnId) {
      cancelTurnBestEffort({
        fetchFn: this.fetchFn,
        url: this.url(
          `/api/chat/${encodeURIComponent(sessionId)}/turn/${encodeURIComponent(turnId)}/cancel`,
        ),
      });
    }
    return Boolean(turnId);
  }

  supersede({ stopSpeech = true } = {}) {
    this.generation += 1;
    if (stopSpeech) this.onSpeechStop();
    this.cancelActive();
    return this.generation;
  }

  handleEvent(event, generation, traceState) {
    if (!this.isCurrent(generation) || !event) return false;
    const type = String(event.type || "");
    if (isTerminalTurnEvent(type)) traceState.terminalReceived = true;
    this.onEvent(event);

    if (type === "response.text.delta") {
      if (!traceState.firstTextLogged) {
        traceState.firstTextLogged = true;
        this.log.info?.(`[叙华][trace=${generation}] llm.first_text_delta`);
      }
      this.onSpeechDelta(
        event.payload?.delta || "",
        event.payload?.locale || this.getContext()?.localeHint || "",
      );
    } else if (type === "turn.completed") {
      this.log.info?.(`[叙华][trace=${generation}] text.complete`);
      this.onSpeechDone(
        event.payload?.answer || "",
        event.payload?.locale || this.getContext()?.localeHint || "",
      );
    } else if (type === "turn.failed" || type === "turn.cancelled") {
      this.onSpeechStop();
    }

    this.activeTurnId = nextActiveTurnId(this.activeTurnId, {
      type,
      turn_id: event.turn_id,
    });
    return true;
  }

  async ask(raw) {
    const text = String(raw || "").trim();
    if (!text || typeof this.fetchFn !== "function") return false;

    const generation = this.supersede();
    const controller = new AbortController();
    this.controller = controller;
    const context = this.getContext() || {};
    this.onSubmit(text);
    this.log.info?.(`[叙华][trace=${generation}] llm.request.client.start`);

    const decoder = new TextDecoder();
    const sse = new SseEventDecoder();
    const traceState = { firstTextLogged: false, terminalReceived: false };

    try {
      const response = await this.fetchFn(this.url("/api/chat"), {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
        body: JSON.stringify({
          question: text,
          session_id: String(context.sessionId || "").trim() || null,
          category: String(context.category || "").trim(),
          locale_hint: String(context.localeHint || "").trim(),
        }),
        signal: controller.signal,
      });
      if (!response?.ok || !response.body?.getReader) throw new Error("request_failed");

      const reader = response.body.getReader();
      while (true) {
        const { value, done } = await reader.read();
        const chunk = decoder.decode(value || new Uint8Array(), { stream: !done });
        for (const event of sse.push(chunk, { final: done })) {
          this.handleEvent(event, generation, traceState);
        }
        if (done) break;
        if (!this.isCurrent(generation)) {
          try { await reader.cancel?.(); } catch { /* best effort */ }
          return false;
        }
      }
      if (this.isCurrent(generation) && !traceState.terminalReceived) {
        throw new Error("stream_ended_before_terminal");
      }
      return this.isCurrent(generation);
    } catch (error) {
      if (error?.name !== "AbortError" && this.isCurrent(generation)) {
        this.onSpeechStop();
        this.onError(error);
      }
      return false;
    } finally {
      if (this.controller === controller) this.controller = null;
    }
  }

  destroy() {
    this.supersede({ stopSpeech: false });
  }
}

export default TextConversationSession;
