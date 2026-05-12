"""Tests for embedding index, normalization, and cosine similarity."""
import math
from heritage_explorer.embeddings import (
    normalize_vector,
    dot,
    build_embedding_text,
)
from heritage_explorer.dataset import load_dataset


def test_normalize_vector_unit_length():
    v = [3.0, 4.0]
    n = normalize_vector(v)
    assert math.isclose(n[0], 0.6)
    assert math.isclose(n[1], 0.8)


def test_normalize_vector_empty_for_zero():
    assert normalize_vector([0.0, 0.0, 0.0]) == []


def test_normalize_vector_empty_for_single():
    n = normalize_vector([5.0])
    assert len(n) == 1
    assert math.isclose(n[0], 1.0)


def test_dot_product():
    assert dot([1.0, 2.0, 3.0], [4.0, 5.0, 6.0]) == 32.0


def test_dot_product_orthogonal():
    assert math.isclose(dot([1.0, 0.0], [0.0, 1.0]), 0.0)


def test_build_embedding_text_includes_title_and_category():
    kb = load_dataset()
    item = kb.items[0]
    text = build_embedding_text(item)
    assert item.title in text
    assert item.category in text


def test_build_embedding_text_respects_max_chars():
    kb = load_dataset()
    item = kb.items[0]
    text = build_embedding_text(item, max_chars=50)
    assert len(text) <= 50
