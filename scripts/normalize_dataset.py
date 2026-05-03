"""Normalize heritage_items.json: clean titles and fix category errors."""

from __future__ import annotations

import argparse
import json
import re
from copy import deepcopy
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "processed" / "heritage_items.json"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "heritage_items.json"

# Known category overrides: title_pattern → correct_category
CATEGORY_FIXES: dict[str, str] = {
    "中国皮影戏": "传统戏剧",
}

# Items to skip (bad data)
SKIP_IDS: set[str] = set()


def normalize_title(title: str) -> tuple[str, str]:
    """Clean bracket-formatted titles.

    Returns (clean_title, extra_alias).
    "皮影戏[皮影戏]" → ("皮影戏", "")
    "泥塑[淮滨泥塑（小叫吹）]" → ("淮滨泥塑（小叫吹）", "泥塑")
    "竹马舞[三家村竹马舞]" → ("三家村竹马舞", "竹马舞")
    """
    match = re.match(r"^(.+?)\[(.+)\]$", title)
    if not match:
        return title, ""

    generic = match.group(1).strip()
    specific = match.group(2).strip()

    # Normalize nested parens in specific part
    specific = specific.replace("（", "(").replace("）", ")")

    if specific == generic or not specific:
        return generic, ""
    if specific.endswith(")"):
        return specific, generic
    return specific, generic


def _extract_city_from_content(content: str) -> str:
    """Extract city name from content field for title disambiguation."""
    match = re.search(r"(?:城市|地区)[:：]\s*(\S{2,6}(?:市|县|区))", content)
    if match:
        return match.group(1)
    match = re.search(r"报道地区[:：]\s*(\S+?)(?:市|县|区)", content)
    if match:
        return match.group(1)
    return ""


def normalize_item(item: dict[str, Any]) -> dict[str, Any] | None:
    if item["id"] in SKIP_IDS:
        return None

    item = deepcopy(item)
    new_title, extra_alias = normalize_title(item["title"])
    old_title = item["title"]

    if new_title != old_title:
        item["title"] = new_title
        aliases = list(item.get("aliases") or [])
        if extra_alias and extra_alias not in aliases:
            aliases.append(extra_alias)
        if old_title not in aliases:
            aliases.append(old_title)
        item["aliases"] = aliases

        old_search = item.get("search_text", "")
        item["search_text"] = old_search.replace(old_title, new_title, 1)

    if new_title in CATEGORY_FIXES:
        item["category"] = CATEGORY_FIXES[new_title]

    return item


def _disambiguate_duplicates(items: list[dict[str, Any]]) -> list[dict]:
    """Add city suffix to items with duplicate titles."""
    changes: list[dict] = []
    title_groups: dict[str, list[int]] = {}
    for idx, item in enumerate(items):
        title_groups.setdefault(item["title"], []).append(idx)

    for title, indices in title_groups.items():
        if len(indices) <= 1:
            continue
        for idx in indices:
            item = items[idx]
            city = _extract_city_from_content(item.get("content", ""))
            if city and city not in item["title"]:
                old_title = item["title"]
                new_title = f"{title}（{city}）"
                if item.get("aliases"):
                    item["aliases"] = list(item["aliases"]) + [old_title]
                item["title"] = new_title
                changes.append({
                    "id": item["id"],
                    "old_title": old_title,
                    "new_title": new_title,
                    "action": "disambiguated",
                })
    return changes


def normalize_dataset(input_path: Path, output_path: Path, *, dry_run: bool = False) -> dict:
    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    original_count = len(data["items"])
    normalized: list[dict[str, Any]] = []
    changes: list[dict] = []

    for item in data["items"]:
        result = normalize_item(item)
        if result is None:
            changes.append({"id": item["id"], "title": item["title"], "action": "removed"})
            continue
        if result["title"] != item["title"]:
            changes.append({
                "id": item["id"],
                "old_title": item["title"],
                "new_title": result["title"],
                "new_aliases": result.get("aliases", []),
                "action": "renamed",
            })
        if result["category"] != item["category"]:
            changes.append({
                "id": item["id"],
                "title": result["title"],
                "old_category": item["category"],
                "new_category": result["category"],
                "action": "recategorized",
            })
        normalized.append(result)

    data["items"] = normalized

    # Disambiguate identical titles
    disambiguate_changes = _disambiguate_duplicates(data["items"])
    if disambiguate_changes:
        for dc in disambiguate_changes:
            changes.append(dc)

    # Update category counts
    from collections import Counter
    cat_counter = Counter(item["category"] for item in normalized)
    for cat in data["categories"]:
        cat["item_count"] = cat_counter.get(cat["name"], 0)

    if not dry_run:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with output_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")

    return {
        "original_count": original_count,
        "final_count": len(normalized),
        "changes": changes,
        "change_count": len(changes),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Normalize heritage_items.json")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--dry-run", action="store_true", help="Show changes without writing")
    return parser.parse_args()


def main() -> None:
    import io
    import sys

    args = parse_args()
    result = normalize_dataset(args.input.resolve(), args.output.resolve(), dry_run=args.dry_run)

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    if args.dry_run:
        print(f"DRY RUN: {result['change_count']} changes would be made")
    else:
        print(f"Written {result['final_count']} items (was {result['original_count']})")
        print(f"{result['change_count']} changes applied")

    for change in result["changes"][:30]:
        action = change["action"]
        if action == "renamed":
            print(f"  RENAME: {change['old_title'][:50]} -> {change['new_title'][:50]}")
        elif action == "recategorized":
            print(f"  CATEGORY: [{change['title'][:40]}] {change['old_category']} -> {change['new_category']}")
        elif action == "removed":
            print(f"  REMOVE: {change['title'][:50]}")
        elif action == "disambiguated":
            print(f"  DUPLICATE: {change['old_title'][:40]} -> {change['new_title'][:50]}")

    if len(result["changes"]) > 30:
        print(f"  ... and {len(result['changes']) - 30} more")


if __name__ == "__main__":
    main()
