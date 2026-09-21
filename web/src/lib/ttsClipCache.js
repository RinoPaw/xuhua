import { browserFetch } from "./browserFetch.js";
import { requestTtsSource, resolveSpeechLocale } from "./voiceProtocol.js";

function clipKey(text, locale) {
  return `${resolveSpeechLocale(locale)}\u0000${String(text || "").trim()}`;
}

function defaultCreateObjectUrl(blob) {
  const create = globalThis.URL?.createObjectURL;
  return typeof create === "function" ? create.call(globalThis.URL, blob) : "";
}

function defaultRevokeObjectUrl(url) {
  const revoke = globalThis.URL?.revokeObjectURL;
  if (typeof revoke === "function") revoke.call(globalThis.URL, url);
}

/**
 * Session-scoped cache for tiny, predictable speech clips.
 *
 * A prewarm resolves the private TTS ticket immediately, downloads the final
 * audio bytes, and keeps them behind a Blob URL. Playback therefore needs no
 * second provider round-trip. Failed prewarms are deliberately invisible to
 * the caller's main speech path; normal TTS remains the fallback.
 */
export class TtsClipCache {
  constructor({
    fetchImpl = browserFetch,
    createObjectURL = defaultCreateObjectUrl,
    revokeObjectURL = defaultRevokeObjectUrl,
  } = {}) {
    this.fetchImpl = fetchImpl;
    this.createObjectURL = createObjectURL;
    this.revokeObjectURL = revokeObjectURL;
    this.urls = new Map();
    this.pending = new Map();
    this.disposed = false;
  }

  get(text, locale = "") {
    return this.urls.get(clipKey(text, locale)) || "";
  }

  async sourceFor(text, locale = "") {
    const key = clipKey(text, locale);
    const cached = this.urls.get(key);
    if (cached) return cached;
    const pending = this.pending.get(key)?.promise;
    if (!pending) return "";
    try {
      await pending;
    } catch {
      return "";
    }
    return this.urls.get(key) || "";
  }

  prewarm({ websocketPath, text, locale = "" } = {}) {
    const content = String(text || "").trim();
    if (!content || this.disposed) return Promise.resolve("");
    const resolvedLocale = resolveSpeechLocale(locale);
    const key = clipKey(content, resolvedLocale);
    const cached = this.urls.get(key);
    if (cached) return Promise.resolve(cached);
    const existing = this.pending.get(key);
    if (existing) return existing.promise;

    const controller = new AbortController();
    const promise = (async () => {
      const source = await requestTtsSource({
        websocketPath,
        text: content,
        traceId: "voice-prewarm",
        segment: 0,
        reason: "prewarm",
        locale: resolvedLocale,
        signal: controller.signal,
        fetchImpl: this.fetchImpl,
      });
      const response = await this.fetchImpl(source, { signal: controller.signal });
      if (!response?.ok) throw new Error(`tts_prewarm_${response?.status || 0}`);
      const blob = await response.blob();
      if (!blob || !(blob.size > 0)) throw new Error("tts_prewarm_empty");
      const url = String(this.createObjectURL(blob) || "");
      if (!url) throw new Error("tts_prewarm_object_url_unavailable");
      if (this.disposed) {
        this.revokeObjectURL(url);
        return "";
      }
      this.urls.set(key, url);
      return url;
    })().finally(() => {
      const current = this.pending.get(key);
      if (current?.promise === promise) this.pending.delete(key);
    });

    this.pending.set(key, { controller, promise });
    return promise;
  }

  dispose() {
    if (this.disposed) return;
    this.disposed = true;
    for (const { controller } of this.pending.values()) controller.abort();
    this.pending.clear();
    for (const url of this.urls.values()) this.revokeObjectURL(url);
    this.urls.clear();
  }
}

export { clipKey };
