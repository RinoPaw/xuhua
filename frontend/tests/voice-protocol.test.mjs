import assert from "node:assert/strict";
import test from "node:test";

import {
  acceptAssistantTurn,
  assistantEventLocale,
  buildTtsUrl,
  compactRecognitionContext,
  rememberIgnoredTurn,
  resolveSpeechLocale,
  websocketUrl,
} from "../src/lib/voiceProtocol.js";

test("websocketUrl preserves path and maps HTTP schemes", () => {
  assert.equal(websocketUrl("/api/voice", "https://example.com/app"), "wss://example.com/api/voice");
  assert.equal(websocketUrl("/api/voice", "http://localhost:5050/"), "ws://localhost:5050/api/voice");
});

test("compactRecognitionContext bounds and de-duplicates titles", () => {
  const context = compactRecognitionContext({
    category: "传统技艺",
    visibleItems: [{ title: "汴绣" }, { title: "汴绣" }, { title: "木版年画" }],
    selectedItem: { title: "汴绣" },
    sessionId: "session-1",
    localeHint: "zh-CN",
    preferredLocales: ["en-US"],
  });
  assert.equal(context.category, "传统技艺");
  assert.deepEqual(context.titles, ["汴绣", "木版年画"]);
  assert.equal(context.selected_title, "汴绣");
  assert.equal(context.session_id, "session-1");
  assert.equal(context.locale_hint, "zh-CN");
});

test("speech helpers normalize locale and build TTS URL", () => {
  assert.equal(resolveSpeechLocale("yue-HK"), "yue-HK");
  assert.equal(assistantEventLocale({ payload: { locale: "ja-JP" } }), "ja-JP");
  const url = buildTtsUrl({
    websocketPath: "/api/voice",
    text: "汴绣",
    traceId: "trace 1",
    segment: 2,
    reason: "text_complete",
    locale: "zh-CN",
  });
  assert.match(url, /^\/api\/tts\?/u);
  assert.match(url, /text=%E6%B1%B4%E7%BB%A3/u);
  assert.match(url, /trace_id=trace%201/u);
  assert.match(url, /segment=2/u);
});

test("assistant turn acceptance rejects stale or ignored turns", () => {
  const active = { current: "" };
  const ignored = new Set();
  assert.equal(acceptAssistantTurn({ turn_id: "turn-1" }, active, ignored), true);
  assert.equal(active.current, "turn-1");
  assert.equal(acceptAssistantTurn({ turn_id: "turn-2" }, active, ignored), false);
  rememberIgnoredTurn(ignored, "turn-1");
  active.current = "";
  assert.equal(acceptAssistantTurn({ turn_id: "turn-1" }, active, ignored), false);
});
