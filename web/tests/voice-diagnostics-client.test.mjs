import assert from "node:assert/strict";
import test from "node:test";
import { reportLocalVoiceDiagnostic } from "../src/lib/voiceDiagnosticsClient.js";

test("local diagnostic transport sends only bounded safe event metadata", async () => {
  const requests = [];
  const fetchImpl = async (url, options) => {
    requests.push({ url, options });
    return { ok: true };
  };
  assert.equal(reportLocalVoiceDiagnostic("wake.local.speech_unmatched", {
    connection: "session-id", trace: "trace-123", elapsedMs: 420,
    level: 0.2, text: "SECRET_TRANSCRIPT", token: "SECRET_TOKEN",
  }, { location: { hostname: "127.0.0.1" }, fetchImpl }), true);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].url, "/api/voice/diagnostics");
  const body = JSON.parse(requests[0].options.body);
  assert.deepEqual(body, {
    event: "wake.local.speech_unmatched", connection: "session-id",
    trace: "trace-123", segment: -1, elapsed_ms: 420, level: 0.2,
  });
  assert.doesNotMatch(requests[0].options.body, /SECRET/);
});

test("public site and unknown events do not send local diagnostics", () => {
  let calls = 0;
  const fetchImpl = () => { calls += 1; return Promise.resolve(); };
  assert.equal(reportLocalVoiceDiagnostic("wake.local.detected", {}, {
    location: { hostname: "heritage.example" }, fetchImpl,
  }), false);
  assert.equal(reportLocalVoiceDiagnostic("voice.raw_audio", {}, {
    location: { hostname: "localhost" }, fetchImpl,
  }), false);
  assert.equal(calls, 0);
});
