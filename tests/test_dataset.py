from heritage_explorer.dataset import item_to_dict, load_dataset
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


def test_dataset_items_have_direct_title_and_family_fields():
    kb = load_dataset()

    assert all(hasattr(item, "title") for item in kb.items)
    assert all(hasattr(item, "family") for item in kb.items)
    assert not any(hasattr(item, "aliases") for item in kb.items)


def test_dataset_item_ids_are_unique():
    kb = load_dataset()

    assert len({item.id for item in kb.items}) == len(kb.items)


def test_item_payload_normalizes_title_and_family():
    kb = load_dataset()
    item = next(item for item in kb.items if item.title == "滑县木版年画")
    payload = item_to_dict(item)

    assert payload["title"] == "滑县木版年画"
    assert payload["family"] == "木版年画"
    assert "aliases" not in payload
    assert "official_title" not in payload
    assert "display_title" not in payload
    assert "title_family" not in payload


def test_direct_woodblock_titles_are_grouped_by_family():
    kb = load_dataset()
    item = next(item for item in kb.items if item.title == "朱仙镇木版年画")
    payload = item_to_dict(item)

    assert payload["title"] == "朱仙镇木版年画"
    assert payload["family"] == "木版年画"


def test_common_woodblock_typo_is_corrected_in_public_title():
    kb = load_dataset()
    item = next(item for item in kb.items if item.title == "内黄李新张木版年画")
    payload = item_to_dict(item)

    assert payload["title"] == "内黄李新张木版年画"
    assert payload["family"] == "木版年画"


def test_ihchina_parenthetical_titles_are_normalized_to_title_and_family():
    kb = load_dataset()

    sichuan_items = [item for item in kb.items if item.title == "四川皮影戏"]
    assert sichuan_items
    assert all(item.family == "皮影戏" for item in sichuan_items)
    assert all(item.category == "传统戏剧" for item in sichuan_items)
    assert all(item.level == "国家级" for item in sichuan_items)

    hubei_titles = {item.title for item in kb.items if item.province == "湖北省" and item.family == "皮影戏"}
    assert {"江汉平原皮影戏", "云梦皮影戏"} <= hubei_titles


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


def test_search_prioritizes_region_plus_family_over_pinyin_noise():
    kb = load_dataset()
    for query in ("湖北皮影", "湖北皮影戏"):
        results, total = search_items_lexical(kb, query=query, limit=5)

        assert total > 0
        assert results[0].province == "湖北省"
        assert results[0].family == "皮影戏"
        assert results[0].title in {"江汉平原皮影戏", "云梦皮影戏"}
        assert results[0].title != "蒙古族皮艺"


def test_lexical_rank_weight_keeps_pinyin_visible_in_hybrid_results():
    assert LEXICAL_RANK_WEIGHT == 1.3


def test_search_keeps_exact_title_first_inside_natural_language_request():
    kb = load_dataset()
    results, total = search_items_lexical(kb, query="给朱仙镇木版年画生成讲解词", limit=5)

    assert total > 0
    assert results[0].title == "朱仙镇木版年画"


def test_hybrid_search_keeps_exact_title_before_family_pinyin_matches():
    kb = load_dataset()
    results, total = search_items(kb, query="给朱仙镇木版年画生成讲解词", limit=5)

    assert total > 0
    assert results[0].title == "朱仙镇木版年画"


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
    lexical_decoy = next(item for item in kb.items if item.title == "嵩山木雕")
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
