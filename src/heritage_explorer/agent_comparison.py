"""Comparison task handler for the heritage agent."""

from __future__ import annotations

import re
from typing import Any

from .agent_models import AgentResult, TaskType
from .dataset import KnowledgeBase, normalize_text
from .item_cards import _enriched_item_card, _source_payload, _title_with_family


_COMPARISON_TARGET_TRAILING_RE = re.compile(
    r"(?:有什么区别|有什么不同|有何区别|有何不同|的区别|的差异|哪个更受欢迎|哪个更适合|哪个更|哪个好|的比较|的对比|对比一下|比较一下)$"
)



def handle_comparison(kb: KnowledgeBase, analysis) -> AgentResult:
    """Handle a multi-entity structured comparison without fabricating matches."""
    from .search import search_items_lexical

    # Resolve target entities — try explicit entities first, fall back to splitting
    targets: list[str] = []
    if analysis.entities:
        targets = [_clean_comparison_target(e) for e in analysis.entities]
    else:
        # Fallback: split rewritten query on common separators
        parts = re.split(r"\s+", analysis.rewritten_query)
        targets = [_clean_comparison_target(p) for p in parts if len(p) >= 2]
    targets = [target for target in targets if target]

    if len(targets) < 2:
        # Not enough entities to compare — fall through to LLM
        from .ai import Answer, answer_question

        answer: Answer = answer_question(
            kb,
            question=analysis.rewritten_query or analysis.original_query,
        )
        return AgentResult(
            task_type=TaskType.COMPARISON,
            answer=answer.answer,
            speech=answer.speech,
            sources=answer.sources,
            mode=answer.mode,
            confidence=0.7,
        )

    # Search each target entity in the KB
    resolved: list[tuple[str, Any, Any, Any]] = []  # (entity_name, item, meta, labels)
    unmatched: list[str] = []
    used_item_ids: set[str] = set()

    for t in targets:
        match = _resolve_comparison_target(kb, t, used_item_ids)
        if match:
            display_name, item, meta, labels = match
            used_item_ids.add(item.id)
            resolved.append((display_name, item, meta, labels))
        else:
            unmatched.append(t)

    if len(resolved) < 2:
        suggestion_query = _comparison_suggestion_query(targets)
        suggestions: list[Any] = []
        if suggestion_query:
            suggestions, _ = search_items_lexical(kb, query=suggestion_query, limit=4)
        suggestion_cards = [_enriched_item_card(item) for item in suggestions]
        suggestion_sources = [_source_payload(item) for item in suggestions]
        missing = unmatched or targets
        missing_text = "、".join(missing)
        answer_lines = [
            f"资料库中暂未找到可直接对应「{missing_text}」的非遗条目，因此当前不能做依据式对比。",
        ]
        if suggestion_cards:
            topic_text = f"与“{suggestion_query}”相关" if suggestion_query else "当前最接近"
            answer_lines.extend([
                "",
                f"资料库里 {topic_text} 的项目有：",
                "",
            ])
            for index, item in enumerate(suggestions, 1):
                location = " · ".join(part for part in [item.province, item.city] if part)
                category = item.category
                desc = " · ".join(part for part in [category, location] if part)
                answer_lines.append(f"{index}. {_title_with_family(item)}" + (f"（{desc}）" if desc else ""))
            answer_lines.extend([
                "",
                "你可以继续追问这些已收录项目之间的区别，或改问资料库中实际存在的地区化项目。",
            ])

        speech = (
            f"资料库中暂时没有可直接对应{missing_text}的条目，所以现在不能做依据式对比。"
            + (
                f"当前最接近的项目主要有：{'、'.join(_title_with_family(item) for item in suggestions)}。"
                if suggestions else ""
            )
        )
        return AgentResult(
            task_type=TaskType.COMPARISON,
            answer="\n".join(answer_lines),
            speech=speech,
            items=suggestion_cards,
            sources=suggestion_sources,
            mode="local",
            confidence=0.45,
            warnings=[f"未在资料库中找到可直接对应的比较项：{missing_text}"],
        )

    # Build comparison answer
    lines: list[str] = []
    lines.append(f"## {' vs '.join(name for name, _, _, _ in resolved)} 对比\n")

    # ── Table header ──
    col_width = 18
    header = f"| {'维度':<{col_width - 4}}" + "".join(
        f" | {name[:col_width - 2]:<{col_width - 2}}" for name, _, _, _ in resolved
    ) + " |"
    sep = "|" + "-" * (col_width - 1) + "|" + "|".join("-" * (col_width - 1) for _ in resolved) + "|"
    lines.append(header)
    lines.append(sep)

    def _row(label: str, *values: str) -> str:
        return f"| {label:<{col_width - 4}}" + "".join(
            f" | {v[:col_width - 2]:<{col_width - 2}}" for v in values
        ) + " |"

    # Category row
    lines.append(_row("类别", *(item.category for _, item, _, _ in resolved)))

    # Level row
    lines.append(_row("级别", *(meta.level if meta else "—" for _, _, meta, _ in resolved)))

    # Province row
    lines.append(_row("省份", *(meta.province if meta else "—" for _, _, meta, _ in resolved)))

    # City row
    lines.append(_row("城市", *(meta.city if meta and meta.city else "—" for _, _, meta, _ in resolved)))

    # Display forms
    lines.append(_row(
        "展示形式",
        *("、".join(meta.display_forms) if meta and meta.display_forms else "—" for _, _, meta, _ in resolved),
    ))

    # Education value
    lines.append(_row(
        "教育价值",
        *(labels.education_value if labels else "—" for _, _, _, labels in resolved),
    ))

    # Interaction potential
    lines.append(_row(
        "互动潜力",
        *(labels.interaction_potential if labels else "—" for _, _, _, labels in resolved),
    ))

    # ── Narrative sections ──
    lines.append("")
    for entity_name, item, meta, labels in resolved:
        lines.append(f"### {entity_name}")
        if meta and meta.features:
            lines.append(f"**技艺特点：**{meta.features[:200]}")
        if meta and meta.history:
            lines.append(f"**历史背景：**{meta.history[:200]}")
        if meta and meta.cultural_value:
            lines.append(f"**文化价值：**{meta.cultural_value[:200]}")
        if not (meta and (meta.features or meta.history or meta.cultural_value)):
            lines.append(f"{item.summary[:300]}")
        lines.append("")

    # Comparison summary
    lines.append("### 对比小结")
    summary_parts: list[str] = []

    # Level comparison
    levels = [meta.level if meta else "" for _, _, meta, _ in resolved]
    unique_levels = list(dict.fromkeys(levels))
    if len(unique_levels) > 1:
        summary_parts.append(f"级别上，{'、'.join(f'{name}为{lv}' for (name, _, _, _), lv in zip(resolved, levels))}")
    else:
        summary_parts.append(f"两项均为{unique_levels[0]}非遗项目")

    # Category comparison
    cats = [item.category for _, item, _, _ in resolved]
    unique_cats = list(dict.fromkeys(cats))
    if len(unique_cats) > 1:
        summary_parts.append(f"分属{'和'.join(unique_cats)}不同类别")
    else:
        summary_parts.append(f"同属{unique_cats[0]}类别")

    # Education comparison
    if labels_data := [(name, labels) for name, _, _, labels in resolved if labels]:
        edu_values = [labels.education_value for _, labels in labels_data]
        if len(set(edu_values)) > 1:
            summary_parts.append("教育价值存在差异")
        else:
            summary_parts.append(f"教育价值均为{edu_values[0]}")

    lines.append("；".join(summary_parts) + "。")

    # Build evidence
    evidence: list[dict[str, Any]] = []
    for entity_name, item, _, _ in resolved:
        evidence.append({
            "type": "source",
            "claim": f"对比项：{entity_name}",
            "basis": f"lexical_search query={entity_name!r}",
            "item_id": item.id,
        })

    sources = [_source_payload(item) for _, item, _, _ in resolved]
    items = [_enriched_item_card(item) for _, item, _, _ in resolved]

    warnings: list[str] = []
    if unmatched:
        warnings.append(f"未在资料库中找到：{'、'.join(unmatched)}")

    return AgentResult(
        task_type=TaskType.COMPARISON,
        answer="\n".join(lines),
        items=items,
        sources=sources,
        evidence=evidence,
        mode="local",
        confidence=0.85 if not unmatched else 0.6,
        warnings=warnings,
    )


