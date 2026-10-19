import test from "node:test";
import assert from "node:assert/strict";
import { acknowledgementAudio } from "../src/lib/speechProfile.js";
import { TtsClipCache } from "../src/lib/ttsClipCache.js";
import { VoiceOutputController } from "../src/lib/voiceOutput.js";

test("acknowledgement cache keeps Yunxia and Xiaolu clips separate", async () => {
  const fetched = [];
  let count = 0;
  const cache = new TtsClipCache({
    fetchImpl: async url => { fetched.push(url); return { ok: true, blob: async () => new Blob(["audio"]) }; },
    createObjectURL: () => `blob:voice-${++count}`, revokeObjectURL() {},
  });
  try {
    const xuhua = await cache.sourceFor("我在。", "zh-CN", "/api/voice");
    const shizha = await cache.sourceFor("我在。", "zh-CN", "/shizha/api/voice");
    assert.notEqual(xuhua, shizha);
    assert.equal(await cache.sourceFor("我在。", "zh-CN", "/api/voice"), xuhua);
    assert.equal(await cache.sourceFor("我在。", "zh-CN", "/shizha/api/voice"), shizha);
    assert.deepEqual(fetched, ["/assets/audio/ack-wozai-x4-yezi.mp3", "/assets/audio/ack-wozai-yunxia.mp3"]);
  } finally { cache.dispose(); }
});

test("audio unlocking chooses the same voice asset as later acknowledgements", () => {
  const unlocked = [];
  const output = new VoiceOutputController({ websocketPath: "/shizha/api/voice",
    createScheduler: () => ({ unlock: source => unlocked.push(source) }),
  });
  output.unlock();
  output.setWebsocketPath("/api/voice");
  output.unlock();
  assert.deepEqual(unlocked, [acknowledgementAudio("/shizha/api/voice"), acknowledgementAudio("/api/voice")]);
});
