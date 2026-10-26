"""Audit regional-subitem knowledge-base integrity and provenance offline."""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
from typing import Any

from build_dataset import build_dataset

ROOT = Path(__file__).resolve().parents[1]


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _source_items(source: Any) -> list:
    if isinstance(source, list):
        return source
    for name in ("items", "list", "records"):
        if isinstance(source.get(name), list):
            return source[name]
    raise ValueError("source has no record array")


def audit(source_path: Path, runtime_path: Path) -> dict:
    source = json.loads(source_path.read_text(encoding="utf-8"))
    runtime = json.loads(runtime_path.read_text(encoding="utf-8"))
    records = _source_items(source)
    items = runtime["items"]
    categories = runtime["categories"]
    if any(not isinstance(item, dict) for item in items):
        raise ValueError("invalid runtime record")
    declared = {str(c["name"]): int(c["item_count"]) for c in categories}
    actual = Counter(str(i.get("category") or "") for i in items)
    ids = Counter(str(i.get("id") or "") for i in items)
    titles = Counter(str(i.get("title") or "") for i in items)
    regional_keys = Counter(
        (i.get("title"), i.get("province"), i.get("city"), i.get("district"))
        for i in items
    )
    missing = {
        field: sum(not str(i.get(field) or "").strip() for i in items)
        for field in ("id", "title", "category", "summary", "content", "search_text",
                      "province", "city", "district", "level")
    }
    rebuilt = build_dataset(source_path)
    # Diagnostic samples only. These remain warnings until the original
    # administrative unit and project numbers have been verified.
    aligned_source = records if len(records) == len(items) else [{} for _ in items]
    missing_region_samples = [
        {
            "id": item.get("id"), "title": item.get("title"),
            "raw_unit": next((str(raw.get(k)) for k in
                              ("unit", "location", "address", "region", "province_name")
                              if isinstance(raw, dict) and raw.get(k)), ""),
            "project_num": raw.get("project_num") if isinstance(raw, dict) else None,
        }
        for item, raw in zip(items, aligned_source)
        if not str(item.get("province") or "").strip()
    ][:12]
    colliding = {key for key, count in regional_keys.items() if count > 1}
    duplicate_region_samples = [
        {"id": item.get("id"), "title": item.get("title"),
         "province": item.get("province"), "city": item.get("city"),
         "district": item.get("district")}
        for item in items
        if (item.get("title"), item.get("province"), item.get("city"),
            item.get("district")) in colliding
    ][:12]
    issues: list[dict] = []

    def flag(level: str, code: str, count: int | bool) -> None:
        if count:
            issues.append({"severity": level, "code": code, "count": int(count)})

    flag("error", "duplicate_ids", sum(n - 1 for key, n in ids.items() if key and n > 1))
    flag("error", "missing_ids", missing["id"])
    flag("error", "missing_titles", missing["title"])
    flag("error", "category_counts_mismatch", declared != actual)
    flag("error", "duplicate_category_names", len(declared) != len(categories))
    flag("warning", "source_rebuild_mismatch", rebuilt != runtime)
    flag("warning", "same_title_and_region", sum(n - 1 for n in regional_keys.values() if n > 1))
    flag("warning", "missing_content", missing["content"])
    flag("warning", "missing_province", missing["province"])
    metadata = source.get("meta", {}) if isinstance(source, dict) else {}
    if not isinstance(metadata, dict):
        metadata = {}
    provenance = {
        "source_name": str(source.get("source") or metadata.get("source") or "")
        if isinstance(source, dict) else "",
        "generated_at": str(metadata.get("generated_at") or ""),
        "raw_field_presence": {
            field: sum(bool(str(r.get(field) or "").strip()) for r in records
                       if isinstance(r, dict))
            for field in ("id", "project_id", "project_num", "rx_time",
                          "batch", "url", "source_url")
        },
    }
    return {
        "kind": "heritage_dataset_audit",
        "unit": "regional_subitem",
        "source": {"records": len(records), "sha256": _sha(source_path), **provenance},
        "runtime": {
            "records": len(items),
            "sha256": _sha(runtime_path),
            "categories": len(categories),
            "distinct_titles_not_project_count": len(titles),
            "repeated_title_groups": sum(n > 1 for n in titles.values()),
            "same_title_region_extra_records": sum(
                n - 1 for n in regional_keys.values() if n > 1
            ),
            "missing_fields": missing,
            "by_category": dict(sorted(actual.items())),
            "by_province": dict(sorted(Counter(
                str(i.get("province") or "").strip() or "(missing)" for i in items
            ).items())),
        },
        "rebuild": {
            "matches_committed": rebuilt == runtime,
            "different_item_positions": sum(
                x != y for x, y in zip(rebuilt["items"], items)
            ) + abs(len(rebuilt["items"]) - len(items)),
            "same_categories": rebuilt["categories"] == categories,
        },
        "diagnostics": {
            "missing_province_samples": missing_region_samples,
            "same_title_region_samples": duplicate_region_samples,
        },
        "issues": issues,
        "passed": not any(i["severity"] == "error" for i in issues),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "data/source/heritage_source.json")
    parser.add_argument("--runtime", type=Path, default=ROOT / "data/processed/heritage_items.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args()
    report = audit(args.source, args.runtime)
    result = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    print(result)
    if args.output:
        args.output.write_text(result, encoding="utf-8")
    if args.strict and not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
