from __future__ import annotations

from heritage_explorer.language import (
    LANGUAGE_PROFILES,
    detect_locale,
    get_language_profile,
    is_chinese_locale,
    locale_from_provider_language,
    normalize_locale_hint,
)


def test_only_four_language_profiles_are_supported() -> None:
    assert set(LANGUAGE_PROFILES) == {"zh-CN", "en-US", "ja-JP", "ko-KR"}


def test_locale_hints_are_limited_to_supported_languages() -> None:
    assert normalize_locale_hint("zh_Hans") == "zh-CN"
    assert normalize_locale_hint("ZH-hk") == "zh-CN"
    assert normalize_locale_hint("ja_jp") == "ja-JP"
    assert normalize_locale_hint("ko-KR") == "ko-KR"
    assert normalize_locale_hint("en-GB") == "en-US"
    assert normalize_locale_hint("yue-HK") is None
    assert normalize_locale_hint("zh_henan") is None
    assert normalize_locale_hint("fr-FR") is None
    assert normalize_locale_hint("auto") is None
    assert normalize_locale_hint("xx-Unknown") is None


def test_text_and_provider_hints_select_only_four_languages() -> None:
    assert detect_locale("この無形文化遺産を紹介して", hint="en-US") == "ja-JP"
    assert detect_locale("这个手艺好巴适，咋个做的？") == "zh-CN"
    assert detect_locale("河南话呢") == "zh-CN"
    assert detect_locale("Tell me about this heritage project", hint="zh-CN") == "en-US"
    assert detect_locale("곤곡이라는 전통 예술을 소개해 주세요") == "ko-KR"
    assert detect_locale("昆曲", hint="ja-JP") == "ja-JP"


def test_provider_language_tags_map_to_four_response_profiles() -> None:
    expected = {
        "zh": ("zh-CN", "zh-CN-XiaoxiaoNeural"),
        "en": ("en-US", "en-US-JennyNeural"),
        "ja": ("ja-JP", "ja-JP-NanamiNeural"),
        "ko": ("ko-KR", "ko-KR-SunHiNeural"),
    }
    for provider_tag, (locale, voice) in expected.items():
        assert locale_from_provider_language(provider_tag) == locale
        assert get_language_profile(locale).tts_voice == voice
    for unsupported in ("yue", "fr", "de", "ru", "xx"):
        assert locale_from_provider_language(unsupported) is None


def test_chinese_is_the_only_chinese_language_profile() -> None:
    assert is_chinese_locale("zh-CN")
    assert not is_chinese_locale("en-US")
    assert not is_chinese_locale("ja-JP")
    assert not is_chinese_locale("ko-KR")
    assert get_language_profile("yue-CN").code == "zh-CN"
