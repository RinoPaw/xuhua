import { DEFAULT_LOCALE, getPreferredLocales, normalizeLocaleHint } from "./locale.js";

function normalizeTurnId(value) {
  const id = String(value ?? "").trim();
  return id || "";
}

export class VoiceTurnTracker {
  constructor({ ignoredLimit = 32 } = {}) {
    this.activeTurnId = "";
    this.ignoredTurns = new Set();
    this.ignoredLimit = Math.max(1, Number(ignoredLimit) || 32);
  }

  get current() {
    return this.activeTurnId;
  }

  setActive(turnId) {
    const id = normalizeTurnId(turnId);
    if (!id || this.ignoredTurns.has(id)) return false;
    if (this.activeTurnId && this.activeTurnId !== id) return false;
    this.activeTurnId = id;
    return true;
  }

  accept(message) {
    return this.setActive(message?.turn_id);
  }

  ignore(turnId = this.activeTurnId) {
    const id = normalizeTurnId(turnId);
    if (!id) return false;
    this.ignoredTurns.add(id);
    while (this.ignoredTurns.size > this.ignoredLimit) {
      this.ignoredTurns.delete(this.ignoredTurns.values().next().value);
    }
    if (this.activeTurnId === id) this.activeTurnId = "";
    return true;
  }

  ignoreActive() {
    return this.ignore(this.activeTurnId);
  }

  clearActive() {
    this.activeTurnId = "";
  }

  reset() {
    this.activeTurnId = "";
    this.ignoredTurns.clear();
  }
}

export function websocketUrl(path, baseUrl = globalThis.location?.href || "http://localhost/") {
  const url = new URL(path, baseUrl);
  if (url.protocol === "https:") url.protocol = "wss:";
  else if (url.protocol === "http:") url.protocol = "ws:";
  else if (!["ws:", "wss:"].includes(url.protocol)) throw new Error("voice_socket_invalid_scheme");
  return url.toString();
}

export function resolveSpeechLocale(value, fallback = DEFAULT_LOCALE) {
  return normalizeLocaleHint(value) || normalizeLocaleHint(fallback) || DEFAULT_LOCALE;
}

export function assistantEventLocale(message, fallback = DEFAULT_LOCALE) {
  return resolveSpeechLocale(
    message?.locale
      || message?.response_locale
      || message?.payload?.locale
      || message?.payload?.response_locale,
    fallback,
  );
}

export function ttsEndpoint(websocketPath) {
  const value = String(websocketPath || "/api/voice");
  if (/^wss?:\/\//iu.test(value)) {
    const url = new URL(value);
    url.protocol = url.protocol === "wss:" ? "https:" : "http:";
    url.pathname = url.pathname.replace(/\/voice$/, "/tts");
    return url.toString();
  }
  return value.replace(/\/voice$/, "/tts");
}

export async function requestTtsSource({
  websocketPath,
  text,
  traceId,
  segment,
  reason,
  locale,
  signal,
  fetchImpl = globalThis.fetch,
}) {
  if (typeof fetchImpl !== "function") throw new Error("tts_fetch_unavailable");
  const endpoint = ttsEndpoint(websocketPath);
  const response = await fetchImpl(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      text: String(text || ""),
      trace_id: String(traceId || ""),
      segment: Number(segment) || 0,
      reason: String(reason || ""),
      locale: resolveSpeechLocale(locale),
    }),
    signal,
  });
  if (!response.ok) throw new Error(`tts_ticket_${response.status}`);
  const payload = await response.json();
  const token = String(payload?.token || "").trim();
  if (!token) throw new Error("tts_ticket_invalid");
  return `${endpoint.replace(/\/+$/u, "")}/${encodeURIComponent(token)}`;
}

export function compactRecognitionContext(context) {
  const value = context && typeof context === "object" ? context : {};
  const values = [];
  for (const key of ["selectedTitle", "selectedItem", "selected"]) {
    if (value[key]) values.push(value[key]);
  }
  for (const key of ["titles", "visibleTitles", "visibleItems", "items"]) {
    const entries = Array.isArray(value[key]) ? value[key] : [];
    values.push(...entries);
  }

  const titles = [];
  const seen = new Set();
  for (const entry of values) {
    const title = String(entry && typeof entry === "object" ? entry.title || "" : entry || "").trim();
    if (!title || seen.has(title)) continue;
    seen.add(title);
    titles.push(title.slice(0, 200));
    if (titles.length >= 8) break;
  }

  const rawPreferredLocales = Array.isArray(value.preferredLocales)
    ? value.preferredLocales
    : Array.isArray(value.preferred_locales)
      ? value.preferred_locales
      : [];
  const requestedLocale = normalizeLocaleHint(value.localeHint || value.locale_hint || value.locale);
  const preferredLocales = getPreferredLocales({
    languages: [...(requestedLocale ? [requestedLocale] : []), ...rawPreferredLocales],
  });
  const localeHint = requestedLocale || preferredLocales[0] || DEFAULT_LOCALE;

  return {
    category: String(value.category || "").trim().slice(0, 200),
    titles,
    selected_title: String(
      value.selectedTitle || value.selectedItem?.title || value.selected?.title || "",
    ).trim().slice(0, 200),
    session_id: String(value.sessionId || "").trim().slice(0, 128),
    locale_hint: localeHint,
    preferred_locales: preferredLocales,
  };
}
