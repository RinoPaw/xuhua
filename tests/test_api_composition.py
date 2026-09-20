from __future__ import annotations

import pytest

from heritage_explorer.api import create_app
from heritage_explorer.dataset import KnowledgeBase
from heritage_explorer.models import SearchResponse
from heritage_explorer.sessions import SessionStore


class StubSearch:
    def __init__(self) -> None:
        self.knowledge_base = KnowledgeBase({"items": [], "categories": []})

    def search(self, *_args: object, **_kwargs: object) -> SearchResponse:
        return SearchResponse((), 0)


class StubAssistant:
    def __init__(self, search: StubSearch, sessions: SessionStore) -> None:
        self.search = search
        self.sessions = sessions


def test_app_uses_services_owned_by_assistant() -> None:
    search = StubSearch()
    sessions = SessionStore()
    assistant = StubAssistant(search, sessions)

    app = create_app(assistant=assistant)  # type: ignore[arg-type]

    assert app is not None


def test_app_rejects_second_search_owner() -> None:
    assistant = StubAssistant(StubSearch(), SessionStore())

    with pytest.raises(ValueError, match="assistant-owned search"):
        create_app(assistant=assistant, search=StubSearch())  # type: ignore[arg-type]


def test_app_rejects_second_session_owner() -> None:
    assistant = StubAssistant(StubSearch(), SessionStore())

    with pytest.raises(ValueError, match="assistant-owned session"):
        create_app(assistant=assistant, sessions=SessionStore())  # type: ignore[arg-type]
