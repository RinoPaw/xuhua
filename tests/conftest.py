import pytest

from heritage_explorer import config


@pytest.fixture(autouse=True)
def disable_embedding_search(monkeypatch):
    monkeypatch.setattr(config, "SEARCH_USE_EMBEDDING", False)
