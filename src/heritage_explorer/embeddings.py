"""OpenAI-compatible embedding indexing and semantic retrieval."""

from __future__ import annotations

import json
import math
import textwrap
import time
import urllib.error
import urllib.request
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import config
from .dataset import HeritageItem, KnowledgeBase, normalize_text


class EmbeddingUnavailable(RuntimeError):
    """Raised when semantic retrieval is not configured or cannot be used."""


@dataclass(frozen=True)
class EmbeddingRecord:
    item_id: str
    vector: tuple[float, ...]


@dataclass(frozen=True)
class EmbeddingIndex:
    model: str
    base_url: str
    dimensions: int
    records: tuple[EmbeddingRecord, ...]

    @classmethod
    def from_payload(cls, payload: dict[str, Any]) -> "EmbeddingIndex":
        records = []
        dimensions = int(payload.get("dimensions") or 0)
        for raw in payload.get("embeddings", []):
            item_id = str(raw.get("id") or "")
            vector = normalize_vector(raw.get("embedding") or [])
            if not item_id or not vector:
                continue
            dimensions = dimensions or len(vector)
            records.append(EmbeddingRecord(item_id=item_id, vector=tuple(vector)))
        return cls(
            model=str(payload.get("model") or ""),
            base_url=str(payload.get("base_url") or ""),
            dimensions=dimensions,
            records=tuple(records),
        )


class EmbeddingClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        timeout: int | None = None,
        max_retries: int | None = None,
        retry_backoff: float | None = None,
    ):
        self.api_key = config.EMBEDDING_API_KEY if api_key is None else api_key
        self.base_url = (config.EMBEDDING_BASE_URL if base_url is None else base_url).rstrip("/")
        self.model = config.EMBEDDING_MODEL if model is None else model
        self.timeout = config.EMBEDDING_TIMEOUT if timeout is None else timeout
        self.max_retries = config.EMBEDDING_MAX_RETRIES if max_retries is None else max_retries
        self.retry_backoff = config.EMBEDDING_RETRY_BACKOFF if retry_backoff is None else retry_backoff

    def embed_texts(self, texts: list[str]) -> list[list[float]]:
        if not self.api_key:
            raise EmbeddingUnavailable("EMBEDDING_API_KEY is not configured.")
        if not texts:
            return []

        last_error = ""
        for attempt in range(self.max_retries + 1):
            try:
                return self._embed_texts_once(texts)
            except (EmbeddingUnavailable, TimeoutError) as exc:
                last_error = str(exc) or type(exc).__name__
                if attempt >= self.max_retries:
                    break
                time.sleep(self.retry_delay(exc, attempt))
        raise EmbeddingUnavailable(last_error or "Embedding request failed.")

    def retry_delay(self, exc: Exception, attempt: int) -> float:
        if isinstance(exc.__cause__, urllib.error.HTTPError):
            retry_after = exc.__cause__.headers.get("Retry-After")
            if retry_after:
                try:
                    return max(float(retry_after), 0.0)
                except ValueError:
                    pass
        return self.retry_backoff * (attempt + 1)

    def _embed_texts_once(self, texts: list[str]) -> list[list[float]]:
        payload = {
            "model": self.model,
            "input": texts,
        }
        request = urllib.request.Request(
            self.base_url + "/embeddings",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise EmbeddingUnavailable(describe_embedding_error(exc, self.api_key)) from exc
        except urllib.error.URLError as exc:
            raise EmbeddingUnavailable(describe_embedding_error(exc, self.api_key)) from exc

        try:
            rows = sorted(body["data"], key=lambda row: int(row.get("index", 0)))
            return [list(map(float, row["embedding"])) for row in rows]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingUnavailable("Unexpected embedding API response.") from exc


def build_embedding_text(item: HeritageItem, max_chars: int | None = None) -> str:
    max_chars = config.EMBEDDING_TEXT_MAX_CHARS if max_chars is None else max_chars
    aliases = "、".join(item.aliases)
    parts = [
        f"名称：{item.title}",
        f"类别：{item.category}",
        f"别名：{aliases}" if aliases else "",
        f"摘要：{item.summary}",
        f"正文：{item.content}",
    ]
    text = normalize_text("\n".join(part for part in parts if part))
    return textwrap.shorten(text, width=max_chars, placeholder="...")


def build_index_payload(
    kb: KnowledgeBase,
    client: EmbeddingClient,
    batch_size: int | None = None,
) -> dict[str, Any]:
    batch_size = config.EMBEDDING_BATCH_SIZE if batch_size is None else batch_size
    rows: list[dict[str, Any]] = []
    dimensions = 0
    for start in range(0, len(kb.items), batch_size):
        batch = kb.items[start : start + batch_size]
        texts = [build_embedding_text(item) for item in batch]
        vectors = client.embed_texts(texts)
        if len(vectors) != len(batch):
            raise EmbeddingUnavailable("Embedding API returned a mismatched batch length.")
        for item, vector in zip(batch, vectors, strict=True):
            normalized = normalize_vector(vector)
            dimensions = dimensions or len(normalized)
            rows.append({"id": item.id, "embedding": normalized})

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
        "dimensions": dimensions,
        "embeddings": rows,
    }


