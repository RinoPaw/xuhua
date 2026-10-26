from __future__ import annotations

import sys
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from evaluate_retrieval import choose_cases, evaluate  # noqa: E402
from heritage_explorer.dataset import KnowledgeBase  # noqa: E402


def kb() -> KnowledgeBase:
    return KnowledgeBase({"items": [
        {"id": "carve", "title": "木雕技艺", "category": "传统技艺",
         "province": "浙江省", "content": "传统手工雕刻"},
        {"id": "dance", "title": "龙舞", "category": "传统舞蹈",
         "province": "广东省", "content": "节庆舞龙"},
        {"id": "repeat1", "title": "剪纸", "category": "传统美术",
         "province": "河北省"},
        {"id": "repeat2", "title": "剪纸", "category": "传统美术",
         "province": "河南省"},
    ]})


def test_balanced_gold_uses_unique_titles_and_retains_regional_duplicates() -> None:
    cases = choose_cases(kb(), 1)
    assert {item.id for item in cases} == {"carve", "dance"}
    assert all(item.title != "剪纸" for item in cases)


def test_source_derived_benchmark_reports_hits_but_claims_no_user_accuracy() -> None:
    report = evaluate(kb(), 1)
    assert report["selection"]["cases"] == 2
    assert report["results"]["exact_title"]["hit_at_5"] == 2
    assert report["results"]["exact_title_with_province"]["hit_at_5"] == 2
    assert report["limitations"]
    assert report["kind"] == "source_derived_retrieval_smoke_benchmark"
