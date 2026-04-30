from heritage_explorer.dataset import load_dataset
from heritage_explorer.search import search_items


def test_dataset_loads():
    kb = load_dataset()
    assert len(kb.items) > 700
    assert any(category.name == "传统技艺" for category in kb.categories)


def test_search_finds_known_item():
    kb = load_dataset()
    results, total = search_items(kb, query="陈氏太极拳", limit=5)
    assert total > 0
    assert any("太极拳" in item.title for item in results)
