import test from "node:test";
import assert from "node:assert/strict";

import {
  DEFAULT_LOCALE,
  getLocaleHint,
  getPreferredLocales,
  normalizeLocaleHint,
} from "../src/lib/locale.js";
import {
  assistantEventLocale,
  compactRecognitionContext,
} from "../src/lib/voiceProtocol.js";

test("normalizes browser locales, removes duplicates, and falls back safely", () => {
  assert.equal(normalizeLocaleHint("zh_cn"), "zh-CN");
  assert.equal(normalizeLocaleHint("not a locale"), "");
  assert.deepEqual(
    getPreferredLocales({ languages: ["en-us", "en-US", "ja_jp", "bad locale"] }),
    ["en-US", "ja-JP"],
  );
  assert.equal(getLocaleHint({ languages: [] }), DEFAULT_LOCALE);
});

test("adds hidden locale hints to the bounded recognition context", () => {
  const context = compactRecognitionContext({
    localeHint: "en-us",
    preferredLocales: ["ja-JP", "en-US"],
    sessionId: "session",
    selectedItem: { title: "昆曲" },
  });

  assert.equal(context.locale_hint, "en-US");
  assert.deepEqual(context.preferred_locales, ["en-US", "ja-JP"]);
  assert.equal(context.selected_title, "昆曲");
  assert.equal(context.session_id, "session");
});

test("reads locale from realtime event envelopes with a safe fallback", () => {
  assert.equal(assistantEventLocale({ locale: "ja-JP" }, "en-US"), "ja-JP");
  assert.equal(
    assistantEventLocale({ payload: { locale: "yue-HK" } }, "en-US"),
    "yue-HK",
  );
  assert.equal(assistantEventLocale({}, "de-DE"), "de-DE");
});
