"""Tests for bilingual JSON parsing."""


def test_parse_bilingual_json_valid():
    from heritage_explorer.agent import _parse_bilingual_json

    raw = """{
  "answer": "朱仙镇木版年画是中国传统美术瑰宝。",
  "speech_en": "Zhuxianzhen Woodblock New Year Prints are a treasured form of traditional Chinese art.",
  "fields": {
    "名称": { "zh": "朱仙镇木版年画", "en": "Zhuxianzhen Woodblock New Year Prints" },
    "类别": { "zh": "传统美术", "en": "Traditional Fine Arts" },
    "简介": { "zh": "朱仙镇木版年画历史悠久。", "en": "Zhuxianzhen woodblock prints are one of China's oldest folk art forms." },
    "主要特色": { "zh": "线条有力，色彩浓烈。", "en": "Bold outlines and vibrant colors." }
  }
}"""
    result = _parse_bilingual_json(raw)
    assert result is not None
    assert "answer" in result
    assert "fields" in result
    assert result["speech_en"].startswith("Zhuxianzhen Woodblock New Year Prints")
    assert result["fields"]["名称"] == {"zh": "朱仙镇木版年画", "en": "Zhuxianzhen Woodblock New Year Prints"}
    assert result["fields"]["类别"] == {"zh": "传统美术", "en": "Traditional Fine Arts"}
    assert len(result["fields"]) == 4


def test_parse_bilingual_json_with_markdown_fence():
    from heritage_explorer.agent import _parse_bilingual_json

    raw = """```json
{
  "answer": "test answer",
  "speech_en": "This is a short English speech.",
  "fields": {
    "名称": { "zh": "名称", "en": "Name" },
    "类别": { "zh": "类别", "en": "Category" },
    "简介": { "zh": "简介", "en": "Summary" },
    "主要特色": { "zh": "特色", "en": "Features" }
  }
}
```"""
    result = _parse_bilingual_json(raw)
    assert result is not None
    assert result["answer"] == "test answer"
    assert result["fields"]["名称"] == {"zh": "名称", "en": "Name"}


def test_parse_bilingual_json_structured_zh_en_fields():
    from heritage_explorer.agent import _parse_bilingual_json

    raw = """{
  "answer": "双语导语。",
  "speech_en": "Bian Embroidery is a representative embroidery tradition from Kaifeng.",
  "fields": {
    "名称": { "zh": "汴绣", "en": "Bian Embroidery" },
    "类别": { "zh": "传统美术", "en": "Traditional Fine Arts" },
    "简介": { "zh": "汴绣历史悠久。", "en": "Bian embroidery has a long history." },
    "主要特色": { "zh": "针法细腻，设色典雅。", "en": "Fine stitches and elegant colors." }
  }
}"""
    result = _parse_bilingual_json(raw)
    assert result is not None
    assert result["fields"]["名称"]["zh"] == "汴绣"
    assert result["fields"]["名称"]["en"] == "Bian Embroidery"


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
  "speech_en": "This is the spoken version.",
  "fields": {
    "名称": { "zh": "名称", "en": "EN" },
    "类别": { "zh": "类别", "en": "EN" },
    "简介": { "zh": "简介", "en": "EN" },
    "主要特色": { "zh": "特色", "en": "EN" }
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
  "speech_en": "spoken",
  "fields": {
    "名称": { "zh": "名称", "en": "Name" },
    "类别": { "zh": "类别", "en": "Category" }
  }
}"""
    result = _parse_bilingual_json(raw)
    assert result is None
