from heritage_explorer.dataset import get_knowledge_base, get_soft_labels, get_structured_meta, load_dataset
from heritage_explorer.extractor import RuleExtractor


# ── RuleExtractor tests (extraction engine remains for build-time use) ──

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
    assert "其他" in meta.display_forms
    assert "展示馆传习所" in meta.display_forms
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


def test_rule_extractor_uses_henan_city_when_later_province_fields_conflict():
    kb = load_dataset()
    item = next(item for item in kb.items if item.title == "众度堂中医外科疗法")

    meta = RuleExtractor().extract(item)

    assert meta.province == "河南省"
    assert meta.city == "开封市"


# ── Unified dataset format tests ──

def test_heritage_item_has_baked_structured_fields():
    kb = get_knowledge_base()
    item = kb.items[0]
    assert item.level != ""
    assert item.province != ""
    assert item.city != ""
    assert isinstance(item.display_forms, tuple)
    assert isinstance(item.suitable_scenarios, tuple)
    assert isinstance(item.cultural_keywords, tuple)

    # All 805 items should have level filled
    filled = sum(1 for i in kb.items if i.level)
    assert filled == len(kb.items)


def test_get_structured_meta_from_item_fields():
    kb = get_knowledge_base()
    item = kb.get("h_dfc42ccd7c")
    assert item is not None

    meta = get_structured_meta(item.id)
    assert meta is not None
    assert meta.level == item.level
    assert meta.province == item.province
    assert meta.city == item.city
    assert meta.district == item.district
    assert meta.display_forms == item.display_forms
    assert meta.features == item.features
    assert meta.history == item.history
    assert meta.cultural_value == item.cultural_value


def test_get_soft_labels_from_item_fields():
    kb = get_knowledge_base()
    item = kb.get("h_dfc42ccd7c")
    assert item is not None

    labels = get_soft_labels(item.id)
    assert labels is not None
    assert labels.suitable_scenarios == item.suitable_scenarios
    assert labels.target_audience == item.target_audience
    assert labels.display_difficulty == item.display_difficulty
    assert labels.interaction_potential == item.interaction_potential
    assert labels.education_value == item.education_value
    assert labels.cultural_keywords == item.cultural_keywords


def test_get_structured_meta_returns_none_for_unknown_id():
    assert get_structured_meta("nonexistent") is None


def test_get_soft_labels_returns_none_for_unknown_id():
    assert get_soft_labels("nonexistent") is None
