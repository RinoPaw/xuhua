"""Scenario matching with hard evidence separated from soft inferred labels."""

from __future__ import annotations

from typing import Any

from .dataset import normalize_text


SOFT_SCENARIO_SCORE = 2
HARD_SCENARIO_THRESHOLD = 4

SCENARIO_EVIDENCE_TERMS: dict[str, tuple[str, ...]] = {
    "社区活动": ("社区活动", "社区", "民俗活动", "活动", "居民", "节庆"),
    "校园展示": ("校园展示", "校园", "学校", "学生", "课堂", "教学", "中小学"),
    "研学体验": ("研学体验", "研学", "课程", "课堂", "教学", "学习", "实践", "实操", "体验"),
    "文创设计": ("文创设计", "文创", "设计", "包装", "纹样", "图案", "衍生品", "产品"),
    "展馆讲解": ("展馆讲解", "展馆", "讲解", "展览", "陈列", "导览", "参观"),
    "亲子互动": ("亲子", "儿童", "孩子", "家庭", "家长", "动手", "手作", "互动", "玩具", "游戏", "泥玩具", "吹响"),
}

SCENARIO_STRONG_TERMS: dict[str, tuple[str, ...]] = {
    "社区活动": ("社区活动", "民俗活动", "居民", "节庆"),
    "校园展示": ("校园展示", "学校", "学生", "中小学"),
    "研学体验": ("研学体验", "研学", "课程", "课堂", "教学", "实践", "实操"),
    "文创设计": ("文创设计", "文创", "包装", "纹样", "衍生品"),
    "展馆讲解": ("展馆讲解", "展馆", "导览", "陈列"),
    "亲子互动": ("亲子", "儿童", "孩子", "家长", "玩具", "泥玩具", "游戏", "动手", "手作", "吹响"),
}


def scenario_match_score(item: Any, scenario: str) -> int:
    """Return scenario support score.

    Hard evidence comes from display forms and source text.  Soft category-inferred
    labels are allowed as weak tie-breakers only and cannot pass the threshold alone.
    """
    scenario = normalize_text(scenario)
    if not scenario:
        return 0

    terms = SCENARIO_EVIDENCE_TERMS.get(scenario, (scenario,))
    display_text = normalize_text(" ".join(getattr(item, "display_forms", ()) or ()))
    source_text = normalize_text(
        " ".join(
            str(part or "")
            for part in [
                getattr(item, "title", ""),
                getattr(item, "family", ""),
                getattr(item, "category", ""),
                getattr(item, "summary", ""),
                getattr(item, "content", "")[:800],
            ]
        )
    )
    suitable_scenarios = tuple(getattr(item, "suitable_scenarios", ()) or ())

    score = 0
    if scenario and scenario in display_text:
        score += 10
    display_hits = sum(1 for term in terms if term and term in display_text)
    source_hits = sum(1 for term in terms if term and term in source_text)
    strong_source_hits = sum(1 for term in SCENARIO_STRONG_TERMS.get(scenario, ()) if term and term in source_text)
    score += min(display_hits * 6, 12)
    if strong_source_hits:
        score += min(strong_source_hits * 5, 10)
    elif source_hits >= 2:
        score += min(source_hits * 3, 6)
    if scenario in suitable_scenarios:
        score += SOFT_SCENARIO_SCORE
    return score


def scenario_is_hard_match(item: Any, scenario: str) -> bool:
    return scenario_match_score(item, scenario) >= HARD_SCENARIO_THRESHOLD
