import assert from "node:assert/strict";
import test from "node:test";

import {
  conversationReducer,
  initialConversationState,
  rotateAndLimit,
} from "../src/lib/conversationState.js";

function state() {
  return { ...initialConversationState, sessionId: "session-1", messages: [], sources: [] };
}

test("ask appends a user turn and resets per-turn state", () => {
  const next = conversationReducer(
    { ...state(), error: "old", sources: [{ id: "old" }] },
    { type: "ask", text: "介绍汴绣" },
  );
  assert.equal(next.phase, "retrieving");
  assert.equal(next.error, "");
  assert.deepEqual(next.sources, []);
  assert.equal(next.messages.at(-1).content, "介绍汴绣");
  assert.equal(next.messages.at(-1).status, "complete");
});

test("realtime partials reuse one transcribing user bubble", () => {
  const first = conversationReducer(state(), { type: "realtime.user.partial", text: "汴" });
  const second = conversationReducer(first, { type: "realtime.user.partial", text: "汴绣" });
  assert.equal(second.messages.length, 1);
  assert.equal(second.messages[0].content, "汴绣");
  assert.equal(second.messages[0].status, "transcribing");

  const final = conversationReducer(second, { type: "realtime.user", text: "汴绣" });
  assert.equal(final.messages.length, 1);
  assert.equal(final.messages[0].status, "complete");
});

test("an empty realtime partial withdraws only the pending transcription bubble", () => {
  const partial = conversationReducer(state(), { type: "realtime.user.partial", text: "汴" });
  const rejected = conversationReducer(partial, { type: "realtime.user.partial", text: "" });
  assert.deepEqual(rejected.messages, []);

  const complete = conversationReducer(state(), { type: "realtime.user", text: "汴绣" });
  const untouched = conversationReducer(complete, { type: "realtime.user.partial", text: "" });
  assert.deepEqual(untouched.messages, complete.messages);
});

test("voice errors withdraw only a pending transcription bubble", () => {
  const partial = conversationReducer(state(), { type: "realtime.user.partial", text: "汴" });
  const failed = conversationReducer(partial, { type: "error", message: "语音识别暂时不可用" });
  assert.equal(failed.phase, "error");
  assert.equal(failed.error, "语音识别暂时不可用");
  assert.deepEqual(failed.messages, []);

  const complete = conversationReducer(state(), { type: "realtime.user", text: "汴绣" });
  const completeFailed = conversationReducer(complete, { type: "error", message: "连接暂时不可用" });
  assert.deepEqual(completeFailed.messages, complete.messages);
});

test("a recovered realtime partial clears the previous voice error", () => {
  const first = conversationReducer(state(), { type: "realtime.user.partial", text: "汴" });
  const failed = conversationReducer(first, { type: "error", message: "语音识别暂时不可用" });
  const retry = conversationReducer(failed, { type: "realtime.user.partial", text: "汴绣" });

  assert.equal(retry.phase, "realtime");
  assert.equal(retry.error, "");
  assert.equal(retry.messages.length, 1);
  assert.equal(retry.messages[0].content, "汴绣");
  assert.equal(retry.messages[0].status, "transcribing");
});

test("completed assistant event reconciles streamed text, sources and suggestions", () => {
  let next = conversationReducer(state(), { type: "ask", text: "介绍汴绣" });
  next = conversationReducer(next, {
    type: "event",
    event: {
      type: "response.text.delta",
      session_id: "session-1",
      turn_id: "turn-1",
      payload: { delta: "汴绣" },
    },
  });
  next = conversationReducer(next, {
    type: "event",
    event: {
      type: "response.sources",
      session_id: "session-1",
      turn_id: "turn-1",
      payload: { sources: [{ id: "bianxiu" }] },
    },
  });
  next = conversationReducer(next, {
    type: "event",
    event: {
      type: "turn.completed",
      session_id: "session-1",
      turn_id: "turn-1",
      payload: {
        answer: "汴绣是开封代表性传统美术。",
        suggested_questions: ["它有哪些针法？", "它有哪些针法？", "现在如何传承？"],
      },
    },
  });

  assert.equal(next.phase, "complete");
  assert.equal(next.messages.at(-1).content, "汴绣是开封代表性传统美术。");
  assert.deepEqual(next.messages.at(-1).sources, [{ id: "bianxiu" }]);
  assert.deepEqual(next.messages.at(-1).suggestions, ["它有哪些针法？", "现在如何传承？"]);
});

test("interrupting a live realtime answer marks only that answer cancelled", () => {
  let next = conversationReducer(state(), { type: "realtime.user", text: "介绍汴绣" });
  next = conversationReducer(next, { type: "realtime.answer.delta", text: "汴绣是" });
  next = conversationReducer(next, { type: "realtime.interrupted" });

  assert.equal(next.phase, "realtime");
  assert.equal(next.messages.at(-1).status, "cancelled");

  next = conversationReducer(next, { type: "realtime.answer.done", text: "汴绣是传统美术" });
  next = conversationReducer(next, { type: "realtime.interrupted" });
  assert.equal(next.messages.at(-1).status, "complete");
});

test("rotateAndLimit de-duplicates and rotates deterministically", () => {
  assert.deepEqual(rotateAndLimit(["甲", "乙", "甲", "丙"], 1, 2), ["乙", "丙"]);
});
