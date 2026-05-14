"""Session conversation memory. Max 5 rounds, in-memory store.

Each turn stores the user query, agent answer (truncated), and the heritage
items used by the answer.  The store is a module-level singleton — sessions
are lost on server restart.
"""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_ROUNDS = 5
ANSWER_TRUNCATE = 500  # chars to keep from each answer
ITEM_TEXT_TRUNCATE = 500  # chars to keep from long item fields


@dataclass
class Turn:
    query: str
    answer: str = ""
    item_titles: list[str] = field(default_factory=list)
    items_full: list[dict] = field(default_factory=list)


class ConversationStore:
    """In-memory session store. Not persisted across restarts."""

    def __init__(self) -> None:
        self._sessions: dict[str, list[Turn]] = {}

    def get(self, session_id: str) -> list[Turn]:
        return self._sessions.get(session_id, [])

    def is_first_turn(self, session_id: str) -> bool:
        return session_id not in self._sessions or not self._sessions[session_id]

    def turn_count(self, session_id: str) -> int:
        return len(self._sessions.get(session_id, []))

    def add_turn(
        self,
        session_id: str,
        query: str,
        answer: str,
        item_titles: list[str],
        items_full: list[dict] | None = None,
    ) -> None:
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        compact_items = [_compact_item_payload(item) for item in (items_full or [])]
        compact_items = [item for item in compact_items if item]
        self._sessions[session_id].append(
            Turn(
                query=query,
                answer=answer[:ANSWER_TRUNCATE],
                item_titles=list(item_titles),
                items_full=compact_items,
            )
        )
        # Enforce max rounds
        while len(self._sessions[session_id]) > MAX_ROUNDS:
            self._sessions[session_id].pop(0)

    def format_context(self, session_id: str) -> dict:
        """Build a context dict for the agent's planner / LLM.

        Returns a dict compatible with the existing `context` parameter
        in Agent.dispatch_stream, with extra 'history' field.
        """
        turns = self.get(session_id)
        if not turns:
            return {}

        last = turns[-1]
        # Collect all unique items across turns.  Keep title-only context for
        # older planner paths and full item context for the LLM decision path.
        all_titles: list[str] = []
        all_items_full: list[dict] = []
        seen_item_keys: set[str] = set()
        for t in turns:
            for title in t.item_titles:
                if title not in all_titles:
                    all_titles.append(title)
            for item in t.items_full:
                item_key = str(item.get("id") or item.get("title") or "").strip()
                if not item_key or item_key in seen_item_keys:
                    continue
                seen_item_keys.add(item_key)
                all_items_full.append(item)

        return {
            "question": last.query,
            "items": [{"title": t} for t in all_titles],
            "items_full": all_items_full,
            "answer": last.answer,
            "history": [
                {
                    "q": t.query,
                    "a": t.answer[:300],
                    "items": list(t.item_titles),
                    "items_full": list(t.items_full),
                }
                for t in turns
            ],
            "turn_count": len(turns),
            "session_id": session_id,
        }


# Module-level singleton
store = ConversationStore()


def _compact_item_payload(item: dict) -> dict:
    if not isinstance(item, dict):
        return {}

    compact: dict = {}
    for key in (
        "id",
        "title",
        "family",
        "category",
        "level",
        "province",
        "city",
        "district",
    ):
        value = str(item.get(key) or "").strip()
        if value:
            compact[key] = value

    for key in ("summary", "content", "features", "history", "cultural_value"):
        value = str(item.get(key) or "").strip()
        if value:
            compact[key] = value[:ITEM_TEXT_TRUNCATE]

    for key in ("display_forms", "suitable_scenarios"):
        value = item.get(key)
        if isinstance(value, (list, tuple)):
            compact[key] = [str(part) for part in value[:6] if str(part).strip()]

    return compact
