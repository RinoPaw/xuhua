"""Deterministic retrieval smoke benchmark; never interpret as real-user accuracy.

Gold IDs and queries come from this same knowledge base. This tests exact-name
retrieval and region scoping, not unseen queries or human judged relevance.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server/src"))
from heritage_explorer.dataset import KnowledgeBase  # noqa: E402
from heritage_explorer.search import search_items  # noqa: E402


def choose_cases(kb: KnowledgeBase, per_category: int = 3):
    """Pick stable unique-title cases, balanced across available categories."""
    titles = Counter(item.title for item in kb.items)
    by_category = defaultdict(list)
    for item in kb.items:
        if (titles[item.title] == 1 and len(item.title) >= 2
                and item.province and item.id):
            by_category[item.category].append(item)
    cases = []
    for category in sorted(by_category):
        ordered = sorted(by_category[category],
                         key=lambda item: (hashlib.sha256(item.id.encode()).hexdigest(), item.id))
        cases.extend(ordered[:per_category])
    return cases


def evaluate(kb: KnowledgeBase, per_category: int = 3) -> dict:
    cases = choose_cases(kb, per_category)
    if not cases:
        raise ValueError("no unambiguous title cases available")
    measures = {}
    for mode in ("exact_title", "exact_title_with_province"):
        hits1 = hits5 = 0
        reciprocal_rank = 0.0
        durations = []
        failed = []
        for item in cases:
            kwargs = {"province": item.province} if mode == "exact_title_with_province" else {}
            started = time.perf_counter()
            results, _total = search_items(
                kb, query=item.title, limit=5, use_pinyin=False, **kwargs
            )
            durations.append((time.perf_counter() - started) * 1000)
            gold_rank = next((n for n, result in enumerate(results, 1)
                              if result.id == item.id), None)
            if gold_rank == 1:
                hits1 += 1
            if gold_rank is not None:
                hits5 += 1
                reciprocal_rank += 1 / gold_rank
            else:
                failed.append({"id": item.id, "category": item.category,
                               "title": item.title, "province": item.province})
        measures[mode] = {
            "cases": len(cases),
            "hit_at_1": hits1,
            "hit_at_5": hits5,
            "mrr_at_5": round(reciprocal_rank / len(cases), 4),
            "mean_duration_ms_on_this_runner": round(statistics.mean(durations), 2),
            "max_duration_ms_on_this_runner": round(max(durations), 2),
            "misses_sample": failed[:8],
        }
    return {
        "kind": "source_derived_retrieval_smoke_benchmark",
        "limitations": [
            "The same corpus supplies the query and the expected ID.",
            "This cannot estimate real-user relevance, answer accuracy or satisfaction.",
            "Timing is environment dependent; no latency SLA is inferred.",
            "Pinyin and free-form paraphrase cases are not covered.",
        ],
        "selection": {"per_category": per_category, "cases": len(cases),
                      "categories": dict(sorted(Counter(x.category for x in cases).items()))},
        "results": measures,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path,
                        default=ROOT / "data/processed/heritage_items.json")
    parser.add_argument("--per-category", type=int, default=3)
    args = parser.parse_args()
    if args.per_category < 1 or args.per_category > 20:
        parser.error("--per-category must be 1..20")
    payload = json.loads(args.dataset.read_text(encoding="utf-8"))
    print(json.dumps(evaluate(KnowledgeBase(payload), args.per_category),
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
