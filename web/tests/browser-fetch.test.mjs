import assert from "node:assert/strict";
import test from "node:test";

import { browserFetch } from "../src/lib/browserFetch.js";

test("browserFetch preserves the global receiver required by browser-native fetch", async () => {
  const originalFetch = globalThis.fetch;
  let receiver = null;
  let received = null;

  globalThis.fetch = function (...args) {
    receiver = this;
    received = args;
    return Promise.resolve({ ok: true });
  };

  try {
    const response = await browserFetch("/api/meta", { method: "GET" });
    assert.equal(response.ok, true);
    assert.equal(receiver, globalThis);
    assert.equal(received[0], "/api/meta");
    assert.deepEqual(received[1], { method: "GET" });
  } finally {
    globalThis.fetch = originalFetch;
  }
});
