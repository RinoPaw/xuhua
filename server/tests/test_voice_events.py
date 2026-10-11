from heritage_explorer.voice_events import (
    AssistantCancelledEvent,
    AssistantDeltaEvent,
    AssistantDoneEvent,
    ReadyEvent,
    SourcesEvent,
    UserPartialEvent,
    UserTranscriptEvent,
    UtteranceRejectedEvent,
    VoiceErrorEvent,
    VoiceStatusEvent,
    encode_voice_event,
)


def test_server_events_encode_to_stable_wire_shapes() -> None:
    cases = [
        (ReadyEvent(), {"type": "ready"}),
        (
            VoiceStatusEvent("thinking", turn_id="turn-1", locale="yue-CN"),
            {
                "type": "status",
                "status": "thinking",
                "turn_id": "turn-1",
                "locale": "yue-CN",
            },
        ),
        (
            VoiceStatusEvent("transcribing", utterance_id=3),
            {"type": "status", "status": "transcribing", "utterance_id": 3},
        ),
        (
            UserPartialEvent(3, 2, "汴"),
            {
                "type": "user.partial",
                "utterance_id": 3,
                "revision": 2,
                "text": "汴",
                "final": False,
            },
        ),
        (
            UserTranscriptEvent(
                3,
                2,
                "汴绣",
                "卞绣",
                ({"raw": "卞绣", "canonical": "汴绣"},),
                "zh-CN",
            ),
            {
                "type": "user.transcript",
                "utterance_id": 3,
                "revision": 2,
                "final": True,
                "text": "汴绣",
                "raw_text": "卞绣",
                "normalizations": [{"raw": "卞绣", "canonical": "汴绣"}],
                "locale": "zh-CN",
                "asr_engine": "xfyun_slm",
            },
        ),
        (
            UtteranceRejectedEvent(4),
            {"type": "utterance.rejected", "utterance_id": 4},
        ),
        (
            AssistantDeltaEvent("session", "turn", "好", "zh-CN"),
            {
                "type": "assistant.delta",
                "session_id": "session",
                "turn_id": "turn",
                "text": "好",
                "locale": "zh-CN",
            },
        ),
        (
            SourcesEvent("session", "turn", ({"id": "item-1"},)),
            {
                "type": "sources",
                "session_id": "session",
                "turn_id": "turn",
                "items": [{"id": "item-1"}],
            },
        ),
        (
            AssistantDoneEvent("session", "turn", "好的", "zh-CN"),
            {
                "type": "assistant.done",
                "session_id": "session",
                "turn_id": "turn",
                "text": "好的",
                "locale": "zh-CN",
            },
        ),
        (
            AssistantCancelledEvent("session", "turn", "superseded"),
            {
                "type": "assistant.cancelled",
                "session_id": "session",
                "turn_id": "turn",
                "reason": "superseded",
            },
        ),
        (
            VoiceErrorEvent(
                "语音识别暂时不可用",
                code="asr_unavailable",
                utterance_id=5,
            ),
            {
                "type": "error",
                "message": "语音识别暂时不可用",
                "code": "asr_unavailable",
                "utterance_id": 5,
            },
        ),
    ]

    for event, expected in cases:
        assert encode_voice_event(event) == expected


def test_legacy_chinese_engine_label_is_normalized_to_the_single_slm_path() -> None:
    event = UserTranscriptEvent(1, 1, "hello", "hello", (), "en-US", "chinese")
    assert encode_voice_event(event)["asr_engine"] == "xfyun_slm"



def test_interruption_ack_encodes_actual_cancellation_details() -> None:
    from heritage_explorer.voice_events import InterruptAckEvent

    assert encode_voice_event(
        InterruptAckEvent("ab" * 16, "barge_in", "turn-1", 7, True)
    ) == {
        "type": "interrupt.ack",
        "request_id": "ab" * 16,
        "reason": "barge_in",
        "turn_id": "turn-1",
        "utterance_id": 7,
        "cancelled": True,
    }
