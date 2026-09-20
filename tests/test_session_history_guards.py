from heritage_explorer.models import ConversationTurn
from heritage_explorer.sessions import SessionStore


def make_turn(turn_id: str) -> ConversationTurn:
    return ConversationTurn(
        turn_id=turn_id,
        question=f"question-{turn_id}",
        answer=f"answer-{turn_id}",
    )


def test_cancelled_active_turn_cannot_enter_history() -> None:
    store = SessionStore()
    store.begin_turn("session", "cancelled")
    assert store.cancel_turn("session", "cancelled") is True

    store.append("session", make_turn("cancelled"))

    assert store.history("session") == []


def test_superseded_turn_cannot_enter_history_but_replacement_can() -> None:
    store = SessionStore()
    store.begin_turn("session", "old")
    store.begin_turn("session", "new")

    store.append("session", make_turn("old"))
    store.append("session", make_turn("new"))

    assert [turn.turn_id for turn in store.history("session")] == ["new"]
