import importlib.util
import json
from pathlib import Path

from heritage_explorer.dataset import load_dataset


ROOT = Path(__file__).resolve().parents[1]
V3_PATH = ROOT / "data" / "dataset" / "heritage_items.v3.jsonl"
REVIEW_PATH = ROOT / "data" / "dataset" / "heritage_items.v3.review.jsonl"
SCHEMA_KEYS = {"id", "title", "family", "category", "level", "address", "content"}
ADDRESS_KEYS = {"province", "city", "district", "detail"}


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_v3_jsonl_has_lean_unique_schema():
    kb = load_dataset()
    rows = _read_jsonl(V3_PATH)

    assert len(rows) == len(kb.items)
    assert len({row["id"] for row in rows}) == len(rows)

    for row in rows:
        assert set(row) == SCHEMA_KEYS
        assert set(row["address"]) == ADDRESS_KEYS
        assert row["id"].strip()
        assert row["title"].strip()
        assert row["category"].strip()
        assert row["level"].strip()
        assert row["address"]["province"].strip()
        assert row["address"]["city"].strip()
        assert row["content"].strip()
        assert "aliases" not in row
        assert "summary" not in row
        assert "search_text" not in row
        assert "source" not in row


def test_v3_jsonl_preserves_title_family_and_clean_address():
    rows = _read_jsonl(V3_PATH)
    by_title = {row["title"]: row for row in rows}

    assert by_title["滑县木版年画"]["family"] == "木版年画"
    assert by_title["滑县木版年画"]["level"] == "国家级"
    assert by_title["滑县木版年画"]["address"] == {
        "province": "河南省",
        "city": "安阳市",
        "district": "滑县",
        "detail": "",
    }
    assert by_title["陈氏太极拳"]["family"] == "太极拳"
    assert by_title["陈氏太极拳"]["level"] == "人类"
    assert by_title["罗卷戏（安阳市）"]["id"] != by_title["罗卷戏（南阳市）"]["id"]
    assert by_title["众度堂中医外科疗法"]["address"]["province"] == "河南省"


def test_v3_review_file_is_empty_when_dataset_is_clean():
    assert REVIEW_PATH.read_text(encoding="utf-8") == ""


def test_v3_builder_can_create_limited_records():
    spec = importlib.util.spec_from_file_location(
        "build_dataset_v3_jsonl",
        ROOT / "scripts" / "build_dataset_v3_jsonl.py",
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    records, review_rows = module.build_records(load_dataset(), limit=5)

    assert len(records) == 5
    assert review_rows == []
    assert all(set(record) == SCHEMA_KEYS for record in records)
