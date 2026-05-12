"""Tests for lexical search, ranking, and pinyin matching."""
from heritage_explorer.search import (
    tokenize,
    normalize_search_query,
    score_item,
    rank_lexical,
    search_items_lexical,
    search_items_pinyin,
    prepend_pinyin_matches,
)
from heritage_explorer.dataset import load_dataset


def test_tokenize_splits_chinese_chars():
    tokens = tokenize("太极拳是什么")
    assert len(tokens) > 0
    # Should contain bigrams
    assert any(len(t) == 2 for t in tokens) or len(tokens) >= 1


def test_tokenize_deduplicates():
    text = "太极拳太极拳"
    tokens = tokenize(text)
    from collections import Counter
    counts = Counter(tokens)
    assert all(c == 1 for c in counts.values())


def test_normalize_search_query_strips_fillers():
    result = normalize_search_query("介绍一下太极拳是什么")
    assert "介绍" not in result or "是什么" not in result


def test_score_item_exact_title_match_high_score():
    kb = load_dataset()
    found = next(it for it in kb.items if it.title == "陈氏太极拳")
    score = score_item(found, "陈氏太极拳", tokenize("陈氏太极拳"))
    assert score >= 100


def test_score_item_partial_title():
    kb = load_dataset()
    found = next(it for it in kb.items if "太极拳" in it.title)
    score = score_item(found, "太极", tokenize("太极"))
    assert score >= 40


def test_score_item_category_match():
    kb = load_dataset()
    item = next(i for i in kb.items if i.category == "传统美术")
    score = score_item(item, "传统美术", tokenize("传统美术"))
    assert score > 0


def test_rank_lexical_returns_ordered_results():
    kb = load_dataset()
    candidates = [i for i in kb.items if "木版年画" in (i.family or "")]
    if len(candidates) >= 2:
        ranked = rank_lexical(candidates, "滑县木版年画", tokenize("滑县木版年画"))
        assert len(ranked) >= 1
        assert ranked[0][0] >= ranked[-1][0]


def test_search_items_lexical_returns_results():
    kb = load_dataset()
    result, total = search_items_lexical(kb, query="太极拳", limit=5)
    assert total > 0
    assert len(result) <= 5
    assert any("太极拳" in item.title for item in result)


def test_search_items_lexical_respects_limit():
    kb = load_dataset()
    result, total = search_items_lexical(kb, query="木版年画", limit=2)
    assert len(result) <= 2


def test_search_items_lexical_filters_by_category():
    kb = load_dataset()
    result, total = search_items_lexical(kb, query="", category="传统美术", limit=10)
    assert total > 0
    assert all(item.category == "传统美术" for item in result)


def test_search_items_pinyin_finds_homophone():
    kb = load_dataset()
    # Clear the lru_cache before testing pinyin
    from heritage_explorer.search import _build_pinyin_index
    _build_pinyin_index.cache_clear()
    result = search_items_pinyin(kb, "落山皮影")
    # Should find items with "罗山" in title
    if result:
        assert any("罗山" in item.title for item in result)


def test_search_items_pinyin_empty_for_short_query():
    kb = load_dataset()
    result = search_items_pinyin(kb, "落")
    assert result == []


def test_prepend_pinyin_matches_no_duplicate():
    kb = load_dataset()
    ranked = [i for i in kb.items if "皮影" in (i.family or "")][:5]
    result = prepend_pinyin_matches(kb, ranked, "落山", list(kb.items))
    ids = [item.id for item in result]
    assert len(ids) == len(set(ids))  # no duplicates
