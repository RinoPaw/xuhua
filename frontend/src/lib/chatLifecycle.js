const TERMINAL_TURN_EVENTS = new Set([
  "turn.completed",
  "turn.failed",
  "turn.cancelled",
]);

export function nextActiveTurnId(currentTurnId, event) {
  const turnId = String(event?.turn_id || "").trim();
  if (!turnId) return currentTurnId || null;
  if (!TERMINAL_TURN_EVENTS.has(event?.type)) return turnId;
  if (!currentTurnId || currentTurnId === turnId) return null;
  return currentTurnId;
}

export function cancelTurnBestEffort({ fetchFn = globalThis.fetch, url } = {}) {
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
