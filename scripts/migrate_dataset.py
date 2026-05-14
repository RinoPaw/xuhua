"""Migrate heritage_items.json to the unified format with baked-in structured fields.

Reads the current heritage_items.json, runs RuleExtractor and
infer_soft_labels on every item, and writes a new heritage_items.json
with all structured metadata and soft label fields at the top level.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(SRC))

from heritage_explorer.dataset import load_dataset
from heritage_explorer.extractor import RuleExtractor, infer_soft_labels

ROOT = Path(__file__).resolve().parents[1]
INPUT_PATH = ROOT / "data" / "processed" / "heritage_items.json"
OUTPUT_PATH = ROOT / "data" / "processed" / "heritage_items.json"
BACKUP_PATH = ROOT / "data" / "processed" / "heritage_items.bak.json"


def migrate() -> None:
    print(f"Loading {INPUT_PATH} ...")
    kb = load_dataset(INPUT_PATH)

    extractor = RuleExtractor()
    print(f"Extracting structured metadata for {len(kb.items)} items ...")
    meta_dict = extractor.extract_batch(kb.items)

    print("Inferring soft labels ...")
    labels_dict = {
        item.id: infer_soft_labels(item, meta_dict.get(item.id))
        for item in kb.items
    }

    # Build enriched items list
    enriched_items = []
    for item in kb.items:
        meta = meta_dict.get(item.id)
        labels = labels_dict.get(item.id)

        enriched = {
            "id": item.id,
            "title": item.title,
            "family": item.family,
            "category": item.category,
            "summary": item.summary,
            "content": item.content,
            "search_text": item.search_text,
            "source": item.source,
            # structured metadata
            "level": meta.level if meta else "",
            "province": meta.province if meta else "",
            "city": meta.city if meta else "",
            "district": meta.district if meta else "",
            "display_forms": list(meta.display_forms) if meta else [],
            "history": meta.history if meta else "",
            "features": meta.features if meta else "",
            "cultural_value": meta.cultural_value if meta else "",
            # soft labels
            "suitable_scenarios": list(labels.suitable_scenarios) if labels else [],
            "target_audience": list(labels.target_audience) if labels else [],
            "display_difficulty": labels.display_difficulty if labels else "",
            "interaction_potential": labels.interaction_potential if labels else "",
            "education_value": labels.education_value if labels else "",
            "cultural_keywords": list(labels.cultural_keywords) if labels else [],
        }
        enriched_items.append(enriched)

    payload = {
        "schema_version": kb.schema_version,
        "generated_at": kb.generated_at,
        "source": kb.source,
        "categories": [
            {"id": c.id, "name": c.name, "item_count": c.item_count}
            for c in kb.categories
        ],
        "items": enriched_items,
    }

    # Backup original
    if INPUT_PATH.exists() and INPUT_PATH.samefile(OUTPUT_PATH):
        print(f"Backing up to {BACKUP_PATH} ...")
        BACKUP_PATH.write_text(INPUT_PATH.read_text(encoding="utf-8"), encoding="utf-8")

    print(f"Writing {OUTPUT_PATH} ...")
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
        f.write("\n")

    # Quick verification
    verify_kb = load_dataset()
    sample = verify_kb.items[0]
    print(f"Verification - first item: id={sample.id}, level={sample.level!r}, "
          f"province={sample.province!r}, city={sample.city!r}, "
          f"scenarios={sample.suitable_scenarios!r}")

    filled = sum(1 for item in verify_kb.items if item.level)
    print(f"Items with level filled: {filled} / {len(verify_kb.items)}")
    print("Done.")


if __name__ == "__main__":
    migrate()
