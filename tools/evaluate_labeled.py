"""Evaluate independent, human-reviewed retrieval questions against Xuhua.

Draft cases produce retrieval previews but NEVER contribute to accuracy scores.
Only cases with status="approved", explicit source-backed IDs, and review notes
enter Hit@K / Recall@K / MRR@K. No LLM or external APIs are called.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server/src"))

from heritage_explorer.dataset import KnowledgeBase  # noqa: E402
from heritage_explorer.language import LANGUAGE_PROFILES, detect_locale  # noqa: E402
from heritage_explorer.retrieval_policy import (  # noqa: E402
    candidate_limit,
    localized_search_query,
    retrieval_basis,
)
from heritage_explorer.search import search_items  # noqa: E402

DEFAULT_CASES = ROOT / "data/eval/retrieval_cases.json"
DEFAULT_DATASET = ROOT / "data/processed/heritage_items.json"
TASKS = frozenset({
    "item_lookup", "region_lookup", "category_browse", "education_task",
    "multilingual_lookup",
})
STATUSES = frozenset({"draft", "approved"})


class ManifestError(ValueError):
    """Malformed or unsupported human-label manifest."""


class _SearchContext:
    def __init__(self, kb: KnowledgeBase):
        self.knowledge_base = kb


def validate_manifest(manifest: Any, kb: KnowledgeBase) -> list[dict[str, Any]]:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ManifestError("schema_version must be 1")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ManifestError("cases must be a nonempty array")
    known_ids = {item.id for item in kb.items}
    seen = set()
    validated: list[dict[str, Any]] = []
    for index, case in enumerate(cases, start=1):
        if not isinstance(case, dict):
            raise ManifestError(f"case {index}: expected an object")
        name = case.get("id")
        if not isinstance(name, str) or not name.strip() or name in seen:
            raise ManifestError(f"case {index}: id is empty or repeated")
        seen.add(name)
        question = case.get("question")
        if not isinstance(question, str) or not question.strip():
            raise ManifestError(f"{name}: question must be nonempty")
        language = case.get("language")
        if not isinstance(language, str) or language not in LANGUAGE_PROFILES:
            raise ManifestError(f"{name}: unsupported language {language!r}")
        if not isinstance(case.get("task"), str) or case["task"] not in TASKS:
            raise ManifestError(f"{name}: unsupported task")
        status = case.get("status")
        if not isinstance(status, str) or status not in STATUSES:
            raise ManifestError(f"{name}: status must be draft or approved")
        category = case.get("category", "")
        if not isinstance(category, str):
            raise ManifestError(f"{name}: category must be a string")
        gold = case.get("expected_item_ids", [])
        if not isinstance(gold, list) or any(
            not isinstance(value, str) or not value.strip() for value in gold
        ) or len(gold) != len(set(gold)):
            raise ManifestError(f"{name}: expected_item_ids must be unique strings")
        if status == "approved":
            if not gold:
                raise ManifestError(f"{name}: approved case needs verified item IDs")
            if not str(case.get("review_note") or "").strip():
                raise ManifestError(f"{name}: approved case needs review_note")
            if not str(case.get("evidence") or "").strip():
                raise ManifestError(f"{name}: approved case needs evidence")
            unknown = sorted(set(gold) - known_ids)
            if unknown:
                raise ManifestError(f"{name}: gold ID is absent from the knowledge base: {unknown}")
        elif gold:
            raise ManifestError(f"{name}: draft cannot contain gold IDs")
        validated.append(case)
    return validated


def _preview(kb: KnowledgeBase, context: _SearchContext, case: dict[str, Any]) -> dict:
    question = case["question"].strip()
    locale = detect_locale(question, hint=case["language"])
    category = case.get("category", "")
    basis = retrieval_basis(context, question, category, locale=locale)
    query = localized_search_query(question, locale, basis)
    count = 12 if basis == "multilingual_catalogue" else candidate_limit(
        context, question, category, 12
    )
    started = time.perf_counter()
    if basis in {"none", "conversation_reply"}:
        results = []
        total = 0
    else:
        results, total = search_items(
            kb, query=query, category=category, limit=max(5, count),
            use_pinyin=True,
        )
    duration = round((time.perf_counter() - started) * 1000, 2)
    return {
        "id": case["id"],
        "task": case["task"],
        "declared_language": case["language"],
        "detected_locale": locale,
        "status": case["status"],
        "question": question,
        "retrieval_basis": basis,
        "retrieval_query": query,
        "total_candidates": total,
        "duration_ms_on_this_runner": duration,
        "top5": [
            {"id": item.id, "title": item.title, "province": item.province,
             "category": item.category}
            for item in results[:5]
        ],
    }


def evaluate(manifest: Any, kb: KnowledgeBase) -> dict[str, Any]:
    cases = validate_manifest(manifest, kb)
    context = _SearchContext(kb)
    previews = []
    scored = []
    for case in cases:
        preview = _preview(kb, context, case)
        if case["status"] == "approved":
            gold = set(case["expected_item_ids"])
            predicted = [item["id"] for item in preview["top5"]]
            first = next((rank for rank, item_id in enumerate(predicted, 1)
                          if item_id in gold), None)
            preview["gold_count"] = len(gold)
            preview["found_count_at_5"] = len(gold.intersection(predicted))
            preview["first_relevant_rank"] = first
            preview["missing_gold_ids"] = sorted(gold.difference(predicted))
            scored.append(preview)
        previews.append(preview)

    n = len(scored)
    metrics = None
    if n:
        metrics = {
            "reviewed_cases": n,
            "hit_at_1": round(sum(p["first_relevant_rank"] == 1 for p in scored) / n, 4),
            "hit_at_5": round(sum(p["first_relevant_rank"] is not None for p in scored) / n, 4),
            "recall_at_5": round(sum(
                p["found_count_at_5"] / p["gold_count"] for p in scored
            ) / n, 4),
            "mrr_at_5": round(sum(
                1 / p["first_relevant_rank"] if p["first_relevant_rank"] else 0
                for p in scored
            ) / n, 4),
        }
    return {
        "kind": "independently_labeled_retrieval_evaluation",
        "label_policy": "Only manually approved cases with evidence and valid gold IDs are scored.",
        "limitations": [
            "Draft prompts have no ground truth and contribute no accuracy scores.",
            "Metrics describe retrieval only, not LLM answer accuracy, ASR, TTS, or user satisfaction.",
            "The sample is not representative of real users until independently recruited and reviewed.",
            "Timing reflects this specific runner and is not an application latency SLA.",
        ],
        "coverage": {
            "total_cases": len(cases),
            "approved": n,
            "draft": len(cases) - n,
            "by_language": dict(sorted(Counter(c["language"] for c in cases).items())),
            "approved_by_language": dict(sorted(Counter(
                c["language"] for c in cases if c["status"] == "approved"
            ).items())),
        },
        "metrics": metrics,
        "cases": previews,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--output", type=Path, help="write complete evaluation JSON")
    parser.add_argument("--summary", action="store_true", help="show coverage and metrics only")
    parser.add_argument("--require-approved", action="store_true",
                        help="fail when there are no independently approved cases")
    args = parser.parse_args()
    kb = KnowledgeBase(json.loads(args.dataset.read_text(encoding="utf-8")))
    report = evaluate(json.loads(args.cases.read_text(encoding="utf-8")), kb)
    report["inputs"] = {
        "dataset_sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        "cases_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    visible = (
        {key: report[key] for key in ("kind", "label_policy", "coverage", "metrics", "inputs")}
        if args.summary else report
    )
    print(json.dumps(visible, ensure_ascii=False, indent=2))
    if args.require_approved and report["coverage"]["approved"] == 0:
        raise SystemExit("No approved cases: independent evaluation not yet available")


if __name__ == "__main__":
    main()
