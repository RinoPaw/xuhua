"""Typed client commands for the realtime voice WebSocket protocol."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, TypeAlias


@dataclass(frozen=True, slots=True)
class UtteranceStartCommand:
    interrupt: bool = False
    level: float | int | str | None = None
    threshold: float | int | str | None = None


@dataclass(frozen=True, slots=True)
class UtteranceEndCommand:
    pass


@dataclass(frozen=True, slots=True)
class UtteranceCancelCommand:
    pass


@dataclass(frozen=True, slots=True)
class BargeInCommand:
    pass


@dataclass(frozen=True, slots=True)
class InterruptCommand:
    pass


@dataclass(frozen=True, slots=True)
class TextCommand:
    text: str


@dataclass(frozen=True, slots=True)
class ContextCommand:
    session_id: str = ""
    category: str = ""
    locale_hint: str = ""
    selected_title: str = ""
    titles: tuple[str, ...] = ()

    def as_event(self) -> dict[str, Any]:
        return {
            "type": "context",
            "session_id": self.session_id,
            "category": self.category,
            "locale_hint": self.locale_hint,
            "selected_title": self.selected_title,
            "titles": list(self.titles),
        }


VoiceCommand: TypeAlias = (
    UtteranceStartCommand
    | UtteranceEndCommand
    | UtteranceCancelCommand
    | BargeInCommand
    | InterruptCommand
    | TextCommand
    | ContextCommand
)


def _title(value: object) -> str:
    if isinstance(value, dict):
        value = value.get("title", "")
    return str(value or "").strip()


def _context_command(event: dict[str, Any]) -> ContextCommand:
    selected_title = ""
    values: list[object] = []
    for key in ("selected_title", "selected_item", "selected"):
        value = event.get(key)
        title = _title(value)
        if title:
            if not selected_title:
                selected_title = title
            values.append(title)

    for key in ("titles", "visible_titles", "visible_items", "items"):
        entries = event.get(key)
        if isinstance(entries, (list, tuple)):
            values.extend(entries)

    titles: list[str] = []
    seen: set[str] = set()
    for value in values:
        title = _title(value)
        if not title or title in seen:
            continue
        seen.add(title)
        titles.append(title)

    return ContextCommand(
        session_id=str(event.get("session_id") or "").strip(),
        category=str(event.get("category") or "").strip(),
        locale_hint=str(event.get("locale_hint") or event.get("locale") or "").strip(),
        selected_title=selected_title,
        titles=tuple(titles),
    )


def decode_voice_command(raw: str) -> VoiceCommand | None:
    """Decode one browser JSON frame into the protocol's canonical command set."""

    try:
        event = json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(event, dict):
        return None

    event_type = str(event.get("type") or "")
    if event_type == "utterance.start":
        return UtteranceStartCommand(
            interrupt=bool(event.get("interrupt")),
            level=event.get("level"),
            threshold=event.get("threshold"),
        )
    if event_type == "utterance.end":
        return UtteranceEndCommand()
    if event_type == "utterance.cancel":
        return UtteranceCancelCommand()
    if event_type == "barge_in":
        return BargeInCommand()
    if event_type == "interrupt":
        return InterruptCommand()
    if event_type == "text":
        return TextCommand(str(event.get("text") or "").strip())
    if event_type == "context":
        return _context_command(event)
    return None


__all__ = [
    "BargeInCommand",
    "ContextCommand",
    "InterruptCommand",
    "TextCommand",
    "UtteranceCancelCommand",
    "UtteranceEndCommand",
    "UtteranceStartCommand",
    "VoiceCommand",
    "decode_voice_command",
]
