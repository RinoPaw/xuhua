/** Local-only diagnostic transport; never forward audio or transcript text. */
const EVENTS = new Set([
  "wake.local.listening", "wake.local.detected", "wake.local.speech_unmatched",
  "wake.local.stopped", "wake.remote.connected", "wake.remote.failed",
  "voice.tts.playing", "voice.tts.failed", "voice.tts.complete",
  "voice.tts.segment_complete", "voice.outcome",
]);
const safeToken = (value) => /^[A-Za-z0-9_-]{1,72}$/u.test(String(value || ""))
  ? String(value) : "-";
const safeNumber = (value, limit) => Number.isFinite(Number(value)) && Number(value) >= 0
  ? Math.min(Number(value), limit) : 0;

export function reportLocalVoiceDiagnostic(event, details = {}, {
  location = globalThis.location,
  fetchImpl = globalThis.fetch,
} = {}) {
  if (!["localhost", "127.0.0.1", "::1", "[::1]"].includes(location?.hostname)
    || !EVENTS.has(event) || typeof fetchImpl !== "function") return false;
  const payload = {
    event,
    connection: safeToken(details.connection),
    trace: safeToken(details.trace),
    segment: Number.isInteger(details.segment) && details.segment >= 0
      ? Math.min(details.segment, 999) : -1,
    elapsed_ms: safeNumber(details.elapsedMs, 300000),
    level: safeNumber(details.level, 1),
  };
  try {
    const pending = fetchImpl("/api/voice/diagnostics", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
      keepalive: true,
    });
    pending?.catch?.(() => {});
    return true;
  } catch {
    return false;
  }
}
