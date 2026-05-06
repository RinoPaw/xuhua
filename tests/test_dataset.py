from heritage_explorer.dataset import load_dataset
from heritage_explorer.search import (
    LEXICAL_RANK_WEIGHT,
    rank_hybrid,
    search_items,
    search_items_lexical,
    tokenize,
)


def test_dataset_loads():
    kb = load_dataset()
    assert len(kb.items) > 700
    assert any(category.name == "传统技艺" for category in kb.categories)


def test_search_finds_known_item():
    kb = load_dataset()
    results, total = search_items(kb, query="陈氏太极拳", limit=5)
    assert total > 0
    assert any("太极拳" in item.title for item in results)


def test_search_matches_homophone_query_with_pinyin():
    kb = load_dataset()
    results, total = search_items(kb, query="落山皮影戏", limit=5)

    assert total > 0
    assert results[0].title == "罗山皮影戏"


def test_lexical_search_matches_partial_homophone_query_with_pinyin():
    kb = load_dataset()
    results, total = search_items_lexical(kb, query="落山", limit=5)

    assert total > 0
    assert results[0].title == "罗山皮影戏"


def test_lexical_rank_weight_keeps_pinyin_visible_in_hybrid_results():
    assert LEXICAL_RANK_WEIGHT == 1.3


def test_search_falls_back_without_embedding_index(monkeypatch, tmp_path):
    from heritage_explorer import config

    monkeypatch.setattr(config, "SEARCH_USE_EMBEDDING", True)
    monkeypatch.setattr(config, "EMBEDDING_API_KEY", "test-key")
    monkeypatch.setattr(config, "EMBEDDING_INDEX_PATH", tmp_path / "missing.json")
    kb = load_dataset()
    results, total = search_items(kb, query="陈氏太极拳", limit=5)
    assert total > 0
    assert any("太极拳" in item.title for item in results)


def test_hybrid_search_uses_rank_fusion_for_fuzzy_queries(monkeypatch):
    from heritage_explorer import embeddings

    kb = load_dataset()
    target = next(item for item in kb.items if item.title == "少林功夫")
    lexical_decoy = next(item for item in kb.items if item.title == "木雕（嵩山木雕）")
    candidates = [lexical_decoy, target]

    def fake_embedding_scores(kb, query, candidates, client=None, min_score=None):
        assert min_score == 0.0
        return {target.id: 0.35}

    monkeypatch.setattr(embeddings, "embedding_scores", fake_embedding_scores)
    ranked = rank_hybrid(kb, candidates, "嵩山和尚练武那个", tokenize("嵩山和尚练武那个"))

    assert ranked[0][1].title == "少林功夫"


def test_hybrid_search_boosts_exact_title_matches(monkeypatch):
    from heritage_explorer import embeddings

    kb = load_dataset()
    target = next(item for item in kb.items if item.title == "朱仙镇木版年画")
    semantic_decoy = next(item for item in kb.items if item.title == "登封木版年画")
    candidates = [target, semantic_decoy]

    def fake_embedding_scores(kb, query, candidates, client=None, min_score=None):
        assert min_score == 0.0
        return {
            semantic_decoy.id: 0.92,
            target.id: 0.7,
        }

    monkeypatch.setattr(embeddings, "embedding_scores", fake_embedding_scores)
    ranked = rank_hybrid(kb, candidates, "朱仙镇木版年画", tokenize("朱仙镇木版年画"))

    assert ranked[0][1].title == "朱仙镇木版年画"
