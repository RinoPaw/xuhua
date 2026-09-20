import assert from "node:assert/strict";
import test from "node:test";

import {
  assistantEventLocale,
  compactRecognitionContext,
  requestTtsSource,
  resolveSpeechLocale,
  ttsEndpoint,
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

test("speech helpers normalize locale and derive TTS endpoints", () => {
  assert.equal(resolveSpeechLocale("yue-HK"), "yue-HK");
  assert.equal(assistantEventLocale({ payload: { locale: "ja-JP" } }), "ja-JP");
  assert.equal(ttsEndpoint("/api/voice"), "/api/tts");
  assert.equal(
    ttsEndpoint("wss://voice.example.com/api/voice"),
    "https://voice.example.com/api/tts",
  );
  assert.equal(
    ttsEndpoint("ws://localhost:5050/api/voice"),
    "http://localhost:5050/api/tts",
  );
});

test("TTS text is posted in the request body and never copied into the stream URL", async () => {
  const calls = [];
  const source = await requestTtsSource({
    websocketPath: "wss://voice.example.com/api/voice",
    text: "汴绣是什么？",
    traceId: "trace 1",
    segment: 1,
    reason: "text_complete",
    locale: "zh-CN",
    fetchImpl: async (url, options) => {
      calls.push({ url, options });
      return {
        ok: true,
        async json() { return { token: "private-token" }; },
      };
    },
  });

  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "https://voice.example.com/api/tts");
  assert.equal(calls[0].options.method, "POST");
  assert.deepEqual(JSON.parse(calls[0].options.body), {
    text: "汴绣是什么？",
    trace_id: "trace 1",
    segment: 1,
    reason: "text_complete",
    locale: "zh-CN",
  });
  assert.equal(source, "https://voice.example.com/api/tts/private-token");
  assert.equal(source.includes("汴绣"), false);
  assert.equal(source.includes("text="), false);
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
