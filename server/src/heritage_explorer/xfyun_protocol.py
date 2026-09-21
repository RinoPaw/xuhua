"""Pure Xunfei streaming-IAT protocol helpers."""

from __future__ import annotations

import base64
from email.utils import formatdate
import hashlib
import hmac
import re
from urllib.parse import urlencode


def format_hotwords(hotwords: str | list[str] | tuple[str, ...] | None) -> str:
    """Return Xunfei's ``dhw`` value, bounded to 1024 UTF-8 bytes."""

    if hotwords is None:
        return ""
    values = [hotwords] if isinstance(hotwords, str) else hotwords
    cleaned: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = str(value or "")
        for item in re.split(r"[|,，、;；\r\n\t]+", text):
            item = "".join(item.split())
            if not item or item in seen:
                continue
            seen.add(item)
            cleaned.append(item)

    prefix = "utf-8;"
    remaining = 1024 - len(prefix.encode("utf-8"))
    selected: list[str] = []
    used = 0
    for item in cleaned:
        encoded = item.encode("utf-8")
        required = len(encoded) if not selected else len(encoded) + 1
        if required <= remaining - used:
            selected.append(item)
            used += required
            continue
        if not selected and remaining > 0:
            item = encoded[:remaining].decode("utf-8", errors="ignore")
            if item:
                selected.append(item)
        break
    return prefix + "|".join(selected) if selected else ""


def signed_url(
    *,
    host: str,
    path: str,
    api_key: str,
    api_secret: str,
    date: str | None = None,
) -> str:
    """Build the authenticated WebSocket URL without retaining credentials."""

    request_date = date or formatdate(usegmt=True)
    origin = f"host: {host}\ndate: {request_date}\nGET {path} HTTP/1.1"
    digest = hmac.new(
        api_secret.encode(),
        origin.encode(),
        digestmod=hashlib.sha256,
    ).digest()
    signature = base64.b64encode(digest).decode()
    authorization = (
        f'api_key="{api_key}", algorithm="hmac-sha256", '
        f'headers="host date request-line", signature="{signature}"'
    )
    params = {
        "authorization": base64.b64encode(authorization.encode()).decode(),
        "date": request_date,
        "host": host,
    }
    return f"wss://{host}{path}?{urlencode(params)}"


def extract_candidates(result: dict[str, object]) -> tuple[str, ...]:
    """Extract full-text hypotheses, preserving provider candidate order."""

    words: list[list[str]] = []
    segments = result.get("ws", [])
    if not isinstance(segments, list):
        return ("",)
    for segment in segments:
        raw_candidates = segment.get("cw", []) if isinstance(segment, dict) else []
        if not isinstance(raw_candidates, list):
            continue
        candidates: list[str] = []
        for candidate in raw_candidates:
            if isinstance(candidate, dict):
                word = str(candidate.get("w", ""))
                if word:
                    candidates.append(word)
        if candidates:
            words.append(candidates)
    if not words:
        return ("",)
    count = max(len(items) for items in words)
    return tuple(
        "".join(items[index] if index < len(items) else items[0] for items in words)
        for index in range(count)
    )


def extract_text(result: dict[str, object]) -> str:
    return extract_candidates(result)[0]


def extract_language(result: dict[str, object]) -> str:
    """Return the dominant provider ``cw.lg`` source-language tag."""

    counts: dict[str, int] = {}
    segments = result.get("ws", [])
    if not isinstance(segments, list):
        return ""
    for segment in segments:
        candidates = segment.get("cw", []) if isinstance(segment, dict) else []
        if not isinstance(candidates, list):
            continue
        for candidate in candidates:
            if not isinstance(candidate, dict):
                continue
            language = str(candidate.get("lg") or "").strip().casefold()
            if language:
                counts[language] = counts.get(language, 0) + 1
                break
    return max(counts, key=counts.get) if counts else ""


def is_status_two(value: object) -> bool:
    return value == 2 or value == "2"


def is_last_result(value: object) -> bool:
    return value is True or value == "true" or value == 1 or value == "1"


class TranscriptAccumulator:
    """Merge incremental and WPGS replacement results into one transcript."""

    def __init__(self) -> None:
        self.pieces: dict[int, str] = {}
        self.candidate_pieces: dict[int, tuple[str, ...]] = {}
        self.language_pieces: dict[int, str] = {}

    def apply(self, result: dict[str, object]) -> bool:
        candidates = extract_candidates(result)
        piece = candidates[0] if candidates else ""
        sequence = int(result.get("sn", max(self.pieces, default=-1) + 1))
        replacement = result.get("rg") if result.get("pgs") == "rpl" else None
        if isinstance(replacement, list) and len(replacement) == 2:
            start, end = int(replacement[0]), int(replacement[1])
            for key in range(start, end + 1):
                self.pieces.pop(key, None)
                self.candidate_pieces.pop(key, None)
                self.language_pieces.pop(key, None)
        if piece:
            self.pieces[sequence] = piece
        if candidates and any(candidates):
            self.candidate_pieces[sequence] = tuple(
                candidate
                for index, candidate in enumerate(candidates)
                if candidate and candidate not in candidates[:index]
            )
        source_language = extract_language(result)
        if source_language:
            self.language_pieces[sequence] = source_language
        return bool(piece or replacement)

    @property
    def text(self) -> str:
        return "".join(self.pieces[key] for key in sorted(self.pieces)).strip()

    @property
    def detected_language(self) -> str:
        counts: dict[str, int] = {}
        for language in self.language_pieces.values():
            counts[language] = counts.get(language, 0) + 1
        return max(counts, key=counts.get) if counts else ""

    @property
    def alternatives(self) -> tuple[str, ...]:
        if not self.candidate_pieces:
            return (self.text,) if self.text else ()
        keys = sorted(self.candidate_pieces)
        count = max(len(self.candidate_pieces[key]) for key in keys)
        texts: list[str] = []
        for index in range(count):
            parts = []
            for key in keys:
                candidates = self.candidate_pieces[key]
                parts.append(candidates[index] if index < len(candidates) else candidates[0])
            text = "".join(parts).strip()
            if text and text not in texts:
                texts.append(text)
        top1 = self.text
        if top1 and top1 not in texts:
            texts.insert(0, top1)
        return tuple(texts)


__all__ = [
    "TranscriptAccumulator",
    "extract_candidates",
    "extract_language",
    "extract_text",
    "format_hotwords",
    "is_last_result",
    "is_status_two",
    "signed_url",
]
