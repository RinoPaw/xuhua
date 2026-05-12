"""Context building and text extraction for the heritage AI."""

from __future__ import annotations

import re

from ..dataset import HeritageItem, normalize_text
from ..ai.prompts import get_structured_labels


def build_context(sources: list[HeritageItem], max_chars: int) -> str:
    chunks = []
    remaining = max_chars
    for index, item in enumerate(sources, start=1):
        text = item_context_text(item)
        chunk = f"[{index}] 标题：{item.title}\n类别：{item.category}\n资料：{text}"
        if len(chunk) > remaining:
            chunk = chunk[: max(0, remaining - 20)] + "..."
        chunks.append(chunk)
        remaining -= len(chunk)
        if remaining <= 0:
            break
    return "\n\n".join(chunks)


def item_context_text(item: HeritageItem) -> str:
    parts = []
    for label in ("介绍", "历史", "主要特色", "重要价值", "传承人"):
        value = extract_structured_field(item.content, label)
        if value:
            parts.append(f"{label}：{clean_knowledge_text(value)}")
    if parts:
        return "\n".join(parts)
    return clean_knowledge_text(item.summary or item.content)


def extract_structured_field(text: str, label: str) -> str:
    STRUCTURED_LABELS = get_structured_labels()
    text = normalize_text(text)
    marker = f"{label}:"
    start = text.find(marker)
    if start < 0:
        return ""
    start += len(marker)
    end = len(text)
    for next_label in STRUCTURED_LABELS:
        if next_label == label:
            continue
        for next_marker in (f", {next_label}:", f"，{next_label}:"):
            position = text.find(next_marker, start)
            if position >= 0:
                end = min(end, position)
    return text[start:end].strip(" ，,")


def clean_knowledge_text(text: str) -> str:
    text = normalize_text(text)
    text = re.sub(r"经纬度[:：]?\s*[-\d.,，\s]+", " ", text)
    text = re.sub(r"电话[:：]?\s*[\d\- ]+", " ", text)
    text = re.sub(r"序号[:：]?\s*\d+", " ", text)
    text = re.sub(r"\boperation[:：]?\s*\S+", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ，,")
    return text
