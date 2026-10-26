"""Regression checks for regional-subitem auditing and source rebuilds."""

from __future__ import annotations

import json
import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from audit_heritage import audit  # noqa: E402
from build_dataset import build_dataset  # noqa: E402


def make_files(tmp_path: Path) -> tuple[Path, Path]:
    source = tmp_path / "heritage_source.json"
    runtime = tmp_path / "heritage_items.json"
    source.write_text(json.dumps({
        "source": "fixture-name",
        "items": [
            {"id": "a", "title": "剪纸", "type": "传统美术",
             "unit": "河北省石家庄市", "content": "河北民间剪纸艺术。"},
            {"id": "b", "title": "剪纸", "type": "传统美术",
             "unit": "河南省郑州市", "content": "河南民间剪纸艺术。"},
        ],
    }, ensure_ascii=False), encoding="utf-8")
    runtime.write_text(json.dumps(build_dataset(source), ensure_ascii=False), encoding="utf-8")
    return source, runtime


def test_same_title_in_different_regions_keeps_two_subitems(tmp_path: Path) -> None:
    source, runtime = make_files(tmp_path)
    report = audit(source, runtime)
    assert report["unit"] == "regional_subitem"
    assert report["source"]["records"] == 2
    assert report["runtime"]["records"] == 2
    assert report["runtime"]["distinct_titles_not_project_count"] == 1
    assert report["runtime"]["repeated_title_groups"] == 1
    assert report["runtime"]["same_title_region_extra_records"] == 0
    assert report["runtime"]["by_category"] == {"传统美术": 2}
    assert report["rebuild"]["matches_committed"]
    assert report["passed"]


def test_duplicate_ids_and_wrong_category_counts_are_errors(tmp_path: Path) -> None:
    source, runtime = make_files(tmp_path)
    data = json.loads(runtime.read_text(encoding="utf-8"))
    data["items"][1]["id"] = data["items"][0]["id"]
    data["categories"][0]["item_count"] = 42
    runtime.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    report = audit(source, runtime)
    codes = {issue["code"] for issue in report["issues"]
             if issue["severity"] == "error"}
    assert {"duplicate_ids", "category_counts_mismatch"} <= codes
    assert not report["passed"]
    assert not report["rebuild"]["matches_committed"]
