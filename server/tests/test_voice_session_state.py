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
            locale_hint="yue-HK",
            selected_title="汴绣",
            titles=("汴绣", "武强木版年画", "汴绣"),
        ),
        max_session_id_chars=7,
    )

    assert state.session_id == "session"
    assert state.category == "传统美术"
    assert state.locale_hint == "yue-CN"
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
