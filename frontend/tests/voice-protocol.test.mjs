import assert from "node:assert/strict";
import test from "node:test";

import {
  assistantEventLocale,
  buildTtsUrl,
  compactRecognitionContext,
  resolveSpeechLocale,
  VoiceTurnTracker,
  websocketUrl,
} from "../src/lib/voiceProtocol.js";

test("websocketUrl preserves WebSocket schemes and maps HTTP schemes", () => {
  assert.equal(websocketUrl("/api/voice", "https://example.com/app"), "wss://example.com/api/voice");
  assert.equal(websocketUrl("/api/voice", "http://localhost:5050/"), "ws://localhost:5050/api/voice");
  assert.equal(
    websocketUrl("wss://voice.example.com/api/voice", "https://example.com/app"),
    "wss://voice.example.com/api/voice",
  );
  assert.equal(
    websocketUrl("ws://localhost:5050/api/voice", "https://example.com/app"),
    "ws://localhost:5050/api/voice",
  );
  assert.throws(
    () => websocketUrl("ftp://example.com/api/voice", "https://example.com/app"),
    /voice_socket_invalid_scheme/u,
  );
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

  const secureUrl = buildTtsUrl({
    websocketPath: "wss://voice.example.com/api/voice",
    text: "汴绣",
    traceId: "trace-2",
    segment: 0,
    reason: "first_sentence",
    locale: "zh-CN",
  });
  assert.match(secureUrl, /^https:\/\/voice\.example\.com\/api\/tts\?/u);
  assert.doesNotMatch(secureUrl, /^wss:/u);

  const localUrl = buildTtsUrl({
    websocketPath: "ws://localhost:5050/api/voice",
    text: "test",
    traceId: "trace-3",
    segment: 0,
    reason: "text_complete",
    locale: "en-US",
  });
  assert.match(localUrl, /^http:\/\/localhost:5050\/api\/tts\?/u);
});

test("assistant turn tracker owns active and ignored turn identity", () => {
  const turns = new VoiceTurnTracker({ ignoredLimit: 2 });
  assert.equal(turns.accept({ turn_id: "turn-1" }), true);
  assert.equal(turns.current, "turn-1");
  assert.equal(turns.accept({ turn_id: "turn-2" }), false);

  assert.equal(turns.ignoreActive(), true);
  assert.equal(turns.current, "");
  assert.equal(turns.accept({ turn_id: "turn-1" }), false);
  assert.equal(turns.accept({ turn_id: "turn-2" }), true);
  turns.ignoreActive();
  turns.setActive("turn-3");
  turns.ignoreActive();

  assert.equal(turns.ignoredTurns.has("turn-1"), false);
  assert.equal(turns.ignoredTurns.has("turn-2"), true);
  assert.equal(turns.ignoredTurns.has("turn-3"), true);
});
