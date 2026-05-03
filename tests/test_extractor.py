from heritage_explorer import dataset, extractor
from heritage_explorer.dataset import load_dataset
from heritage_explorer.extractor import (
    ExtractionCache,
    RuleExtractor,
    SoftLabels,
    StructuredMeta,
)


def test_rule_extractor_extracts_known_sample_fields():
    kb = load_dataset()
    item = kb.get("h_dfc42ccd7c")
    assert item is not None

    meta = RuleExtractor().extract(item)

    assert meta.level == "人类"
    assert meta.province == "河南省"
    assert meta.city == "南阳市"
    assert meta.district == "内乡县"
    assert "王晓杰" in meta.inheritors
    assert meta.coordinates == (111.855712, 33.054557)
    assert "其他" in meta.exhibition_types
    assert "展示馆传习所" in meta.exhibition_types
    assert meta.organization == "内乡县县衙博物馆"


def test_rule_extractor_parses_all_items_without_errors():
    kb = load_dataset()
    extractor = RuleExtractor()
    parsed_items = [extractor.extract(item) for item in kb.items]
    meta = extractor.extract_batch(kb.items)

    assert len(parsed_items) == len(kb.items)
    assert len(meta) == len({item.id for item in kb.items})
    assert sum(1 for item in parsed_items if item.level) == len(kb.items)
    assert sum(1 for item in parsed_items if item.province) / len(kb.items) > 0.95
    assert sum(1 for item in parsed_items if item.city) == len(kb.items)


def test_extraction_cache_round_trips_meta_and_labels(tmp_path):
    meta_path = tmp_path / "heritage_meta.json"
    labels_path = tmp_path / "heritage_labels.json"
    cache = ExtractionCache(meta_path=meta_path, labels_path=labels_path)

    meta = {
        "h_test": StructuredMeta(
            level="国家级",
            province="河南省",
            city="洛阳市",
            district="洛宁县",
            inheritors=("张三",),
            coordinates=(111.1, 34.2),
            exhibition_types=("展示馆传习所",),
            organization="洛宁县文化馆",
        )
    }
    labels = {
        "h_test": SoftLabels(
            suitable_scenarios=("校园展览",),
            target_audience=("青少年",),
            interactivity="高",
            cultural_keywords=("民俗", "教育"),
        )
    }

    cache.save(
        meta,
        labels,
        dataset_generated_at="2026-05-03T00:00:00",
        dataset_schema_version=1,
    )
    loaded_meta, loaded_labels = cache.load()

    assert loaded_meta == meta
    assert loaded_labels == labels
    assert not cache.is_stale(
        dataset_generated_at="2026-05-03T00:00:00",
        dataset_schema_version=1,
    )
    assert cache.is_stale(dataset_generated_at="2026-05-04T00:00:00")


def test_dataset_helpers_lazy_load_extraction_cache(monkeypatch, tmp_path):
    meta_path = tmp_path / "heritage_meta.json"
    labels_path = tmp_path / "heritage_labels.json"
    cache = ExtractionCache(meta_path=meta_path, labels_path=labels_path)
    cache.save(
        {"h_cached": StructuredMeta(level="省级", province="河南省")},
        {"h_cached": SoftLabels(educational_value="高")},
    )
    monkeypatch.setattr(extractor, "META_PATH", meta_path)
    monkeypatch.setattr(extractor, "LABELS_PATH", labels_path)

    dataset.clear_extraction_cache()

    assert dataset.get_structured_meta("h_cached") == StructuredMeta(
        level="省级",
        province="河南省",
    )
    assert dataset.get_soft_labels("h_cached") == SoftLabels(educational_value="高")

    dataset.clear_extraction_cache()
