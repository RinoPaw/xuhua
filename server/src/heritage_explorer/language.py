"""Automatic conversation-language detection and speech profile selection.

The public APIs accept locale *hints*, never provider voice names.  The text
itself remains authoritative so one browser session can naturally switch
languages without adding a settings control to the UI.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata


DEFAULT_LOCALE = "zh-CN"


@dataclass(frozen=True)
class LanguageProfile:
    code: str
    name: str
    response_instruction: str
    tts_voice: str
    asr_language: str


LANGUAGE_PROFILES: dict[str, LanguageProfile] = {
    "zh-CN": LanguageProfile(
        "zh-CN",
        "简体中文（普通话）",
        "使用自然、清晰的简体中文普通话回答。",
        "zh-CN-XiaoxiaoNeural",
        "zh",
    ),
    "en-US": LanguageProfile(
        "en-US",
        "English",
        "Reply in natural English. Keep each heritage project's canonical Chinese name when it is first mentioned.",
        "en-US-JennyNeural",
        "en",
    ),
    "ja-JP": LanguageProfile(
        "ja-JP",
        "日本語",
        "自然で分かりやすい日本語で答えてください。無形文化遺産の固有名は、初出時に中国語の正式名称も残してください。",
        "ja-JP-NanamiNeural",
        "ja",
    ),
    "ko-KR": LanguageProfile(
        "ko-KR",
        "한국어",
        "자연스럽고 이해하기 쉬운 한국어로 답하세요. 무형문화유산 고유명은 처음 언급할 때 중국어 정식 명칭도 함께 남기세요.",
        "ko-KR-SunHiNeural",
        "ko",
    ),
}


_LOCALE_ALIASES = {
    "zh": "zh-CN",
    "zh-cn": "zh-CN",
    "zh-hans": "zh-CN",
    "zh-sg": "zh-CN",
    "cmn": "zh-CN",
    "zh-hk": "zh-CN",
    "zh-tw": "zh-CN",
    "en": "en-US",
    "ja": "ja-JP",
    "jp": "ja-JP",
    "ko": "ko-KR",
    "kr": "ko-KR",
}

_PROVIDER_LANGUAGE_LOCALES = {
    "zh": "zh-CN",
    "cn": "zh-CN",
    "zh_cn": "zh-CN",
    "cn_cbm": "zh-CN",
    "en": "en-US",
    "ja": "ja-JP",
    "jp": "ja-JP",
    "ja_jp": "ja-JP",
    "ko": "ko-KR",
    "kr": "ko-KR",
    "ko_kr": "ko-KR",
}

_LATIN_LANGUAGE_WORDS: dict[str, frozenset[str]] = {
    "en-US": frozenset(
        {
            "hello",
            "thanks",
            "english",
            "heritage",
            "history",
            "what",
            "which",
            "tell",
            "about",
            "the",
            "and",
            "is",
            "are",
        }
    ),
}

_SCRIPT_PATTERNS = (
    (re.compile(r"[\u3040-\u30ff]"), "ja-JP"),
    (re.compile(r"[\uac00-\ud7af]"), "ko-KR"),
)
_HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
_LATIN = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]")
_LATIN_WORD = re.compile(r"[A-Za-zÀ-ÖØ-öø-ÿ]+")


def normalize_locale_hint(value: object) -> str | None:
    """Return a supported canonical locale for an untrusted BCP-47 hint."""

    raw = str(value or "").strip().replace("_", "-")
    if not raw or raw.casefold() == "auto":
        return None
    folded = raw.casefold()
    if folded in _LOCALE_ALIASES:
        return _LOCALE_ALIASES[folded]
    for code in LANGUAGE_PROFILES:
        if code.casefold() == folded:
            return code
    primary = folded.split("-", 1)[0]
    return _LOCALE_ALIASES.get(primary)


def _latin_locale(text: str, hint: str | None) -> str:
    normalized = unicodedata.normalize("NFKC", text).casefold()
    words = _LATIN_WORD.findall(normalized)
    scores = {
        locale: sum(word in vocabulary for word in words)
        for locale, vocabulary in _LATIN_LANGUAGE_WORDS.items()
    }
    best = max(scores, key=scores.get)
    best_score = scores[best]
    if best_score:
        tied = [locale for locale, score in scores.items() if score == best_score]
        if hint in tied:
            return hint
        return best
    if hint in {"en-US", "ja-JP", "ko-KR"}:
        return hint
    return "en-US"


def detect_locale(text: object, *, hint: object = None) -> str:
    """Detect a response/TTS locale, using the browser locale only as a tie-breaker."""

    content = str(text or "").strip()
    normalized_hint = normalize_locale_hint(hint)
    if not content:
        return normalized_hint or DEFAULT_LOCALE

    for pattern, locale in _SCRIPT_PATTERNS:
        if pattern.search(content):
            return locale

    han_count = len(_HAN.findall(content))
    latin_count = len(_LATIN.findall(content))
    if latin_count and (not han_count or latin_count >= han_count * 2):
        return _latin_locale(content, normalized_hint)
    if han_count:
        # Han-only text is ambiguous between Chinese and Japanese.  Preserve
        # text authority for explicit dialect markers above, then let the
        # browser/provider hint break this otherwise undecidable tie.
        if normalized_hint == "ja-JP":
            return normalized_hint
        return "zh-CN"
    if latin_count:
        return _latin_locale(content, normalized_hint)
    return normalized_hint or DEFAULT_LOCALE


def get_language_profile(locale: object = None, *, text: object = "") -> LanguageProfile:
    code = (
        detect_locale(text, hint=locale)
        if text
        else (normalize_locale_hint(locale) or DEFAULT_LOCALE)
    )
    return LANGUAGE_PROFILES.get(code, LANGUAGE_PROFILES[DEFAULT_LOCALE])


def locale_from_provider_language(value: object) -> str | None:
    tag = str(value or "").strip().casefold().replace("-", "_")
    return _PROVIDER_LANGUAGE_LOCALES.get(tag)


def is_chinese_locale(locale: object) -> bool:
    return get_language_profile(locale).asr_language == "zh"


__all__ = [
    "DEFAULT_LOCALE",
    "LANGUAGE_PROFILES",
    "LanguageProfile",
    "detect_locale",
    "get_language_profile",
    "is_chinese_locale",
    "locale_from_provider_language",
    "normalize_locale_hint",
]
