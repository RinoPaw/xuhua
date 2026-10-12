const HARD_BOUNDARIES = new Set(["。", "！", "!", "？", "?", "；", ";", "\n"]);
const SOFT_BOUNDARIES = new Set(["，", ",", "：", ":"]);
const CLOSING_PUNCTUATION = new Set(["\"", "'", "”", "’", ")", "]", "】", "》"]);
const COMMON_ABBREVIATION = /(?:^|\s)(?:mr|mrs|ms|dr|prof|sr|jr|st|vs|etc)\.$/iu;
const INITIALISM = /(?:^|\s)(?:[a-z]\.){2,}$/iu;
// Start synthesizing once a natural Chinese clause is long enough.
const MIN_EARLY_CJK_CHARS = 8;
// Do not send a two- or three-character standalone first sentence to Edge
// while the rest of the answer is still arriving. Full answers remain valid.
const MIN_EARLY_CJK_HARD_CHARS = 6;

function isPeriodBoundary(text, index) {
  const previous = text[index - 1] || "";
  const next = text[index + 1] || "";
  if (/\d/u.test(previous) && /\d/u.test(next)) return false;
  if (next && !/\s/u.test(next) && !CLOSING_PUNCTUATION.has(next)) return false;
  const prefix = text.slice(Math.max(0, index - 16), index + 1);
  return !COMMON_ABBREVIATION.test(prefix) && !INITIALISM.test(prefix);
}

function isCjkLocale(locale) {
  return /^(?:zh|yue|ja|ko)(?:-|$)/iu.test(String(locale || ""));
}

function spokenLength(text) {
  return [...String(text || "").replace(/\s/gu, "")].length;
}

function boundaryEnd(text, index) {
  let end = index + 1;
  while (end < text.length && CLOSING_PUNCTUATION.has(text[end])) end += 1;
  return end;
}

function firstSpeakableSegment(text, locale) {
  const allowSoftBoundary = isCjkLocale(locale);
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    const hardBoundary = HARD_BOUNDARIES.has(character)
      || (character === "." && isPeriodBoundary(text, index));
    const softBoundary = allowSoftBoundary && SOFT_BOUNDARIES.has(character);
    if (!hardBoundary && !softBoundary) continue;

    const end = boundaryEnd(text, index);
    const candidate = text.slice(0, end).trim();
    if (!candidate) continue;
    if (softBoundary && spokenLength(candidate) < MIN_EARLY_CJK_CHARS) continue;
    if (allowSoftBoundary && hardBoundary && spokenLength(candidate) < MIN_EARLY_CJK_HARD_CHARS) continue;
    return { segment: candidate, remainder: text.slice(end) };
  }
  return { segment: null, remainder: text };
}

function splitCompletedSentences(text) {
  const sentences = [];
  let start = 0;
  for (let index = 0; index < text.length; index += 1) {
    const character = text[index];
    const boundary = HARD_BOUNDARIES.has(character)
      || (character === "." && isPeriodBoundary(text, index));
    if (!boundary) continue;
    const end = boundaryEnd(text, index);
    const sentence = text.slice(start, end).trim();
    if (sentence) sentences.push(sentence);
    start = end;
    index = end - 1;
  }
  return { sentences, remainder: text.slice(start) };
}

export class TtsTextPlan {
  constructor(locale = "zh-CN") { this.reset(locale); }

  reset(locale = this.locale || "zh-CN") {
    this.locale = String(locale || "zh-CN");
    this.buffer = "";
    this.remainder = "";
    this.firstCommitted = false;
    this.finalized = false;
  }

  append(text) {
    if (this.finalized) return null;
    this.buffer += String(text || "");

    let first = null;
    if (!this.firstCommitted) {
      const early = firstSpeakableSegment(this.buffer, this.locale);
      if (early.segment) {
        first = early.segment;
        this.firstCommitted = true;
        this.buffer = early.remainder;
      }
    }

    // Do not move short completed sentences into the remainder before
    // the first segment has been committed: doing so would reorder speech.
    if (this.firstCommitted) {
      const split = splitCompletedSentences(this.buffer);
      this.buffer = split.remainder;
      if (split.sentences.length) {
        const separator = isCjkLocale(this.locale) ? "" : " ";
        const joined = split.sentences.join(separator);
        this.remainder += this.remainder && separator ? `${separator}${joined}` : joined;
      }
    }
    return first;
  }

  finish() {
    if (this.finalized) return null;
    this.finalized = true;
    const remainder = `${this.remainder}${this.buffer}`.trim();
    this.buffer = "";
    this.remainder = "";
    return remainder || null;
  }
}

export { MIN_EARLY_CJK_CHARS, splitCompletedSentences };
