import assert from "node:assert/strict";
import test from "node:test";

import { TtsClipCache } from "../src/lib/ttsClipCache.js";

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}

test("prewarm resolves one TTS ticket and keeps final audio behind a Blob URL", async () => {
  const calls = [];
  const revoked = [];
  const cache = new TtsClipCache({
    fetchImpl: async (url, options = {}) => {
      calls.push([url, options.method || "GET"]);
      if (options.method === "POST") {
        return {
          ok: true,
          async json() { return { token: "ack-token" }; },
        };
      }
      return {
        ok: true,
        async blob() { return { size: 8 }; },
      };
    },
    createObjectURL: () => "blob:ack",
    revokeObjectURL: (url) => revoked.push(url),
  });

  assert.equal(await cache.prewarm({
    websocketPath: "/api/voice",
    text: "我在。",
    locale: "zh-CN",
  }), "blob:ack");
  assert.equal(cache.get("我在。", "zh-CN"), "blob:ack");
  assert.deepEqual(calls.map((call) => call[1]), ["POST", "GET"]);

  assert.equal(await cache.prewarm({
    websocketPath: "/api/voice",
    text: "我在。",
    locale: "zh-CN",
  }), "blob:ack");
  assert.equal(calls.length, 2);

  cache.dispose();
  assert.deepEqual(revoked, ["blob:ack"]);
});

test("sourceFor waits for an in-flight prewarm instead of starting duplicate synthesis", async () => {
  const audioGate = deferred();
  let ticketCount = 0;
  const cache = new TtsClipCache({
    fetchImpl: async (_url, options = {}) => {
      if (options.method === "POST") {
        ticketCount += 1;
        return {
          ok: true,
          async json() { return { token: "ack-token" }; },
        };
      }
      await audioGate.promise;
      return {
        ok: true,
        async blob() { return { size: 4 }; },
      };
    },
    createObjectURL: () => "blob:pending-ack",
  });

  const prewarm = cache.prewarm({
    websocketPath: "/api/voice",
    text: "我在。",
    locale: "zh-CN",
  });
  const lookup = cache.sourceFor("我在。", "zh-CN");
  audioGate.resolve();

  assert.equal(await prewarm, "blob:pending-ack");
  assert.equal(await lookup, "blob:pending-ack");
  assert.equal(ticketCount, 1);
});
