from heritage_explorer.models import ConversationTurn
from heritage_explorer.sessions import SessionStore


def make_turn(turn_id: str, *, answer: str | None = None) -> ConversationTurn:
    return ConversationTurn(
        turn_id=turn_id,
        question=f"question-{turn_id}",
        answer=answer or f"answer-{turn_id}",
    )


def test_cancelled_active_turn_cannot_enter_history() -> None:
    store = SessionStore()
    _, _, cancel_event = store.begin_turn("session", "cancelled")
    assert store.cancel_turn("session", "cancelled") is True

    store.append("session", make_turn("cancelled"), cancel_event)

    assert store.history("session") == []


def test_superseded_turn_cannot_enter_history_but_replacement_can() -> None:
    store = SessionStore()
    _, _, old_event = store.begin_turn("session", "old")
    _, _, new_event = store.begin_turn("session", "new")

    store.append("session", make_turn("old"), old_event)
    store.append("session", make_turn("new"), new_event)

    assert [turn.turn_id for turn in store.history("session")] == ["new"]


def test_reused_turn_id_keeps_generation_reason_and_history_isolation() -> None:
    store = SessionStore()
    _, _, old_event = store.begin_turn("session", "same")
    _, _, replacement_event = store.begin_turn("session", "same")

    assert old_event.is_set()
    assert store.cancel_reason("session", "same", old_event) == "superseded"
    assert store.cancel_reason("session", "same", replacement_event) is None

    store.append("session", make_turn("same", answer="stale"), old_event)
    store.append("session", make_turn("same", answer="replacement"), replacement_event)

    history = store.history("session")
    assert [turn.answer for turn in history] == ["replacement"]
