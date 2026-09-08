from __future__ import annotations

from types import SimpleNamespace

from heritage_explorer.asr_normalization import (
    NormalizedSpan,
    normalize_asr_final,
)


def _kb(*items: tuple[str, str, tuple[str, ...]]) -> SimpleNamespace:
    return SimpleNamespace(
        items=[
            SimpleNamespace(title=title, category=category, aliases=aliases)
            for title, category, aliases in items
        ]
    )


def test_corrects_local_homophone_with_category_and_preserves_sentence() -> None:
    result = normalize_asr_final(
        "我是说卞绣，想了解它的历史。",
        kb=_kb(("汴绣", "传统美术", ())),
        category="传统美术",
    )
    assert result.canonical_text == "我是说汴绣，想了解它的历史。"
    assert result.spans == (
        NormalizedSpan(3, 5, "卞绣", "汴绣", result.spans[0].score, result.spans[0].reason),
    )


def test_nbest_can_supply_context_without_category() -> None:
    result = normalize_asr_final(
        "请介绍卞绣",
        kb=_kb(("汴绣", "传统美术", ()), ("苏醒", "", ())),
        asr_candidates=("汴绣", "请介绍卞绣"),
    )
    assert result.canonical_text == "请介绍汴绣"
    assert result.spans[0].raw == "卞绣"


def test_ordinary_word_is_not_fuzzy_changed_without_context() -> None:
    result = normalize_asr_final("我刚刚苏醒了。", kb=_kb(("苏绣", "传统美术", ())))
    assert result.canonical_text == result.raw_text
    assert result.spans == ()


def test_nbest_does_not_override_a_phonetically_different_real_word() -> None:
    result = normalize_asr_final(
        "我刚刚苏醒了。",
        kb=_kb(("苏绣", "传统美术", ())),
        category="传统美术",
        asr_candidates=("我刚刚苏醒了", "我刚刚苏绣了"),
    )
    assert result.canonical_text == result.raw_text
    assert result.spans == ()


def test_exact_title_and_alias_are_protected() -> None:
    result = normalize_asr_final(
        "汴绣和古称汴州绣",
        kb=_kb(("汴绣", "传统美术", ("汴州绣",))),
        category="传统美术",
    )
    assert result.canonical_text == result.raw_text
    assert result.spans == ()


def test_non_chinese_transcript_skips_pinyin_normalization_even_with_context() -> None:
    result = normalize_asr_final(
        "卞绣の歴史を教えてください。",
        kb=_kb(("汴绣", "传统美术", ())),
        category="传统美术",
        asr_candidates=("汴绣の歴史",),
        language="ja",
    )

    assert result.raw_text == "卞绣の歴史を教えてください。"
    assert result.canonical_text == result.raw_text
    assert result.spans == ()


def test_corrects_xuhua_homophone_when_user_addresses_assistant() -> None:
    result = normalize_asr_final(
        "徐华，给我介绍一下汴绣。",
        kb=_kb(("汴绣", "传统美术", ())),
    )

    assert result.canonical_text == "叙华，给我介绍一下汴绣。"
    assert result.spans[0].raw == "徐华"
    assert result.spans[0].canonical == "叙华"
    assert result.spans[0].reason == "assistant-name-asr-alias"


def test_corrects_xuhua_homophone_after_greeting() -> None:
    result = normalize_asr_final("你好徐华", kb=_kb())

    assert result.canonical_text == "你好叙华"
    assert len(result.spans) == 1


def test_does_not_rewrite_real_person_named_xuhua() -> None:
    result = normalize_asr_final(
        "传承人徐华的经历很丰富。",
        kb=_kb(("汴绣", "传统美术", ())),
    )

    assert result.canonical_text == result.raw_text
    assert result.spans == ()
