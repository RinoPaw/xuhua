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



# A request to *speak* a language overrides the script used to ask for it.
# Keep this narrow: mentioning English/Japanese/Korean as a heritage topic
# must never silently switch the language of an unrelated answer.
_REQUESTED_LANGUAGE = {
    "英语": "en-US", "英文": "en-US",
    "日语": "ja-JP", "日文": "ja-JP",
    "韩语": "ko-KR", "韩文": "ko-KR",
    "中文": "zh-CN", "汉语": "zh-CN", "普通话": "zh-CN",
    "english": "en-US", "japanese": "ja-JP",
    "korean": "ko-KR", "chinese": "zh-CN",
}
_CN_LANGUAGE = r"(?:英语|英文|日语|日文|韩语|韩文|中文|汉语|普通话)"
_CN_REQUEST_PREFIX = (
    r"^\s*(?:(?:叙华[，,、]?\s*|请你|请|麻烦|帮我|能不能|可以|"
    r"给我|你|现在|接下来|先|再|试着|我想|我希望|就|都)\s*)*"
)
_CN_LANGUAGE_COMMANDS = (
    re.compile(
        _CN_REQUEST_PREFIX
        + rf"(?:用|改用|换成|切换到|切换成)\s*(?P<language>{_CN_LANGUAGE})"
    ),
    re.compile(
        _CN_REQUEST_PREFIX
        + rf"(?:说|讲|念|读)\s*(?:一|两|几|三)?\s*(?:句|段|点|些|句话)?\s*"
        + rf"(?P<language>{_CN_LANGUAGE})(?=$|[\s，,。！!？?；;、]|吧|看看|试试)"
    ),
)
_EN_LANGUAGE_COMMAND = re.compile(
    r"^\s*(?:please\s+)?(?:speak|answer|reply|respond|talk|say\s+(?:something|"
    r"a\s+sentence))\s+(?:(?:to\s+me)\s+)?(?:in\s+)?"
    r"(?P<language>english|japanese|korean|chinese)\b",
    re.IGNORECASE,
)
_JA_LANGUAGE_COMMAND = re.compile(
    r"^\s*(?P<language>英語|日本語|韓国語|中国語)で(?:話|答|説明|紹介|言)"
)
_KO_LANGUAGE_COMMAND = re.compile(
    r"^\s*(?P<language>영어|일본어|한국어|중국어)로(?:\s|$)"
)
_ADDITIONAL_LANGUAGE_NAMES = {
    "英語": "en-US", "日本語": "ja-JP", "韓国語": "ko-KR", "中国語": "zh-CN",
    "영어": "en-US", "일본어": "ja-JP",
    "한국어": "ko-KR", "중국어": "zh-CN",
}


def requested_response_locale(text: object) -> str | None:
    """Return a locale only when the user clearly asks to speak that language."""
    content = str(text or "").strip()
    for pattern in (*_CN_LANGUAGE_COMMANDS, _EN_LANGUAGE_COMMAND,
                    _JA_LANGUAGE_COMMAND, _KO_LANGUAGE_COMMAND):
        match = pattern.search(content)
        if match:
            name = match.group("language")
            return _REQUESTED_LANGUAGE.get(name.casefold()) or _ADDITIONAL_LANGUAGE_NAMES.get(name)
    return None


def detect_locale(text: object, *, hint: object = None) -> str:
    """Detect a response/TTS locale, using the browser locale only as a tie-breaker."""

    requested = requested_response_locale(text)
    if requested:
        return requested
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
    "requested_response_locale",
]
