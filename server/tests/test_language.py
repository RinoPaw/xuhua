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
    assert normalize_locale_hint("zh_henan") == "zh-CN"
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


def test_explicit_language_commands_override_the_script_and_provider_hint() -> None:
    requests = {
        "说一句英文。": "en-US",
        "给我说一句英语": "en-US",
        "请用英文回答": "en-US",
        "用日语介绍一下苏绣": "ja-JP",
        "说一句日文。": "ja-JP",
        "请说一句韩文": "ko-KR",
        "用韩语跟我聊": "ko-KR",
        "换成中文回答": "zh-CN",
        "Speak Korean.": "ko-KR",
        "Please answer in Japanese": "ja-JP",
        "英語で話してください": "en-US",
        "영어로 대답해 주세요": "en-US",
    }
    for text, expected in requests.items():
        assert detect_locale(text, hint="zh-CN") == expected, text


def test_mentioning_languages_does_not_force_a_response_language() -> None:
    from heritage_explorer.language import requested_response_locale

    for text in (
        "英语和日语分别有哪些特点？",
        "英文怎么说？",
        "介绍一下日语中的非遗词汇",
        "帮我解释“说一句韩文”是什么意思",
        "What is the Japanese name of this craft?",
    ):
        assert requested_response_locale(text) is None, text
    assert detect_locale("英语和日语分别有哪些特点？") == "zh-CN"
