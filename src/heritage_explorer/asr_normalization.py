"""Conservative normalisation of Chinese ASR final transcripts.

The speech recogniser is good at producing fluent text, but can confuse one
character in a heritage item's name.  This module deliberately works on
small Chinese spans and only changes a span when the knowledge base and a
piece of conversation context make the intended item substantially more
likely than its alternatives.
"""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
import re
from typing import Any, Iterable
from weakref import WeakKeyDictionary

from pypinyin import lazy_pinyin


@dataclass(frozen=True)
class NormalizedSpan:
    """A changed span, with offsets into :attr:`NormalizedTranscript.raw_text`.

    ``end`` is exclusive, as with normal Python slices.
    """

    start: int
    end: int
    raw: str
    canonical: str
    score: float
    reason: str


@dataclass(frozen=True)
class NormalizedTranscript:
    raw_text: str
    canonical_text: str
    spans: tuple[NormalizedSpan, ...]


@dataclass(frozen=True)
class _Entry:
    canonical: str
    category: str
    forms: tuple[str, ...]
    pinyin: tuple[str, ...]


@dataclass(frozen=True)
class _Match:
    start: int
    end: int
    entry: _Entry
    score: float
    reason: str


_CHINESE_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")


def _items_from_kb(kb: Any) -> Iterable[Any]:
    """Accept ``KnowledgeBase`` as well as the small mapping fixtures used by callers."""

    if kb is None:
        return ()
    if isinstance(kb, dict):
        return kb.get("items", ())
    return getattr(kb, "items", ())


def _value(obj: Any, name: str, default: Any = "") -> Any:
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _as_forms(value: Any) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        return (value,) if value.strip() else ()
    if isinstance(value, dict):
        # A few exported datasets call the field ``aliases`` and store a
        # mapping of alias -> canonical title.
        return tuple(str(v) for v in value if str(v).strip())
    try:
        return tuple(str(v) for v in value if str(v).strip())
    except TypeError:
        return ()


def _entry_forms(item: Any, title: str) -> tuple[str, ...]:
    forms: list[str] = [title]
    # Do not treat display_forms as aliases: in the runtime dataset these are
    # presentation scenarios (e.g. "作品展示"), rather than names.
    for field in ("aliases", "alias", "alternate_names", "alternative_names", "names"):
        forms.extend(_as_forms(_value(item, field)))
    return tuple(dict.fromkeys(form for form in forms if form))


def _py(value: str) -> tuple[str, ...]:
    return tuple(lazy_pinyin(value, errors="default"))


def _category(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "")).lower()


def _edit_similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, left, right).ratio()


def _sequence_similarity(left: tuple[str, ...], right: tuple[str, ...]) -> float:
    return SequenceMatcher(None, left, right).ratio()


def _char_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    positional = sum(a == b for a, b in zip(left, right)) / max(len(left), len(right))
    return (positional + _edit_similarity(left, right)) / 2


