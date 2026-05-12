"""Tests for planner prompt construction, JSON extraction, and decision parsing."""
import pytest
from heritage_explorer.agent.planner import (
    build_agent_planner_messages,
    extract_json_object,
    decision_from_planner_payload,
)
from heritage_explorer.agent_models import TaskType
from heritage_explorer.dataset import load_dataset


def test_build_planner_messages_includes_kb_stats():
    kb = load_dataset()
    messages = build_agent_planner_messages("太极拳", kb)
    user_msg = messages[1]["content"]
    assert str(len(kb.items)) in user_msg


def test_build_planner_messages_includes_query():
    kb = load_dataset()
    messages = build_agent_planner_messages("太极拳是什么", kb)
    user_msg = messages[1]["content"]
    assert "太极拳是什么" in user_msg


def test_extract_json_object_handles_markdown_fence():
    result = extract_json_object('```json\n{"key": "value"}\n```')
    assert result == '{"key": "value"}'


def test_extract_json_object_handles_plain_json():
    result = extract_json_object('{"task_type": "fact_qa"}')
    assert result == '{"task_type": "fact_qa"}'


def test_extract_json_object_handles_json_with_text_before():
    result = extract_json_object('some text {"task_type": "fact_qa"} more')
    assert result == '{"task_type": "fact_qa"}'


def test_extract_json_object_raises_on_no_json():
    with pytest.raises(ValueError):
        extract_json_object("no json here at all")


def test_decision_from_planner_chitchat_forces_local():
    kb = load_dataset()
    decision = decision_from_planner_payload(
        {
            "task_type": "chitchat",
            "confidence": 0.9,
            "needs_retrieval": True,
            "needs_llm": True,
            "reason": "test",
            "direct_answer": "hello",
            "mode": "no_context",
        },
        "hi",
        kb,
    )
    assert decision.task_type is TaskType.CHITCHAT
    assert not decision.needs_retrieval
    assert not decision.needs_llm
    assert decision.mode == "local"


def test_decision_from_planner_unknown_type_defaults_to_fact_qa():
    kb = load_dataset()
    decision = decision_from_planner_payload({"task_type": "xyz"}, "test", kb)
    assert decision.task_type is TaskType.FACT_QA


def test_decision_from_planner_clamps_confidence():
    kb = load_dataset()
    decision = decision_from_planner_payload(
        {"task_type": "fact_qa", "confidence": 5.0}, "test", kb
    )
    assert decision.confidence == 1.0
