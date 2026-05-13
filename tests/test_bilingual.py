"""Tests for bilingual JSON parsing."""


def test_parse_bilingual_json_valid():
    from heritage_explorer.agent import _parse_bilingual_json

    raw = """{
  "answer": "朱仙镇木版年画是中国传统美术瑰宝。",
  "fields": {
    "名称": "Zhuxianzhen Woodblock New Year Prints",
    "类别": "Traditional Fine Arts",
    "简介": "Zhuxianzhen woodblock prints are one of China's oldest folk art forms...",
    "主要特色": "Bold outlines, vibrant colors, hand-carved wooden blocks..."
  }
}"""
    result = _parse_bilingual_json(raw)
    assert result is not None
    assert "answer" in result
    assert "fields" in result
    assert result["fields"]["名称"] == "Zhuxianzhen Woodblock New Year Prints"
    assert result["fields"]["类别"] == "Traditional Fine Arts"
    assert len(result["fields"]) == 4


def test_parse_bilingual_json_with_markdown_fence():
    from heritage_explorer.agent import _parse_bilingual_json

    raw = """```json
{
  "answer": "test answer",
  "fields": {
    "名称": "Name",
    "类别": "Category",
    "简介": "Summary",
    "主要特色": "Features"
  }
}
```"""
    result = _parse_bilingual_json(raw)
    assert result is not None
    assert result["answer"] == "test answer"
    assert result["fields"]["名称"] == "Name"


def test_parse_bilingual_json_missing_keys():
    from heritage_explorer.agent import _parse_bilingual_json

    assert _parse_bilingual_json('{"answer": "hi"}') is None
    assert _parse_bilingual_json('{"fields": {}}') is None
    assert _parse_bilingual_json("not json") is None
    assert _parse_bilingual_json("") is None


def test_parse_bilingual_json_extra_text_around_json():
    from heritage_explorer.agent import _parse_bilingual_json

    raw = """Sure! Here is the translation:

{
  "answer": "intro",
  "fields": {
    "名称": "EN",
    "类别": "EN",
    "简介": "EN",
    "主要特色": "EN"
  }
}

Hope that helps!"""
    result = _parse_bilingual_json(raw)
    assert result is not None
    assert result["answer"] == "intro"


def test_parse_bilingual_json_partial_fields():
    from heritage_explorer.agent import _parse_bilingual_json

    raw = """{
  "answer": "intro",
  "fields": {
    "名称": "Name",
    "类别": "Category"
  }
}"""
    result = _parse_bilingual_json(raw)
    assert result is None
