import assert from "node:assert/strict";
import test from "node:test";

import {
  SseEventDecoder,
  TextConversationSession,
  decodeSseBlock,
} from "../src/lib/textConversationSession.js";

const encoder = new TextEncoder();

function responseFrom(chunks) {
  let index = 0;
  return {
    ok: true,
    body: {
      getReader() {
        return {
          async read() {
            if (index >= chunks.length) return { value: undefined, done: true };
            return { value: encoder.encode(chunks[index++]), done: false };
          },
          async cancel() {},
        };
      },
    },
  };
}

test("SSE decoder preserves chunk boundaries and event names", () => {
  const decoder = new SseEventDecoder();
  assert.deepEqual(decoder.push("event: response.text.delta\ndata: {\"payload\":{\"del"), []);
  assert.deepEqual(decoder.push("ta\":\"汴绣\"}}\n\n"), [
    { type: "response.text.delta", payload: { delta: "汴绣" } },
  ]);
  assert.deepEqual(
    decodeSseBlock("event: turn.completed\ndata: {\"type\":\"turn.completed\",\ndata: \"turn_id\":\"t1\"}"),
    { type: "turn.completed", turn_id: "t1" },
  );
});

test("text session owns request, SSE turn identity, and speech bridge", async () => {
  const calls = [];
  const events = [];
  const requests = [];
  const session = new TextConversationSession({
    apiBase: "/base",
    fetchFn: async (url, options) => {
      requests.push([url, options]);
      return responseFrom([
        'event: turn.started\ndata: {"type":"turn.started","session_id":"s1","turn_id":"t1","payload":{}}\n\n',
        'event: response.text.delta\ndata: {"type":"response.text.delta","session_id":"s1","turn_id":"t1","payload":{"delta":"你好","locale":"zh-CN"}}\n\n',
        'event: turn.completed\ndata: {"type":"turn.completed","session_id":"s1","turn_id":"t1","payload":{"answer":"你好呀","locale":"zh-CN"}}\n\n',
      ]);
    },
    getContext: () => ({ sessionId: "s1", category: "传统技艺", localeHint: "zh-CN" }),
    onSubmit: (text) => calls.push(["submit", text]),
    onEvent: (event) => events.push(event.type),
    onSpeechDelta: (text, locale) => calls.push(["delta", text, locale]),
    onSpeechDone: (text, locale) => calls.push(["done", text, locale]),
    onSpeechStop: () => calls.push(["stop"]),
    onError: (error) => calls.push(["error", error.message]),
    log: { info() {} },
  });

  assert.equal(await session.ask("  介绍汴绣  "), true);
  assert.equal(requests.length, 1);
  assert.equal(requests[0][0], "/base/api/chat");
  assert.deepEqual(JSON.parse(requests[0][1].body), {
    question: "介绍汴绣",
    session_id: "s1",
    category: "传统技艺",
    locale_hint: "zh-CN",
  });
  assert.deepEqual(events, ["turn.started", "response.text.delta", "turn.completed"]);
  assert.deepEqual(calls, [
    ["stop"],
    ["submit", "介绍汴绣"],
    ["delta", "你好", "zh-CN"],
    ["done", "你好呀", "zh-CN"],
  ]);
  assert.equal(session.activeTurnId, null);
  assert.equal(session.controller, null);
});

test("superseding a text turn aborts the stream and sends best-effort cancel", async () => {
  const requests = [];
  const session = new TextConversationSession({
    apiBase: "",
    fetchFn: (url, options) => {
      requests.push([url, options]);
      return Promise.resolve({ ok: true });
    },
    getContext: () => ({ sessionId: "session 1" }),
    onSpeechStop() {},
  });
  const controller = new AbortController();
  session.controller = controller;
  session.activeTurnId = "turn/1";

  const generation = session.supersede();

  assert.equal(generation, 1);
  assert.equal(controller.signal.aborted, true);
  assert.equal(session.activeTurnId, null);
  assert.equal(requests.length, 1);
  assert.equal(requests[0][0], "/api/chat/session%201/turn/turn%2F1/cancel");
  assert.equal(requests[0][1].method, "POST");
});

test("text session reports a current stream that ends without terminal event", async () => {
  const errors = [];
  const session = new TextConversationSession({
    fetchFn: async () => responseFrom([
      'event: turn.started\ndata: {"type":"turn.started","turn_id":"t1","payload":{}}\n\n',
    ]),
    getContext: () => ({ sessionId: "s1" }),
    onError: (error) => errors.push(error.message),
    log: { info() {} },
  });

  assert.equal(await session.ask("问题"), false);
  assert.deepEqual(errors, ["stream_ended_before_terminal"]);
});
