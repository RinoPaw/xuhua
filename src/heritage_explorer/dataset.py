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


def normalize_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip()


@dataclass(frozen=True)
class Category:
    id: int
    name: str
    item_count: int


@dataclass(frozen=True)
class HeritageItem:
    id: str
    title: str
    category: str
    summary: str
    content: str
    aliases: tuple[str, ...]
    search_text: str
    source: dict[str, Any]


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
                category=str(item.get("category") or "未分类"),
                summary=str(item.get("summary") or ""),
                content=str(item.get("content") or ""),
                aliases=tuple(item.get("aliases") or ()),
                search_text=str(item.get("search_text") or ""),
                source=dict(item.get("source") or {}),
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


_meta_cache: dict[str, "StructuredMeta"] | None = None
_labels_cache: dict[str, "SoftLabels"] | None = None


def _load_extraction_cache() -> tuple[dict[str, "StructuredMeta"], dict[str, "SoftLabels"]]:
    global _labels_cache, _meta_cache
    if _meta_cache is None or _labels_cache is None:
        from .extractor import ExtractionCache

        _meta_cache, _labels_cache = ExtractionCache().load()
    return _meta_cache, _labels_cache


def clear_extraction_cache() -> None:
    global _labels_cache, _meta_cache
    _meta_cache = None
    _labels_cache = None


def get_structured_meta(item_id: str) -> "StructuredMeta | None":
    meta, _ = _load_extraction_cache()
    return meta.get(item_id)


def get_soft_labels(item_id: str) -> "SoftLabels | None":
    _, labels = _load_extraction_cache()
    return labels.get(item_id)


def item_to_dict(item: HeritageItem, include_content: bool = False) -> dict[str, Any]:
    data = {
        "id": item.id,
        "title": item.title,
        "category": item.category,
        "summary": item.summary,
        "aliases": list(item.aliases),
        "source": item.source,
    }
    if include_content:
        data["content"] = item.content
    return data
