"""Regression coverage for requested catalogue result counts."""

import pytest

from heritage_explorer.retrieval_policy import candidate_limit, requested_item_count


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("推荐一个非遗项目", 1),
        ("推荐两个非遗项目", 2),
        ("推荐十个非遗项目", 10),
        ("推荐十一个非遗项目", 11),
        ("推荐十二个非遗项目", 12),
        ("介绍二十个非遗项目", 20),
        ("列举二十五项非遗项目", 25),
        ("看看三十种传统技艺", 30),
        ("推荐一百零五个项目", 105),
        ("推荐一百二十个项目", 120),
        ("推荐100个项目", 100),
        ("推荐1000个项目", 1000),
        ("List 120 heritage projects", 120),
        ("Show 25 examples", 25),
        ("今天的天气怎么样", None),
        ("推荐十二十二个项目", None),
    ],
)
def test_count_parser_does_not_truncate_composite_numbers(question, expected):
    assert requested_item_count(question) == expected


def test_candidate_window_uses_full_requested_count():
    search = object()
    assert candidate_limit(search, "推荐十二个项目", "", 30) == 14
    assert candidate_limit(search, "推荐二十五个项目", "", 30) == 27
    assert candidate_limit(search, "推荐100个项目", "", 30) == 30
