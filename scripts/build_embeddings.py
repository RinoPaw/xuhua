"""Build a local semantic search index through an OpenAI-compatible embedding API."""

from __future__ import annotations

from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from heritage_explorer import config  # noqa: E402
from heritage_explorer.dataset import load_dataset  # noqa: E402
from heritage_explorer.embeddings import EmbeddingClient, build_index_payload, write_index  # noqa: E402


def main() -> None:
    if not config.EMBEDDING_API_KEY:
        raise SystemExit("EMBEDDING_API_KEY is not configured. Add it to .env first.")

    kb = load_dataset()
    client = EmbeddingClient()
    print(
        "Building embedding index "
        f"for {len(kb.items)} items with model {config.EMBEDDING_MODEL}..."
    )
    payload = build_index_payload(kb, client, batch_size=config.EMBEDDING_BATCH_SIZE)
    write_index(payload)
    print(f"Wrote embedding index to {config.EMBEDDING_INDEX_PATH}")


if __name__ == "__main__":
    main()
