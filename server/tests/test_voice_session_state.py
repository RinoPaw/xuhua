from heritage_explorer.voice_protocol import ContextCommand
from heritage_explorer.voice_session import (
    ASSISTANT_NAME,
    VoiceBatchState,
    VoiceContextState,
    build_voice_hotwords,
    is_assistant_address_only,
)


def test_voice_context_state_owns_normalized_browser_context() -> None:
    state = VoiceContextState()

    state.apply(
        ContextCommand(
            session_id="session-123",
            category="传统美术",
            locale_hint="ko-KR",
            selected_title="汴绣",
            titles=("汴绣", "武强木版年画", "汴绣"),
        ),
        max_session_id_chars=7,
    )

    assert state.session_id == "session"
    assert state.category == "传统美术"
    assert state.locale_hint == "ko-KR"
    assert state.titles == ["汴绣", "武强木版年画"]


def test_voice_batch_state_clears_one_generation_atomically() -> None:
    state = VoiceBatchState()
    state.results[1] = "汴绣"
    state.candidates[1] = ("汴绣",)
    state.languages[1] = "zh_cn"
    state.failures.add(2)
    state.partials.update({1: "汴", 2: "绣"})
    state.pending_user_speaking.add(2)
    state.pending.add(1)
    state.revision = 4

    assert state.combined_partial_text() == "汴 绣"

    state.clear()

    assert state.generation == 1
    assert state.revision == 0
    assert state.results == {}
    assert state.candidates == {}
    assert state.languages == {}
    assert state.failures == set()
    assert state.partials == {}
    assert state.pending_user_speaking == set()
    assert state.pending == set()


def test_assistant_name_is_always_first_voice_hotword() -> None:
    hotwords = build_voice_hotwords(
        "传统美术",
        ["汴绣", ASSISTANT_NAME],
        ["朱仙镇木版年画"],
    )

    assert hotwords == (
        ASSISTANT_NAME,
        "传统美术",
        "汴绣",
        "朱仙镇木版年画",
    )


def test_pure_assistant_address_is_distinct_from_a_real_question() -> None:
    assert is_assistant_address_only("叙华")
    assert is_assistant_address_only("叙华。")
    assert is_assistant_address_only(" 叙华！ ")
    assert not is_assistant_address_only("叙华，讲讲汴绣")
    assert not is_assistant_address_only("循环")


def test_repeated_name_and_spoken_particles_are_still_pure_address() -> None:
    for spoken in (
        "叙华呀", "叙华啊", "叙华你在吗？",
        "叙华，叙华。", "叙华叙华！", "叙华，叙华，叙华",
    ):
        assert is_assistant_address_only(spoken), spoken


def test_address_detection_does_not_consume_question_or_normal_words() -> None:
    for spoken in (
        "叙华，请介绍汴绣", "叙华在吗，给我讲讲", "传承人叙华",
        "你叫叙华吗", "叙华叙华讲一下汴绣", "虚化",
    ):
        assert not is_assistant_address_only(spoken), spoken



def test_isolated_voice_name_recovery_is_scoped_to_exact_short_calls() -> None:
    from heritage_explorer.asr_normalization import NormalizedTranscript
    from heritage_explorer.voice_session import recover_isolated_spoken_address

    for raw in ("姓华。", "玉华。", "华。", " 华！ ", "姓华？"):
        normalized = recover_isolated_spoken_address(NormalizedTranscript(raw, raw, ()))
        assert is_assistant_address_only(normalized.canonical_text), raw
        assert normalized.raw_text == raw
        assert normalized.spans[0].reason == "isolated-voice-address-recovery"
        assert normalized.spans[0].raw in {"姓华", "玉华", "华"}

    for raw in (
        "我姓华。", "玉华是传承人", "华", "华文明", "华，请解释这个字",
        "姓华。啊，那他是虚脱了。", "玉华，请介绍汴绣", "花。", "叙华",
    ):
        normalized = recover_isolated_spoken_address(
            NormalizedTranscript(raw, raw, ())
        )
        if raw == "华":
            assert normalized.canonical_text == "叙华"
        else:
            assert normalized.canonical_text == raw, raw


def test_greeting_with_actual_name_acks_but_a_following_question_does_not() -> None:
    for value in ("你好，叙华！", "喂叙华", "您好叙华呀"):
        assert is_assistant_address_only(value), value
    for value in ("你好叙华，介绍一下汴绣", "叙华。华指什么"):
        assert not is_assistant_address_only(value), value
