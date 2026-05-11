"""Build a normalized dataset from the old panda_mudan data files."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def normalize_title(value: str) -> str:
    return re.sub(r"\s+", "", value.replace("\u00a0", " ")).strip()


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip()


TITLE_FAMILY_SUFFIXES = ("木版年画",)
PLACE_QUALIFIER_RE = re.compile(r"^[\u4e00-\u9fff]{2,8}(?:省|市|县|区|州|旗|盟)$")


def split_parenthetical_title(title: str) -> tuple[str, str]:
    match = re.match(r"^(.+?)[（(](.+)[）)]$", normalize_text(title))
    if not match:
        return "", ""
    family = normalize_text(match.group(1))
    variant = normalize_text(match.group(2))
    if PLACE_QUALIFIER_RE.match(variant):
        return "", ""
    if not family or not variant or family == variant:
        return "", ""
    return family, variant


def public_title_parts(title: str) -> tuple[str, str]:
    family, variant = split_parenthetical_title(title)
    if family and variant:
        return variant, family

    if "木板年画" in title:
        return title.replace("木板年画", "木版年画"), "木版年画"

    for suffix in TITLE_FAMILY_SUFFIXES:
        if title.endswith(suffix) and title != suffix:
            return title, suffix

    return title, ""


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return data


def load_categories(source_root: Path) -> tuple[dict[int, str], dict[str, list[str]]]:
    path = source_root / "src" / "mudan" / "data" / "categories.py"
    spec = importlib.util.spec_from_file_location("_legacy_categories", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot import categories from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.HERITAGE_CATEGORY_MAP, module.HERITAGE_CATEGORY_ITEMS


def build_category_lookup(category_items: dict[str, list[str]]) -> dict[str, set[str]]:
    lookup: dict[str, set[str]] = defaultdict(set)
    for category, titles in category_items.items():
        for title in titles:
            normalized = normalize_title(title)
            if normalized:
                lookup[normalized].add(category)
    return lookup


def stable_id(title: str) -> str:
    digest = hashlib.sha1(title.encode("utf-8")).hexdigest()[:10]
    return f"h_{digest}"


def make_unique_ids(items: list[dict[str, Any]]) -> None:
    """Keep title-based ids stable unless an old source title collides."""
    seen: set[str] = set()
    for item in items:
        item_id = str(item["id"])
        if item_id not in seen:
            seen.add(item_id)
            continue

        source = item.get("source") or {}
        seed_parts = [
            item_id,
            str(item.get("title") or ""),
            str(source.get("legacy_order") or ""),
            str(item.get("content") or "")[:160],
        ]
        counter = 1
        while True:
            candidate = stable_id("|".join(seed_parts + [str(counter)]))
            if candidate not in seen:
                item["id"] = candidate
                seen.add(candidate)
                break
            counter += 1


def build_dataset(source_root: Path) -> dict[str, Any]:
    faiss_data_path = source_root / "data" / "faiss_data" / "faiss_data.json"
    summary_path = source_root / "data" / "faiss_data" / "summary" / "summary_final.json"

    faiss_data = load_json(faiss_data_path)
    summaries = load_json(summary_path)
    category_map, category_items = load_categories(source_root)
    category_lookup = build_category_lookup(category_items)

    items = []
    category_counter: Counter[str] = Counter()

    for order, (title, content) in enumerate(faiss_data.items(), start=1):
        raw_title = normalize_text(title)
        clean_title, family = public_title_parts(raw_title)
        normalized_title = normalize_title(raw_title)
        category_candidates = sorted(category_lookup.get(normalized_title, []))
        category = category_candidates[0] if category_candidates else "未分类"
        summary = normalize_text(str(summaries.get(title) or summaries.get(raw_title) or ""))
        clean_content = normalize_text(str(content))

        category_counter[category] += 1
        search_parts = [clean_title, family, category, summary, clean_content]

        items.append({
            "id": stable_id(raw_title),
            "title": clean_title,
            "family": family,
            "category": category,
            "summary": summary,
            "content": clean_content,
            "search_text": " ".join(part for part in search_parts if part),
            "source": {
                "legacy_order": order,
                "files": [
                    "data/faiss_data/faiss_data.json",
                    "data/faiss_data/summary/summary_final.json",
                    "src/mudan/data/categories.py",
                ],
                "category_candidates": category_candidates,
            },
        })

    make_unique_ids(items)

    categories = [
        {
            "id": int(category_id),
            "name": category_name,
            "item_count": int(category_counter.get(category_name, 0)),
        }
        for category_id, category_name in category_map.items()
    ]
    if category_counter.get("未分类", 0):
        categories.append({
            "id": 0,
            "name": "未分类",
            "item_count": int(category_counter["未分类"]),
        })

    return {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "project": "panda_mudan",
            "root": str(source_root),
            "item_count": len(items),
        },
        "categories": categories,
        "items": items,
    }


def parse_args() -> argparse.Namespace:
    default_source = Path(__file__).resolve().parents[2] / "panda_mudan"
    default_output = Path(__file__).resolve().parents[1] / "data" / "processed" / "heritage_items.json"
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-root", type=Path, default=default_source)
    parser.add_argument("--output", type=Path, default=default_output)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    payload = build_dataset(args.source_root.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"Wrote {len(payload['items'])} items to {args.output}")


if __name__ == "__main__":
    main()
