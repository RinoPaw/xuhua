"""Batch fix poor summaries using LLM."""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "data" / "processed" / "heritage_items.json"
DEFAULT_REPORT = ROOT / "data" / "processed" / "audit_report.json"

SUMMARY_PROMPT = """你是非遗文献编辑。为以下非遗项目写一段100-200字的摘要。
要求：
- 直接描述项目本身，禁止使用"根据提供的信息""以下是关于"等开头
- 涵盖项目的基本信息（地域、级别、核心特色）
- 语言简洁专业

项目信息：
标题: {title}
分类: {category}
内容片段: {content}

只返回摘要文本，不要任何前缀或格式标记。"""


def call_llm(prompt: str, api_key: str, base_url: str, model: str, timeout: int = 60) -> str:
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 600,
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


def fix_summaries(
    data_path: Path,
    report_path: Path,
    api_key: str,
    base_url: str,
    model: str,
    limit: int = 0,
    dry_run: bool = True,
) -> dict:
    with data_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    with report_path.open("r", encoding="utf-8") as f:
        report = json.load(f)

    # Find items with poor summaries
    poor_ids = {
        r["id"]
        for r in report["results"]
        if r.get("summary_quality") in ("poor", "empty")
    }

    items_to_fix = [item for item in data["items"] if item["id"] in poor_ids]
    if limit > 0:
        items_to_fix = items_to_fix[:limit]

    fixed = 0
    failed = 0
    changes: list[dict] = []

    for i, item in enumerate(items_to_fix):
        content_snippet = (item.get("content") or "")[:800]

        prompt = SUMMARY_PROMPT.format(
            title=item["title"],
            category=item["category"],
            content=content_snippet,
        )

        try:
            new_summary = call_llm(prompt, api_key, base_url, model)
            new_summary = new_summary.strip()
            # Remove common artifacts
            new_summary = re.sub(r'^["“]|["”]$', '', new_summary)
            new_summary = re.sub(r'^(?:摘要|总结)[:：]\s*', '', new_summary)

            if len(new_summary) > 30:
                old = item.get("summary", "")[:60]
                changes.append({
                    "id": item["id"],
                    "title": item["title"],
                    "old_summary": old,
                    "new_summary": new_summary[:120],
                })
                if not dry_run:
                    item["summary"] = new_summary
                    # Update search_text: replace first 200 chars of old summary
                    item["search_text"] = f"{item['title']} {item['category']} {new_summary} {(item.get('content') or '')[:200]}"
                fixed += 1
            else:
                failed += 1

        except Exception as exc:
            failed += 1
            if failed <= 3:
                changes.append({
                    "id": item["id"],
                    "title": item["title"],
                    "error": str(exc)[:80],
                })

        if (i + 1) % 10 == 0:
            print(f"  {i + 1}/{len(items_to_fix)} (fixed: {fixed}, failed: {failed})", flush=True)

        if i < len(items_to_fix) - 1:
            time.sleep(0.3)

    if not dry_run:
        with data_path.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
            f.write("\n")

    return {
        "total_poor": len(items_to_fix),
        "fixed": fixed,
        "failed": failed,
        "changes": changes,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fix poor summaries using LLM")
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--api-key", type=str, default="")
    parser.add_argument("--base-url", type=str, default="https://api.deepseek.com/v1")
    parser.add_argument("--model", type=str, default="deepseek-chat")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--apply", action="store_true")
    return parser.parse_args()


def main() -> None:
    import io, sys
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

    args = parse_args()
    api_key = args.api_key or __import__("os").environ.get("AI_API_KEY", "")

    if not api_key:
        raise SystemExit("AI_API_KEY not set. Use --api-key or set AI_API_KEY in .env")

    dry_run = not args.apply
    print(f"{'DRY RUN' if dry_run else 'APPLYING'}: fixing {args.report}")
    print(f"Model: {args.model} @ {args.base_url}")
    print()

    result = fix_summaries(
        args.input.resolve(),
        args.report.resolve(),
        api_key,
        args.base_url,
        args.model,
        limit=args.limit,
        dry_run=dry_run,
    )

    print(f"\nDone. Fixed: {result['fixed']}, Failed: {result['failed']} / {result['total_poor']}")
    for c in result["changes"][:10]:
        if "error" in c:
            print(f"  ERROR [{c['title'][:30]}]: {c['error'][:60]}")
        else:
            print(f"  [{c['title'][:30]}] {c['new_summary'][:80]}...")

    if dry_run:
        print("\nDRY RUN. Use --apply to write changes.")


if __name__ == "__main__":
    main()