class _Index:
    """A pinyin/length index; it avoids comparing every span to every item."""

    def __init__(self, kb: Any) -> None:
        entries: dict[tuple[str, str], _Entry] = {}
        for item in _items_from_kb(kb):
            title = str(_value(item, "title", "") or "").strip()
            if not title:
                continue
            category = str(_value(item, "category", "") or "").strip()
            forms = _entry_forms(item, title)
            # The title is the canonical output.  Names with no Chinese
            # characters are retained as exact spellings but are not fuzzy
            # candidates for a Chinese local span.
            entries[(title, category)] = _Entry(title, category, forms, _py(title))
        self.entries = tuple(entries.values())
        self.lengths = frozenset(len(form) for e in self.entries for form in e.forms if form)
        self.max_length = max(self.lengths, default=0)
        self.by_py: dict[tuple[str, ...], list[_Entry]] = {}
        self.by_prefix: dict[tuple[int, str], list[_Entry]] = {}
        self.by_first_char: dict[tuple[int, str], list[_Entry]] = {}
        for entry in self.entries:
            for form in entry.forms:
                if not form or not _CHINESE_RUN.fullmatch(form):
                    continue
                pinyin = _py(form)
                self.by_py.setdefault(pinyin, []).append(entry)
                self.by_prefix.setdefault((len(form), pinyin[0] if pinyin else ""), []).append(
                    entry
                )
                self.by_first_char.setdefault((len(form), form[0]), []).append(entry)
        self.exact_forms = frozenset(
            form for e in self.entries for form in e.forms if form and _CHINESE_RUN.fullmatch(form)
        )
        by_length: dict[int, set[str]] = {}
        for form in self.exact_forms:
            by_length.setdefault(len(form), set()).add(form)
        self.exact_by_length = {length: frozenset(forms) for length, forms in by_length.items()}

    def candidates(self, text: str) -> tuple[_Entry, ...]:
        """Return a small candidate set using pinyin buckets and fallbacks."""

        if not text or len(text) not in self.lengths:
            return ()
        pinyin = _py(text)
        found: dict[tuple[str, str], _Entry] = {}
        for entry in self.by_py.get(pinyin, ()):
            found[(entry.canonical, entry.category)] = entry
        # One changed syllable is common in Mandarin ASR.  The first syllable
        # and length are a cheap, useful bucket before edit scoring.
        if not found and pinyin:
            for entry in self.by_prefix.get((len(text), pinyin[0]), ()):
                found[(entry.canonical, entry.category)] = entry
        # Character bucket catches a non-homophonous first-character error.
        if not found:
            for entry in self.by_first_char.get((len(text), text[0]), ()):
                found[(entry.canonical, entry.category)] = entry
        return tuple(found.values())


_INDEX_CACHE: WeakKeyDictionary[Any, _Index] = WeakKeyDictionary()


def _get_index(kb: Any) -> _Index:
    """Reuse the expensive item index for a live knowledge-base object."""

    if isinstance(kb, dict) or kb is None:
        return _Index(kb)
    try:
        index = _INDEX_CACHE.get(kb)
    except (TypeError, ValueError):
        index = None
    if index is None:
        index = _Index(kb)
        try:
            _INDEX_CACHE[kb] = index
        except (TypeError, ValueError):
            pass
    return index


def prepare_asr_normalization(kb: Any) -> None:
    """Build the immutable catalogue index during application startup.

    The first construction scans the local catalogue and computes pinyin
    forms. Doing it once at startup keeps the first spoken turn on the same
    sub-millisecond path as later turns.
    """

    _get_index(kb)


def _protected_ranges(text: str, index: _Index) -> list[tuple[int, int]]:
    """Find exact forms in one text scan rather than searching each item."""

    ranges: list[tuple[int, int]] = []
    for start in range(len(text)):
        for length, forms_at_length in index.exact_by_length.items():
            end = start + length
            if end <= len(text) and text[start:end] in forms_at_length:
                ranges.append((start, end))
    ranges.sort(key=lambda value: (value[0], -(value[1] - value[0])))
    return ranges


