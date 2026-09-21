from heritage_explorer.answer_policy import (
    fallback_answer,
    is_greeting,
    short_reply_mode,
    suggestions,
    used_sources,
)


def make_item(item_id: str, title: str, *, family: str = "", summary: str = ""):
    return type(
        "Item",
        (),
        {
            "id": item_id,
            "title": title,
            "family": family,
            "display_forms": (),
            "summary": summary,
            "content": "",
        },
    )()


def test_greeting_and_short_reply_detection_remain_localized():
    assert is_greeting("你好。", "zh-CN")
    assert is_greeting("Hello!", "en-US")
    assert short_reply_mode("继续") == "continuation"
    assert short_reply_mode("wait a moment") == "pause"


def test_fallback_respects_requested_item_count():
    items = tuple(make_item(str(index), f"项目{index}", summary="长" * 180) for index in range(6))
    answer = fallback_answer("推荐2个项目", items)
    assert answer.count("**项目") == 2


def test_used_sources_follow_answer_order_and_ignore_shared_family_aliases():
    items = (
        make_item("a", "甲地剪纸", family="剪纸"),
        make_item("b", "乙地剪纸", family="剪纸"),
    )
    assert [item.id for item in used_sources("先看乙地剪纸，再看甲地剪纸。", items)] == ["b", "a"]
    assert [item.id for item in used_sources("剪纸很有意思。", items)] == ["a"]


def test_suggestions_keep_named_project_first():
    items = (make_item("a", "汴绣"),)
    assert suggestions(items)[0].startswith("汴绣")
