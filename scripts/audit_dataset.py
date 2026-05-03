"""LLM-assisted dataset audit: validate categories and flag poor summaries."""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "processed" / "heritage_items.json"
DEFAULT_OUTPUT = ROOT / "data" / "processed" / "heritage_items.json"
DEFAULT_REPORT = ROOT / "data" / "processed" / "audit_report.json"

CATEGORY_NAMES = [
    "传统戏剧", "传统音乐", "传统美术", "传统舞蹈",
    "传统医药", "民俗", "传统技艺", "曲艺",
    "传统体育、游艺与杂技", "民间文学", "未分类",
]

AUDIT_PROMPT = """你是非物质文化遗产分类专家。审核以下非遗项目的分类和摘要质量。

分类必须是以下之一: {categories}

对每个项目，返回 JSON:
{{
  "id": "项目ID",
  "title": "原标题",
  "category_ok": true/false,
  "suggested_category": "建议分类(仅当category_ok为false时填写)",
  "category_reason": "分类错误原因(仅当category_ok为false时填写)",
  "summary_quality": "good/poor/empty",
  "issues": ["标题格式问题", "摘要质量问题", ...]
}}

只返回 JSON 数组，不要其他文字。
不要修改标题，只审核分类和摘要。

项目列表:
{items_json}"""


def call_llm(prompt: str, api_key: str, base_url: str, model: str, timeout: int = 60) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "你是一个严谨的非遗数据审核专家。只返回要求的JSON格式。"},
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.1,
        "max_tokens": 6000,
    }
    url = base_url.rstrip("/") + "/chat/completions"
    req = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"].strip()


def parse_llm_response(text: str) -> list[dict]:
    """Parse LLM response, handling markdown fences and truncation."""
    text = text.strip()
    # Extract from code fence
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.S)
    if match:
        text = match.group(1).strip()
    # Remove leading/trailing non-JSON content
    start = text.find("[")
    if start == -1:
        return []
    text = text[start:]

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Repair truncated JSON: close open objects/arrays
    repaired = _repair_truncated_json(text)
    try:
        return json.loads(repaired)
    except json.JSONDecodeError:
        pass

    return []


def _repair_truncated_json(text: str) -> str:
    """Attempt to repair a truncated JSON array by closing brackets."""
    text = text.rstrip()
    # Remove trailing commas
    while text.endswith(","):
        text = text[:-1]
    # Count unclosed braces/brackets
    open_braces = text.count("{") - text.count("}")
    open_brackets = text.count("[") - text.count("]")
    # Close inner objects first
    text += "}" * max(0, open_braces)
    text += "]" * max(0, open_brackets)
    return text


def audit_dataset(
    input_path: Path,
    api_key: str,
    base_url: str,
    model: str,
    batch_size: int = 15,
    limit: int = 0,
    delay: float = 0.5,
) -> dict:
    with input_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    items = data["items"]
    if limit > 0:
        items = items[:limit]

    all_results: list[dict] = []
    total_batches = (len(items) + batch_size - 1) // batch_size

    for batch_idx in range(total_batches):
        start = batch_idx * batch_size
        end = min(start + batch_size, len(items))
        batch = items[start:end]

        # Build compact item list for prompt
        batch_data = [
            {
                "id": item["id"],
                "title": item["title"],
                "category": item["category"],
                "summary_first_100": (item.get("summary") or "")[:100],
            }
            for item in batch
        ]

        prompt = AUDIT_PROMPT.format(
            categories=", ".join(CATEGORY_NAMES),
            items_json=json.dumps(batch_data, ensure_ascii=False, indent=2),
        )

        print(f"Batch {batch_idx + 1}/{total_batches} ({start + 1}-{end}/{len(items)}) ... ", end="", flush=True)

        try:
            response = call_llm(prompt, api_key, base_url, model)
            results = parse_llm_response(response)
            if results:
                all_results.extend(results)
                print(f"OK ({len(results)} results)")
            else:
                print("PARSE FAILURE")
                print(f"  Raw: {response[:200]}")
        except Exception as exc:
            print(f"ERROR: {exc}")

        if batch_idx < total_batches - 1:
            time.sleep(delay)

    return {
        "total_items": len(items),
        "audited_items": len(all_results),
        "results": all_results,
    }


def apply_audit(data: dict, audit: dict, *, dry_run: bool = True) -> dict:
    """Apply category fixes from audit results."""
    results_by_id = {r["id"]: r for r in audit["results"]}
    changes: list[dict] = []

    for item in data["items"]:
        result = results_by_id.get(item["id"])
        if not result:
            continue

        if not result.get("category_ok") and result.get("suggested_category"):
            old_cat = item["category"]
            new_cat = result["suggested_category"]
            if new_cat in CATEGORY_NAMES and new_cat != old_cat:
                changes.append({
                    "id": item["id"],
                    "title": item["title"],
                    "old_category": old_cat,
                    "new_category": new_cat,
                    "reason": result.get("category_reason", ""),
                })
                if not dry_run:
                    item["category"] = new_cat

        summary_quality = result.get("summary_quality", "good")
        if summary_quality in ("poor", "empty"):
            changes.append({
                "id": item["id"],
                "title": item["title"],
                "action": f"summary_{summary_quality}",
                "issues": result.get("issues", []),
            })

    return {"changes": changes, "count": len(changes)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LLM-assisted heritage dataset audit")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--api-key", type=str, default="")
    parser.add_argument("--base-url", type=str, default="https://api.deepseek.com/v1")
    parser.add_argument("--model", type=str, default="deepseek-chat")
    parser.add_argument("--batch-size", type=int, default=15)
    parser.add_argument("--limit", type=int, default=0, help="Only audit first N items (0=all)")
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true", help="Actually write changes")
    return parser.parse_args()


def main() -> None:
    import io
    import sys

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    args = parse_args()
    api_key = args.api_key or __import__("os").environ.get("AI_API_KEY", "")

    if not api_key:
        raise SystemExit("AI_API_KEY not set. Provide --api-key or set AI_API_KEY in .env")

    print(f"Auditing {args.input} with {args.model} @ {args.base_url}")
    print(f"Batch size: {args.batch_size}")
    print()

    audit = audit_dataset(
        args.input.resolve(),
        api_key,
        args.base_url,
        args.model,
        batch_size=args.batch_size,
        limit=args.limit,
    )

    # Save report
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("w", encoding="utf-8") as f:
        json.dump(audit, f, ensure_ascii=False, indent=2)
    print(f"\nReport saved to {args.report}")
    print(f"Audited {audit['audited_items']} items")

    # Apply fixes to dataset
    with args.input.open("r", encoding="utf-8") as f:
        data = json.load(f)

    result = apply_audit(data, audit, dry_run=not args.apply)

    category_fixes = [c for c in result["changes"] if "old_category" in c]
    summary_flags = [c for c in result["changes"] if c.get("action", "").startswith("summary")]

    print(f"\nCategory fixes: {len(category_fixes)}")
    for c in category_fixes[:20]:
        print(f"  [{c['title'][:40]}] {c['old_category']} -> {c['new_category']}")
        if c.get("reason"):
            print(f"    理由: {c['reason'][:80]}")

    print(f"\nSummary issues: {len(summary_flags)}")
    for c in summary_flags[:20]:
        print(f"  [{c['title'][:40]}] {c['action']}")

    if args.apply:
        with args.output.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"\nApplied. Written to {args.output}")
    else:
        print(f"\nDRY RUN. Use --apply to write changes.")


if __name__ == "__main__":
    main()