def _overlaps(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
    return any(start < right and end > left for left, right in ranges)


def _signal(
    value: str, entry: _Entry, *, candidates: tuple[str, ...], recent: tuple[str, ...]
) -> tuple[float, list[str]]:
    """Context score and human-readable evidence for one candidate."""

    canonical = entry.canonical
    aliases = entry.forms
    signal = 0.0
    reasons: list[str] = []
    category = _category(value)
    if category and category == _category(entry.category):
        signal += 0.17
        reasons.append(f"category={value}")
    if any(any(form in c for form in aliases) or canonical in c for c in candidates):
        signal += 0.23
        reasons.append("asr-nbest")
    if any(any(form in r for form in aliases) or canonical in r for r in recent):
        signal += 0.11
        reasons.append("recent-item")
    return signal, reasons


def normalize_asr_final(
    raw_text: str,
    *,
    kb: Any,
    category: str = "",
    recent_items: Iterable[Any] = (),
    asr_candidates: Iterable[Any] = (),
    language: str = "zh",
) -> NormalizedTranscript:
    """Conservatively correct likely heritage-item name errors in a transcript.

    Only changed local Chinese spans are returned.  Exact titles and aliases
    are protected, and a fuzzy change requires category, recent-item, or n-best
    evidence plus a clear score margin over the next candidate.
    """

    text = str(raw_text or "")
    language_code = str(language or "").strip().casefold().replace("-", "_")
    if language_code not in {"zh", "cn", "zh_cn", "cn_cbm", "chinese"}:
        return NormalizedTranscript(text, text, ())
    index = _get_index(kb)
    if not text or not index.entries:
        return NormalizedTranscript(text, text, ())

    def as_texts(values: Iterable[Any]) -> tuple[str, ...]:
        if isinstance(values, str):
            values = (values,)
        result: list[str] = []
        for value in values or ():
            if isinstance(value, dict):
                value = value.get("text", value.get("title", ""))
            elif not isinstance(value, str):
                value = _value(value, "title", value)
            value = str(value or "").strip()
            if value:
                result.append(value)
        return tuple(result)

    recent = as_texts(recent_items)
    nbest = as_texts(asr_candidates)
    protected = _protected_ranges(text, index)
    matches: list[_Match] = []

    for run in _CHINESE_RUN.finditer(text):
        start, end = run.span()
        run_text = run.group()
        for length in index.lengths:
            if length < 2 or length > len(run_text):
                continue
            for offset in range(0, len(run_text) - length + 1):
                span_start = start + offset
                span_end = span_start + length
                if _overlaps(span_start, span_end, protected):
                    continue
                raw = run_text[offset : offset + length]
                candidates = index.candidates(raw)
                if not candidates:
                    continue
                ranked: list[tuple[float, _Entry, list[str], float, float]] = []
                raw_py = _py(raw)
                for entry in candidates:
                    best_form = max(
                        entry.forms,
                        key=lambda form: (
                            _char_similarity(raw, form) + _sequence_similarity(raw_py, _py(form))
                        ),
                    )
                    char_score = _char_similarity(raw, best_form)
                    py_score = _sequence_similarity(raw_py, _py(best_form))
                    context, reasons = _signal(category, entry, candidates=nbest, recent=recent)
                    base = 0.48 * py_score + 0.52 * char_score
                    score = min(1.0, base + context)
                    ranked.append((score, entry, reasons, py_score, char_score))
                ranked.sort(key=lambda value: value[0], reverse=True)
                best_score, best_entry, reasons, best_py_score, best_char_score = ranked[0]
                second_score = ranked[1][0] if len(ranked) > 1 else 0.0
                has_context = bool(reasons)
                # Without context, fuzzy changes are intentionally disabled;
                # this is what keeps ordinary words such as “苏醒” untouched.
                if (
                    not has_context
                    or best_py_score < 0.72
                    or best_char_score < 0.45
                    or best_score < 0.69
                    or best_score - second_score < 0.075
                ):
                    continue
                if raw == best_entry.canonical or raw in best_entry.forms:
                    continue
                reason = "; ".join(reasons) or "constrained-fuzzy"
                reason += f"; pinyin/char={best_score:.2f}; margin={best_score - second_score:.2f}"
                matches.append(_Match(span_start, span_end, best_entry, best_score, reason))

    # Prefer longer and more confident candidates, then retain non-overlap in
    # source order.  This also makes duplicate KB rows harmless.
    matches.sort(key=lambda m: (m.start, -(m.end - m.start), -m.score))
    chosen: list[_Match] = []
    for candidate in matches:
        if any(candidate.start < old.end and candidate.end > old.start for old in chosen):
            continue
        chosen.append(candidate)
    chosen.sort(key=lambda m: m.start)

    if not chosen:
        return NormalizedTranscript(text, text, ())
    output: list[str] = []
    spans: list[NormalizedSpan] = []
    cursor = 0
    for match in chosen:
        output.append(text[cursor : match.start])
        raw = text[match.start : match.end]
        output.append(match.entry.canonical)
        spans.append(
            NormalizedSpan(
                match.start, match.end, raw, match.entry.canonical, match.score, match.reason
            )
        )
        cursor = match.end
    output.append(text[cursor:])
    return NormalizedTranscript(text, "".join(output), tuple(spans))


__all__ = [
    "NormalizedSpan",
    "NormalizedTranscript",
    "normalize_asr_final",
    "prepare_asr_normalization",
]
