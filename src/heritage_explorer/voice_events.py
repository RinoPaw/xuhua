"""Typed server events for the realtime voice WebSocket protocol."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, TypeAlias


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
    asr_engine: str = "chinese"


@dataclass(frozen=True, slots=True)
class UtteranceRejectedEvent:
    utterance_id: int


@dataclass(frozen=True, slots=True)
class AssistantDeltaEvent:
    session_id: str
    turn_id: str
    text: str
    locale: str


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


@dataclass(frozen=True, slots=True)
class AssistantCancelledEvent:
    session_id: str
    turn_id: str
    reason: str


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
        return {
            "type": "utterance.rejected",
            "utterance_id": event.utterance_id,
        }
    if isinstance(event, AssistantDeltaEvent):
        return {
            "type": "assistant.delta",
            "session_id": event.session_id,
            "turn_id": event.turn_id,
            "text": event.text,
            "locale": event.locale,
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
        }
    if isinstance(event, AssistantCancelledEvent):
        return {
            "type": "assistant.cancelled",
            "session_id": event.session_id,
            "turn_id": event.turn_id,
            "reason": event.reason,
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


def _mapping_tuple(value: object) -> tuple[dict[str, Any], ...]:
    if not isinstance(value, (list, tuple)):
        return ()
    return tuple(dict(item) for item in value if isinstance(item, Mapping))


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def voice_event_from_payload(payload: Mapping[str, Any]) -> VoiceServerEvent:
    """Canonicalize the legacy runtime payload while call sites migrate to events."""

    event_type = str(payload.get("type") or "")
    if event_type == "ready":
        return ReadyEvent()
    if event_type == "status":
        return VoiceStatusEvent(
            status=str(payload.get("status") or ""),
            turn_id=str(payload.get("turn_id") or ""),
            utterance_id=_optional_int(payload.get("utterance_id")),
            locale=str(payload.get("locale") or ""),
        )
    if event_type == "user.partial":
        return UserPartialEvent(
            utterance_id=int(payload.get("utterance_id") or 0),
            revision=int(payload.get("revision") or 0),
            text=str(payload.get("text") or ""),
        )
    if event_type == "user.transcript":
        return UserTranscriptEvent(
            utterance_id=int(payload.get("utterance_id") or 0),
            revision=int(payload.get("revision") or 0),
            text=str(payload.get("text") or ""),
            raw_text=str(payload.get("raw_text") or ""),
            normalizations=_mapping_tuple(payload.get("normalizations")),
            locale=str(payload.get("locale") or ""),
            asr_engine=str(payload.get("asr_engine") or "chinese"),
        )
    if event_type == "utterance.rejected":
        return UtteranceRejectedEvent(int(payload.get("utterance_id") or 0))
    if event_type == "assistant.delta":
        return AssistantDeltaEvent(
            session_id=str(payload.get("session_id") or ""),
            turn_id=str(payload.get("turn_id") or ""),
            text=str(payload.get("text") or ""),
            locale=str(payload.get("locale") or ""),
        )
    if event_type == "sources":
        return SourcesEvent(
            session_id=str(payload.get("session_id") or ""),
            turn_id=str(payload.get("turn_id") or ""),
            items=_mapping_tuple(payload.get("items")),
        )
    if event_type == "assistant.done":
        return AssistantDoneEvent(
            session_id=str(payload.get("session_id") or ""),
            turn_id=str(payload.get("turn_id") or ""),
            text=str(payload.get("text") or ""),
            locale=str(payload.get("locale") or ""),
        )
    if event_type == "assistant.cancelled":
        return AssistantCancelledEvent(
            session_id=str(payload.get("session_id") or ""),
            turn_id=str(payload.get("turn_id") or ""),
            reason=str(payload.get("reason") or "cancelled"),
        )
    if event_type == "error":
        return VoiceErrorEvent(
            message=str(payload.get("message") or ""),
            code=str(payload.get("code") or ""),
            turn_id=str(payload.get("turn_id") or ""),
            utterance_id=_optional_int(payload.get("utterance_id")),
        )
    raise ValueError(f"unknown voice server event type: {event_type!r}")


__all__ = [
    "AssistantCancelledEvent",
    "AssistantDeltaEvent",
    "AssistantDoneEvent",
    "ReadyEvent",
    "SourcesEvent",
    "UserPartialEvent",
    "UserTranscriptEvent",
    "UtteranceRejectedEvent",
    "VoiceErrorEvent",
    "VoiceServerEvent",
    "VoiceStatusEvent",
    "encode_voice_event",
    "voice_event_from_payload",
]
