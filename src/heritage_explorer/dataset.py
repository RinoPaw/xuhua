"""Dataset loading and normalized in-memory access."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .config import DATASET_PATH

if TYPE_CHECKING:
    from .extractor import SoftLabels, StructuredMeta

_AI_FIELDS_PATH = DATASET_PATH.parent / "ai_fields.json"


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip()


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    item_count: int


def _parse_tuple(value: Any) -> tuple[str, ...]:
    if isinstance(value, (list, tuple)):
        return tuple(str(v) for v in value)
    return ()


@dataclass(frozen=True)
class HeritageItem:
    """Core heritage item with 13 stable fields.

    Soft labels (education_value, interaction_potential, etc.) and
    LLM-enriched fields (history, features, cultural_value) are
    loaded on demand from ai_fields.json or computed via RuleExtractor.
    """

    id: str
    title: str
    family: str
    category: str
    summary: str
    content: str
    search_text: str
    # ── geo / level ──
    level: str = ""
    province: str = ""
    city: str = ""
    district: str = ""
    # ── display ──
    display_forms: tuple[str, ...] = ()
    suitable_scenarios: tuple[str, ...] = ()


@lru_cache(maxsize=1)
def _load_ai_fields() -> dict[str, dict[str, str]]:
    """Load LLM-enriched fields (features, history, cultural_value)."""
    if not _AI_FIELDS_PATH.exists():
        return {}
    with _AI_FIELDS_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_ai_fields(item_id: str) -> dict[str, str]:
    """Get LLM-enriched fields for an item. Returns dict with keys:
    features, history, cultural_value (may be empty strings if missing).
    """
    fields = _load_ai_fields().get(item_id, {})
    return {
        "features": fields.get("features", ""),
        "history": fields.get("history", ""),
        "cultural_value": fields.get("cultural_value", ""),
    }


class KnowledgeBase:
    def __init__(self, payload: dict[str, Any]):
        self.schema_version = payload.get("schema_version", 1)
        self.generated_at = payload.get("generated_at", "")
        self.source = payload.get("source", {})
        self.categories = [
            Category(
                id=int(category["id"]),
                name=str(category["name"]),
                item_count=int(category.get("item_count", 0)),
            )
            for category in payload.get("categories", [])
        ]
        self.items = [
            HeritageItem(
                id=str(item["id"]),
                title=str(item["title"]),
                family=str(item.get("family") or ""),
                category=str(item.get("category") or "未分类"),
                summary=str(item.get("summary") or ""),
                content=str(item.get("content") or ""),
                search_text=str(item.get("search_text") or ""),
                level=str(item.get("level") or ""),
                province=str(item.get("province") or ""),
                city=str(item.get("city") or ""),
                district=str(item.get("district") or ""),
                display_forms=_parse_tuple(item.get("display_forms")),
                suitable_scenarios=_parse_tuple(item.get("suitable_scenarios")),
            )
            for item in payload.get("items", [])
        ]
        self._by_id = {item.id: item for item in self.items}

    def get(self, item_id: str) -> HeritageItem | None:
        return self._by_id.get(item_id)

    def category_names(self) -> list[str]:
        return [category.name for category in self.categories]


def load_dataset(path: Path = DATASET_PATH) -> KnowledgeBase:
    with path.open("r", encoding="utf-8") as f:
        return KnowledgeBase(json.load(f))


@lru_cache(maxsize=1)
def get_knowledge_base() -> KnowledgeBase:
    return load_dataset()


def get_structured_meta(item_id: str) -> "StructuredMeta | None":
    """Backward-compatible adapter: build StructuredMeta from HeritageItem + ai_fields."""
    from .extractor import StructuredMeta

    kb = get_knowledge_base()
    item = kb.get(item_id)
    if item is None:
        return None
    ai = get_ai_fields(item_id)
    return StructuredMeta(
        level=item.level,
        province=item.province,
        city=item.city,
        district=item.district,
        display_forms=item.display_forms,
        history=ai["history"],
        features=ai["features"],
        cultural_value=ai["cultural_value"],
    )


def get_soft_labels(item_id: str) -> "SoftLabels | None":
    """Compute soft labels on-the-fly via RuleExtractor."""
    from .extractor import RuleExtractor, infer_soft_labels

    kb = get_knowledge_base()
    item = kb.get(item_id)
    if item is None:
        return None
    extractor = RuleExtractor()
    meta = extractor.extract(item)
    return infer_soft_labels(item, meta)


def item_to_dict(item: HeritageItem, include_content: bool = False) -> dict[str, Any]:
    data = {
        "id": item.id,
        "title": item.title,
        "family": item.family,
        "category": item.category,
        "summary": item.summary,
        "level": item.level,
        "province": item.province,
        "city": item.city,
        "district": item.district,
        "display_forms": list(item.display_forms),
        "suitable_scenarios": list(item.suitable_scenarios),
    }
    # Merge ai_fields for API consumers
    ai = get_ai_fields(item.id)
    data["features"] = ai["features"]
    data["history"] = ai["history"]
    data["cultural_value"] = ai["cultural_value"]
    if include_content:
        data["content"] = item.content
    return data
