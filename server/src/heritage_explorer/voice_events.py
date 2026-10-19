"""Typed server events for the realtime voice WebSocket protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TypeAlias


@dataclass(frozen=True, slots=True)
class ReadyEvent:
    pass


@dataclass(frozen=True, slots=True)
class VoiceStatusEvent:
    status: str
    turn_id: str = ""
    utterance_id: int | None = None
    locale: str = ""


@dataclass(frozen=True, slots=True)
class UserPartialEvent:
    utterance_id: int
    revision: int
    text: str


@dataclass(frozen=True, slots=True)
class UserTranscriptEvent:
    utterance_id: int
    revision: int
    text: str
    raw_text: str
    normalizations: tuple[dict[str, Any], ...]
    locale: str
    asr_engine: str = "xfyun_slm"

    def __post_init__(self) -> None:
        # ``chinese`` was the old application label. The actual provider path
        # is Xunfei's bilingual SLM model, so normalize the legacy value at the
        # protocol boundary without keeping a second English/Chinese engine.
        if self.asr_engine == "chinese":
            object.__setattr__(self, "asr_engine", "xfyun_slm")


@dataclass(frozen=True, slots=True)
class UtteranceRejectedEvent:
    utterance_id: int
    reason: str = ""


@dataclass(frozen=True, slots=True)
class AssistantDeltaEvent:
    session_id: str
    turn_id: str
    text: str
    locale: str
    acknowledgement: bool = False


@dataclass(frozen=True, slots=True)
class SourcesEvent:
    session_id: str
    turn_id: str
    items: tuple[dict[str, Any], ...]


@dataclass(frozen=True, slots=True)
class AssistantDoneEvent:
    session_id: str
    turn_id: str
    text: str
    locale: str
    acknowledgement: bool = False


@dataclass(frozen=True, slots=True)
class AssistantCancelledEvent:
    session_id: str
    turn_id: str
    reason: str


@dataclass(frozen=True, slots=True)
class InterruptAckEvent:
    """The requested cancellation work has completed on the server."""

    request_id: str
    reason: str
    turn_id: str = ""
    utterance_id: int = 0
    cancelled: bool = False


@dataclass(frozen=True, slots=True)
class VoiceErrorEvent:
    message: str
    code: str = ""
    turn_id: str = ""
    utterance_id: int | None = None


VoiceServerEvent: TypeAlias = (
    ReadyEvent
    | VoiceStatusEvent
    | UserPartialEvent
    | UserTranscriptEvent
    | UtteranceRejectedEvent
    | AssistantDeltaEvent
    | SourcesEvent
    | AssistantDoneEvent
    | AssistantCancelledEvent
    | InterruptAckEvent
    | VoiceErrorEvent
)


def encode_voice_event(event: VoiceServerEvent) -> dict[str, Any]:
    """Encode one canonical server event into the stable browser wire shape."""

    if isinstance(event, ReadyEvent):
        return {"type": "ready"}
    if isinstance(event, VoiceStatusEvent):
        payload: dict[str, Any] = {"type": "status", "status": event.status}
        if event.turn_id:
            payload["turn_id"] = event.turn_id
        if event.utterance_id is not None:
            payload["utterance_id"] = event.utterance_id
        if event.locale:
            payload["locale"] = event.locale
        return payload
    if isinstance(event, UserPartialEvent):
        return {
            "type": "user.partial",
            "utterance_id": event.utterance_id,
            "revision": event.revision,
            "text": event.text,
            "final": False,
        }
    if isinstance(event, UserTranscriptEvent):
        return {
            "type": "user.transcript",
            "utterance_id": event.utterance_id,
            "revision": event.revision,
            "final": True,
            "text": event.text,
            "raw_text": event.raw_text,
            "normalizations": list(event.normalizations),
            "locale": event.locale,
            "asr_engine": event.asr_engine,
        }
    if isinstance(event, UtteranceRejectedEvent):
        payload = {
            "type": "utterance.rejected",
            "utterance_id": event.utterance_id,
        }
        if event.reason:
            payload["reason"] = event.reason
        return payload
    if isinstance(event, AssistantDeltaEvent):
        return {
            "type": "assistant.delta",
            "session_id": event.session_id,
            "turn_id": event.turn_id,
            "text": event.text,
            "locale": event.locale,
            **({"acknowledgement": True} if event.acknowledgement else {}),
        }
    if isinstance(event, SourcesEvent):
        return {
            "type": "sources",
            "session_id": event.session_id,
            "turn_id": event.turn_id,
            "items": list(event.items),
        }
    if isinstance(event, AssistantDoneEvent):
        return {
            "type": "assistant.done",
            "session_id": event.session_id,
            "turn_id": event.turn_id,
            "text": event.text,
            "locale": event.locale,
            **({"acknowledgement": True} if event.acknowledgement else {}),
        }
    if isinstance(event, AssistantCancelledEvent):
        return {
            "type": "assistant.cancelled",
            "session_id": event.session_id,
            "turn_id": event.turn_id,
            "reason": event.reason,
        }
    if isinstance(event, InterruptAckEvent):
        return {
            "type": "interrupt.ack",
            "request_id": event.request_id,
            "reason": event.reason,
            "turn_id": event.turn_id,
            "utterance_id": event.utterance_id,
            "cancelled": event.cancelled,
        }
    if isinstance(event, VoiceErrorEvent):
        payload = {"type": "error", "message": event.message}
        if event.code:
            payload["code"] = event.code
        if event.turn_id:
            payload["turn_id"] = event.turn_id
        if event.utterance_id is not None:
            payload["utterance_id"] = event.utterance_id
        return payload
    raise TypeError(f"unsupported voice server event: {type(event)!r}")


__all__ = [
    "AssistantCancelledEvent",
    "AssistantDeltaEvent",
    "AssistantDoneEvent",
    "InterruptAckEvent",
    "ReadyEvent",
    "SourcesEvent",
    "UserPartialEvent",
    "UserTranscriptEvent",
    "UtteranceRejectedEvent",
    "VoiceErrorEvent",
    "VoiceServerEvent",
    "VoiceStatusEvent",
    "encode_voice_event",
]
