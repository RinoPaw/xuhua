from __future__ import annotations

import pytest

from heritage_explorer.tts_tickets import TtsTicketCapacity, TtsTicketStore


def test_tts_tickets_are_bounded_per_client_and_expire() -> None:
    now = [100.0]
    tokens = iter(("token-a", "token-b", "token-c", "token-d"))
    store = TtsTicketStore(
        ttl_seconds=10,
        max_entries=3,
        max_per_client=2,
        clock=lambda: now[0],
        token_factory=lambda: next(tokens),
    )

    first = store.issue(
        text="第一句",
        locale="zh-CN",
        trace_id="trace-1",
        segment=0,
        reason="first_sentence",
        client_id="client-a",
    )
    second = store.issue(
        text="第二句",
        locale="zh-CN",
        trace_id="trace-1",
        segment=1,
        reason="text_complete",
        client_id="client-a",
    )
    assert first == "token-a"
    assert second == "token-b"
    first_ticket = store.get(first)
    assert first_ticket is not None
    assert first_ticket.text == "第一句"

    with pytest.raises(TtsTicketCapacity):
        store.issue(
            text="第三句",
            locale="zh-CN",
            trace_id="trace-1",
            segment=2,
            reason="text_complete",
            client_id="client-a",
        )

    third = store.issue(
        text="其他客户端",
        locale="zh-CN",
        trace_id="trace-2",
        segment=0,
        reason="first_sentence",
        client_id="client-b",
    )
    assert third == "token-c"
    assert len(store) == 3

    now[0] = 111.0
    assert store.get(first) is None
    assert len(store) == 0

    replacement = store.issue(
        text="过期后可复用容量",
        locale="zh-CN",
        trace_id="trace-3",
        segment=0,
        reason="first_sentence",
        client_id="client-a",
    )
    assert replacement == "token-d"
