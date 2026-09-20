import { DEFAULT_LOCALE, getPreferredLocales, normalizeLocaleHint } from "./locale.js";

function normalizeTurnId(value) {
  const id = String(value ?? "").trim();
  return id || "";
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

function ttsEndpoint(websocketPath) {
  const value = String(websocketPath || "/api/voice");
  if (/^wss?:\/\//iu.test(value)) {
    const url = new URL(value);
    url.protocol = url.protocol === "wss:" ? "https:" : "http:";
    url.pathname = url.pathname.replace(/\/voice$/, "/tts");
    return url.toString();
  }
  return value.replace(/\/voice$/, "/tts");
}

export function buildTtsUrl({
  websocketPath,
  text,
  traceId,
  segment,
  reason,
  locale,
}) {
  const ttsPath = ttsEndpoint(websocketPath);
  const speechLocale = resolveSpeechLocale(locale);
  const separator = ttsPath.includes("?") ? "&" : "?";
  return `${ttsPath}${separator}text=${encodeURIComponent(String(text || ""))}`
    + `&trace_id=${encodeURIComponent(String(traceId || ""))}`
    + `&segment=${encodeURIComponent(String(segment ?? 0))}`
    + `&reason=${encodeURIComponent(String(reason || ""))}`
    + `&locale=${encodeURIComponent(speechLocale)}`;
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

export function rememberIgnoredTurn(ignoredTurns, turnId, limit = 32) {
  if (!turnId) return ignoredTurns;
  ignoredTurns.add(turnId);
  if (ignoredTurns.size > limit) ignoredTurns.delete(ignoredTurns.values().next().value);
  return ignoredTurns;
}

export function acceptAssistantTurn(message, activeTurn, ignoredTurns) {
  const turnId = normalizeTurnId(message?.turn_id);
  if (!turnId || ignoredTurns.has(turnId)) return false;
  if (activeTurn.current && activeTurn.current !== turnId) return false;
  activeTurn.current = turnId;
  return true;
}
