"""Check independent labels, four-language coverage and retrieval metric boundaries."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from evaluate_labeled import ManifestError, evaluate, validate_manifest  # noqa: E402
from heritage_explorer.dataset import KnowledgeBase  # noqa: E402


def kb() -> KnowledgeBase:
    return KnowledgeBase({
        "categories": [
            {"id": 1, "name": "传统技艺", "item_count": 1},
            {"id": 2, "name": "传统舞蹈", "item_count": 1},
        ],
        "items": [
            {"id": "carve", "title": "木雕技艺", "category": "传统技艺",
             "province": "浙江省", "summary": "雕刻工艺"},
            {"id": "dance", "title": "龙舞", "category": "传统舞蹈",
             "province": "广东省", "summary": "舞龙表演"},
        ],
    })


def case(
    case_id: str, *, status: str = "draft", gold: list[str] | None = None,
    question: str = "请介绍木雕技艺。", language: str = "zh-CN",
) -> dict:
    data = {
        "id": case_id, "language": language, "task": "item_lookup",
        "question": question, "status": status, "expected_item_ids": gold or [],
    }
    if status == "approved":
        data["evidence"] = "local fixture record ID"
        data["review_note"] = "Reviewer checked fixture identity and query intent."
    return data


def test_drafts_produce_previews_but_no_accuracy() -> None:
    report = evaluate({"schema_version": 1, "cases": [case("draft")]}, kb())
    assert report["coverage"]["draft"] == 1
    assert report["coverage"]["approved"] == 0
    assert report["metrics"] is None
    assert report["cases"][0]["top5"][0]["id"] == "carve"
    assert report["cases"][0]["status"] == "draft"


def test_only_approved_cases_contribute_to_metrics() -> None:
    report = evaluate({"schema_version": 1, "cases": [
        case("hit", status="approved", gold=["carve"]),
        case("miss", status="approved", gold=["dance"], question="请介绍木雕技艺。"),
        case("unreviewed"),
    ]}, kb())
    assert report["coverage"]["total_cases"] == 3
    assert report["coverage"]["approved"] == 2
    assert report["metrics"]["hit_at_1"] == 0.5
    assert report["metrics"]["hit_at_5"] == 0.5
    assert report["metrics"]["recall_at_5"] == 0.5
    assert report["metrics"]["mrr_at_5"] == 0.5
    assert report["cases"][1]["missing_gold_ids"] == ["dance"]


@pytest.mark.parametrize(
    "broken",
    [
        {"schema_version": 3, "cases": [case("a")]},
        {"schema_version": 1, "cases": []},
        {"schema_version": 1, "cases": [case("repeat"), case("repeat")]},
        {"schema_version": 1, "cases": [case("a", gold=["carve"])]},
        {"schema_version": 1, "cases": [case("a", status="approved")]},
        {"schema_version": 1, "cases": [case("a", status="approved", gold=["unknown"])]},
        {"schema_version": 1, "cases": [case("a", language="fr-FR")]},
        {"schema_version": 1, "cases": [case("a", gold=["carve", "carve"])]},
    ],
)
def test_invalid_or_unreviewed_gold_never_slips_into_metrics(broken: dict) -> None:
    with pytest.raises(ManifestError):
        validate_manifest(broken, kb())


def test_approval_requires_traceable_review_note_and_evidence() -> None:
    a = case("no-evidence", status="approved", gold=["carve"])
    del a["evidence"]
    with pytest.raises(ManifestError):
        validate_manifest({"schema_version": 1, "cases": [a]}, kb())


def test_seed_manifest_is_balanced_and_does_not_claim_reviews() -> None:
    location = TOOLS.parent / "data/eval/retrieval_cases.json"
    manifest = json.loads(location.read_text(encoding="utf-8"))
    cases = validate_manifest(manifest, kb())
    assert len(cases) == 20
    assert {c["language"] for c in cases} == {"zh-CN", "en-US", "ja-JP", "ko-KR"}
    assert all(c["status"] == "draft" for c in cases)
    assert all(not c["expected_item_ids"] for c in cases)