def write_index(payload: dict[str, Any], path: Path | None = None) -> None:
    path = config.EMBEDDING_INDEX_PATH if path is None else path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    _load_embedding_index.cache_clear()


@lru_cache(maxsize=1)
def _load_embedding_index(path_text: str) -> EmbeddingIndex | None:
    path = Path(path_text)
    if not path.exists():
        return None
    with path.open("r", encoding="utf-8") as f:
        return EmbeddingIndex.from_payload(json.load(f))


def load_embedding_index(path: Path | None = None) -> EmbeddingIndex | None:
    path = config.EMBEDDING_INDEX_PATH if path is None else path
    return _load_embedding_index(str(path))


def embedding_scores(
    kb: KnowledgeBase,
    query: str,
    candidates: Iterable[HeritageItem],
    client: EmbeddingClient | None = None,
    min_score: float | None = None,
) -> dict[str, float]:
    query = normalize_text(query)
    if not query:
        return {}

    index = load_embedding_index()
    if index is None or not index.records:
        raise EmbeddingUnavailable("Embedding index does not exist.")

    client = client or EmbeddingClient()
    query_vector = normalize_vector(client.embed_texts([query])[0])
    if not query_vector:
        return {}

    records = {record.item_id: record.vector for record in index.records}
    candidate_ids = {item.id for item in candidates}
    known_ids = {item.id for item in kb.items}
    threshold = config.EMBEDDING_MIN_SCORE if min_score is None else min_score
    scores: dict[str, float] = {}
    for item_id, vector in records.items():
        if item_id not in candidate_ids or item_id not in known_ids:
            continue
        score = dot(query_vector, vector)
        if score >= threshold:
            scores[item_id] = score
    return scores


def normalize_vector(vector: Iterable[float]) -> list[float]:
    values = [float(value) for value in vector]
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 0:
        return []
    return [value / norm for value in values]


def dot(left: Iterable[float], right: Iterable[float]) -> float:
    return sum(a * b for a, b in zip(left, right, strict=False))


def describe_embedding_error(exc: Exception, api_key: str = "") -> str:
    if isinstance(exc, urllib.error.HTTPError):
        detail = f"HTTPError {exc.code}"
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:  # noqa: BLE001 - best effort diagnostics only.
            body = ""
        if body:
            detail += f": {body}"
    elif isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", "")
        detail = f"URLError: {reason or exc}"
    else:
        detail = str(exc) or type(exc).__name__

    text = normalize_text(detail)
    if api_key:
        text = text.replace(api_key, "***")
    return textwrap.shorten(text, width=220, placeholder="...")
