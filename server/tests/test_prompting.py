from __future__ import annotations

from heritage_explorer.dataset import KnowledgeBase
from heritage_explorer.models import ConversationTurn
from heritage_explorer.prompting import build_messages, candidate_context


def make_items():
    knowledge_base = KnowledgeBase(
        {
            "items": [
                {
                    "id": "item-1",
                    "title": "汴绣",
                    "category": "传统美术",
                    "summary": "开封刺绣项目",
                    "content": "汴绣以传统针法表现人物、花鸟和山水。",
                    "province": "河南省",
                    "city": "开封市",
                },
                {
                    "id": "item-2",
                    "title": "朱仙镇木版年画",
                    "category": "传统美术",
                    "summary": "木版年画项目",
                    "content": "以雕版套印等方式制作。",
                    "province": "河南省",
                    "city": "开封市",
                },
            ]
        }
    )
    return tuple(knowledge_base.items)


def test_build_messages_preserves_speaker_roles_and_separates_retrieval_context():
    history = [ConversationTurn("turn-1", "介绍锅庄舞", "锅庄舞常见圆圈舞形态。")]
    messages = build_messages(
        "嗯。",
        (),
        history,
        short_reply_mode="continuation",
        retrieval_basis="none",
        locale="zh-CN",
    )

    assert [message["role"] for message in messages] == [
        "system",
        "user",
        "assistant",
        "system",
        "system",
        "system",
        "user",
    ]
    assert messages[1]["content"] == "介绍锅庄舞"
    assert messages[2]["content"] == "锅庄舞常见圆圈舞形态。"
    assert "没有识别到明确的非遗项目" in messages[3]["content"]
    assert messages[-1] == {"role": "user", "content": "嗯。"}


def test_candidate_context_keeps_first_record_even_when_budget_is_tiny():
    items = make_items()
    context = candidate_context(items, 1)
    assert "汴绣" in context
    assert "朱仙镇木版年画" not in context


def test_retrieval_context_is_marked_as_system_evidence_not_user_text():
    items = make_items()
    messages = build_messages(
        "介绍汴绣",
        items,
        (),
        short_reply_mode=None,
        retrieval_basis="item_name",
        locale="zh-CN",
    )
    evidence = messages[-3]["content"]
    assert "系统为本轮自动检索" in evidence
    assert "汴绣" in evidence
    assert messages[-2]["role"] == "system"
    assert messages[-1] == {"role": "user", "content": "介绍汴绣"}
