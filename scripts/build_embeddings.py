"""Build a local semantic search index through an OpenAI-compatible embedding API."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import time
from typing import Any
from datetime import UTC, datetime


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from heritage_explorer import config  # noqa: E402
from heritage_explorer.dataset import HeritageItem, load_dataset  # noqa: E402
from heritage_explorer.embeddings import (  # noqa: E402
    EmbeddingClient,
    build_embedding_text,
    normalize_vector,
    write_index,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=config.EMBEDDING_INDEX_PATH)
    parser.add_argument("--limit", type=int, default=0, help="Only index the first N items.")
    parser.add_argument("--batch-size", type=int, default=config.EMBEDDING_BATCH_SIZE)
    parser.add_argument("--delay", type=float, default=config.EMBEDDING_REQUEST_DELAY)
    parser.add_argument("--no-resume", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not config.EMBEDDING_API_KEY:
        raise SystemExit("EMBEDDING_API_KEY is not configured. Add it to .env first.")

    kb = load_dataset()
    items = kb.items[: args.limit] if args.limit > 0 else kb.items
    client = EmbeddingClient()
    payload = initial_payload(kb, client)
    indexed = {}

    if args.output.exists() and not args.no_resume:
        payload = load_existing_payload(args.output, client)
        indexed = {
            str(row["id"]): row
            for row in payload.get("embeddings", [])
            if row.get("id") and row.get("embedding")
        }

    remaining = [item for item in items if item.id not in indexed]
    payload["embeddings"] = [indexed[item.id] for item in items if item.id in indexed]

    print(
        "Building embedding index "
        f"for {len(items)} items with model {config.EMBEDDING_MODEL} "
        f"({len(indexed)} already indexed)..."
    )
    if not remaining:
        write_index(payload, args.output)
        print(f"Embedding index is already complete: {args.output}")
        return

    for start in range(0, len(remaining), args.batch_size):
        batch = remaining[start : start + args.batch_size]
        rows = embed_batch(client, batch)
        indexed.update({row["id"]: row for row in rows})
        payload["embeddings"] = [indexed[item.id] for item in items if item.id in indexed]
        payload["dimensions"] = payload["dimensions"] or len(rows[0]["embedding"])
        write_index(payload, args.output)
        done = len(payload["embeddings"])
        print(f"Indexed {done}/{len(items)} -> {args.output}")
        if args.delay > 0 and done < len(items):
            time.sleep(args.delay)

    print(f"Wrote embedding index to {args.output}")


def initial_payload(kb, client: EmbeddingClient) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "dataset": {
            "schema_version": kb.schema_version,
            "generated_at": kb.generated_at,
            "item_count": len(kb.items),
        },
        "base_url": client.base_url,
        "model": client.model,
        "dimensions": 0,
        "embeddings": [],
    }


def load_existing_payload(path: Path, client: EmbeddingClient) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if payload.get("model") != client.model or payload.get("base_url") != client.base_url:
        raise SystemExit(
            "Existing embedding index uses another provider or model. "
            "Use --no-resume or another --output path."
        )
    return payload


def embed_batch(client: EmbeddingClient, batch: list[HeritageItem]) -> list[dict[str, Any]]:
    texts = [build_embedding_text(item) for item in batch]
    vectors = client.embed_texts(texts)
    if len(vectors) != len(batch):
        raise RuntimeError("Embedding API returned a mismatched batch length.")
    rows = []
    for item, vector in zip(batch, vectors, strict=True):
        rows.append({"id": item.id, "embedding": normalize_vector(vector)})
    return rows


if __name__ == "__main__":
    main()
