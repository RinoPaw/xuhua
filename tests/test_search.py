from heritage_explorer import search
from heritage_explorer.dataset import KnowledgeBase


def make_kb():
    return KnowledgeBase(
        {
            "items": [
                {
                    "id": "b",
                    "title": "木雕技艺",
                    "family": "雕刻",
                    "display_forms": ["木雕"],
                    "category": "传统技艺",
                    "summary": "浙江木雕工艺",
                    "content": "木雕历史悠久",
                    "level": "国家级",
                    "province": "浙江省",
                    "city": "东阳市",
                    "district": "吴宁街道",
                },
                {
                    "id": "a",
                    "title": "龙舞",
                    "family": "舞蹈",
                    "display_forms": ["舞龙"],
                    "category": "传统舞蹈",
                    "summary": "广东民间舞蹈",
                    "content": "节庆表演",
                    "level": "国家级",
                    "province": "广东省",
                    "city": "东莞市",
                    "district": "莞城区",
                },
                {
                    "id": "c",
                    "title": "龙舟",
                    "family": "体育",
                    "category": "传统体育",
                    "summary": "广东水上活动",
                    "content": "端午竞渡",
                    "level": "省级",
                    "province": "广东省",
                    "city": "广州市",
                    "district": "荔湾区",
                },
            ]
        }
    )


def test_empty_query_filters_and_pagination_are_stable():
    items, total = search.search_items(make_kb(), category="传统舞蹈", limit=1, offset=0)
    assert total == 1
    assert [item.id for item in items] == ["a"]

    items, total = search.search_items(make_kb(), limit=2, offset=1, use_pinyin=False)
    assert total == 3
    assert [item.id for item in items] == ["b", "a"]


def test_weighted_fields_and_keywords():
    kb = make_kb()
    items, total = search.search_items(kb, query="龙舞", use_pinyin=False)
    assert total == 1
    assert items[0].id == "a"


def test_category_intent_is_a_hard_scope_and_intent_words_are_ignored():
    kb = make_kb()
    items, total = search.search_items(
        kb,
        query="有哪些传统舞蹈项目值得了解？",
        use_pinyin=False,
    )
    assert total == 1
    assert [item.id for item in items] == ["a"]

    items, total = search.search_items(
        kb,
        query="推荐5个传统体育项目",
        use_pinyin=False,
    )
    assert total == 1
    assert [item.id for item in items] == ["c"]


def test_category_only_results_diversify_regions_without_randomness():
    payload = {
        "categories": [{"id": 7, "name": "传统音乐", "item_count": 4}],
        "items": [
            {
                "id": "one", "title": "甲曲", "category": "传统音乐",
                "province": "甲省", "level": "国家级",
            },
            {
                "id": "two", "title": "乙曲", "category": "传统音乐",
                "province": "甲省", "level": "国家级",
            },
            {
                "id": "three", "title": "丙曲", "category": "传统音乐",
                "province": "乙省", "level": "国家级",
            },
            {
                "id": "four", "title": "丁曲", "category": "传统音乐",
                "province": "丙省", "level": "国家级",
            },
        ],
    }
    kb = KnowledgeBase(payload)
    first, total = search.search_items(
        kb,
        query="有哪些传统音乐项目值得了解？",
        limit=3,
        use_pinyin=False,
    )
    assert total == 4
    assert len({item.province for item in first}) == 3


def test_province_mentioned_in_query_becomes_a_filter():
    kb = make_kb()
    items, total = search.search_items(
        kb,
        query="推荐广东非遗项目",
        use_pinyin=False,
    )
    assert total == 2
    assert {item.province for item in items} == {"广东省"}

    items, total = search.search_items(kb, keywords="浙江", use_pinyin=False)
    assert total == 1
    assert items[0].id == "b"

    items, total = search.search_items(kb, query="莞城", district="莞城区", use_pinyin=False)
    assert total == 1
    assert items[0].id == "a"


def test_pinyin_is_optional(monkeypatch):
    kb = make_kb()
    monkeypatch.setattr(search, "_pinyin_forms", lambda text: [])
    items, total = search.search_items(kb, query="luowu", use_pinyin=True)
    assert total == 0
    assert items == []

    def fake_pinyin(text):
        return {"luowu": ["luowu"], "龙舞": ["luowu"], "舞蹈": ["wudao"]}.get(text, [text])

    monkeypatch.setattr(search, "_pinyin_forms", fake_pinyin)
    items, total = search.search_items(kb, query="luowu", use_pinyin=True)
    assert total == 1
    assert items[0].id == "a"
