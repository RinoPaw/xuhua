const TERMINAL_TURN_EVENTS = new Set([
  "turn.completed",
  "turn.failed",
  "turn.cancelled",
]);

const browserFetch = (...args) => globalThis.fetch(...args);

export function isTerminalTurnEvent(type) {
  return TERMINAL_TURN_EVENTS.has(String(type || ""));
}

export function nextActiveTurnId(currentTurnId, event) {
  const turnId = String(event?.turn_id || "").trim();
  if (!turnId) return currentTurnId || null;
  if (!isTerminalTurnEvent(event?.type)) return turnId;
  if (!currentTurnId || currentTurnId === turnId) return null;
  return currentTurnId;
}

export function cancelTurnBestEffort({ fetchFn = browserFetch, url } = {}) {
  if (typeof fetchFn !== "function" || !url) return false;
  try {
    const request = fetchFn(url, { method: "POST" });
    if (request?.catch) request.catch(() => {});
    return true;
  } catch {
    return false;
  }
}

export { TERMINAL_TURN_EVENTS };