def _clean_comparison_target(value: str) -> str:
    cleaned = normalize_text(value)
    cleaned = _COMPARISON_TARGET_TRAILING_RE.sub("", cleaned)
    cleaned = cleaned.strip("，,。！？?、；：:~～ ")
    return cleaned


def _comparison_target_parts(target: str) -> tuple[str, str]:
    from .retriever import _PROVINCE_PATTERN, _SHORT_PROVINCE_MAP

    cleaned = _clean_comparison_target(target)
    province = ""
    match = _PROVINCE_PATTERN.search(cleaned)
    if match:
        province = match.group(1)
    else:
        for short, full in sorted(_SHORT_PROVINCE_MAP.items(), key=lambda item: len(item[0]), reverse=True):
            if short in cleaned:
                province = full
                cleaned = cleaned.replace(short, "", 1)
                break

    if province:
        cleaned = cleaned.replace(province, "")
        for short, full in _SHORT_PROVINCE_MAP.items():
            if full == province:
                cleaned = cleaned.replace(short, "")
                break

    core = cleaned.strip(" 的")
    return province, core or _clean_comparison_target(target)


def _resolve_comparison_target(kb: KnowledgeBase, target: str, used_item_ids: set[str]):
    from .search import search_items_lexical

    cleaned = _clean_comparison_target(target)
    province, core = _comparison_target_parts(cleaned)

    candidate_queries = [cleaned]
    if core and core != cleaned:
        candidate_queries.append(core)

    candidates: list[Any] = []
    seen_ids: set[str] = set()
    for query in candidate_queries:
        if not query:
            continue
        result, _ = search_items_lexical(kb, query=query, limit=8)
        for item in result:
            if item.id in used_item_ids or item.id in seen_ids:
                continue
            seen_ids.add(item.id)
            candidates.append(item)

    best = None
    best_score = 0
    for item in candidates:
        if province and item.province != province:
            continue

        names = [
            item.title,
            item.family,
        ]
        score = 0
        if cleaned in names:
            score += 120
        if core in names:
            score += 100
        if cleaned and cleaned in item.title:
            score += 90
        if core and core in item.title:
            score += 70
        if core and core in item.summary:
            score += 30
        if province and item.province == province:
            score += 25

        if score > best_score:
            best = (_title_with_family(item), item, meta, labels)
            best_score = score

    if best_score < 60:
        return None
    return best


def _comparison_suggestion_query(targets: list[str]) -> str:
    cores = []
    for target in targets:
        _, core = _comparison_target_parts(target)
        if core:
            cores.append(core)
    unique = list(dict.fromkeys(core for core in cores if len(core) >= 2))
    if len(unique) == 1:
        return unique[0]
    for candidate in sorted(unique, key=len, reverse=True):
        if all(candidate in core for core in unique):
            return candidate
    return unique[0] if unique else ""
