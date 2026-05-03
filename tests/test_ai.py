import sys
import types

from heritage_explorer.ai import answer_question, build_context, build_speech_text
from heritage_explorer import config
from heritage_explorer.dataset import HeritageItem, load_dataset


def test_local_answer_uses_sources(monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "")
    kb = load_dataset()
    answer = answer_question(kb, "罗山皮影戏")
    assert answer.sources
    assert answer.mode == "local"
    assert "皮影" in answer.answer
    assert answer.speech


def test_fallback_answer_hides_provider_error(monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "test-key")
    monkeypatch.setattr(
        "heritage_explorer.ai.call_chat_model",
        lambda _question, _sources: (_ for _ in ()).throw(
            RuntimeError('APIReachLimitError: {"message":"该模型当前访问量过大"}')
        ),
    )

    kb = load_dataset()
    answer = answer_question(kb, "罗山皮影戏")

    assert answer.mode == "fallback"
    assert "模型服务暂时不可用" in answer.answer
    assert "APIReachLimitError" not in answer.answer
    assert "该模型当前访问量过大" not in answer.answer
    assert "错误：" not in answer.answer


def test_speech_text_removes_markdown_structure():
    speech = build_speech_text(
        "# 皮影戏\n\n"
        "## 信阳皮影戏\n"
        "- **类别**：传统戏剧\n"
        "- **历史**：清末民初开始流行。\n"
    )

    assert "#" not in speech
    assert "**" not in speech
    assert "-" not in speech
    assert "信阳皮影戏" in speech
    assert "它属于传统戏剧" in speech


def test_speech_text_is_rewritten_from_display_answer():
    kb = load_dataset()
    source = next(item for item in kb.items if item.title == "汴绣")

    speech = build_speech_text(
        "汴绣是中国传统刺绣技艺，已有千年历史。\n\n"
        "历史：汴绣起源于北宋时期，开封作为北宋都城，刺绣已发展到很高水平。\n\n"
        "技艺特点：汴绣针法多达36种，以针代笔，以彩线代墨。\n\n"
        "代表作品：巨幅绣品《清明上河图》是汴绣的优秀代表作。",
        question="汴绣",
        sources=[source],
    )

    assert speech.startswith("汴绣是中国传统刺绣技艺")
    assert "从历史来看，汴绣起源于北宋时期" in speech
    assert "在技艺特点上，汴绣针法多达36种" in speech
    assert "代表作品包括巨幅绣品《清明上河图》" in speech
    assert "代表作品包括巨幅绣品《清明上河图》是" not in speech
    assert "代表作品包括，" not in speech
    assert "开封市顺河回族区" not in speech
    assert "基本信息" not in speech
    assert "#" not in speech
    assert "**" not in speech


def test_speech_text_handles_standalone_sections_and_subitems():
    speech = build_speech_text(
        "皮影戏是中国传统戏剧艺术，历史悠久。\n\n"
        "历史：\n\n"
        "皮影戏起源可追溯至三皇五帝时期，历史悠久\n"
        "信阳皮影戏明末清初由山西传入，已有五代传承\n"
        "技艺特点：\n\n"
        "制作工艺：多用牛皮、驴皮，经过刻制上色等工序\n"
        "表演形式：艺人通过操纵皮影人配合唱腔、道白进行表演\n"
        "代表作品：\n\n"
        "信阳皮影戏剧目包括民间神话传说、历史典故等\n"
        "桐柏皮影戏：《隋唐演义》《七擒孟获》等七十余部\n"
        "传承价值：\n\n"
        "文化价值：承载丰富民风民俗，是民间口头文学和音乐艺术的宝贵资源",
    )

    assert "历史。" not in speech
    assert "技艺特点。" not in speech
    assert "代表作品。" not in speech
    assert "传承价值。" not in speech
    assert "从历史来看，皮影戏起源" in speech
    assert "在技艺特点上，制作工艺上，多用牛皮" in speech
    assert "表演形式上，艺人通过操纵皮影人" in speech
    assert "代表作品方面，信阳皮影戏有民间神话传说" in speech
    assert "代表作品方面，信阳皮影戏剧目包括" not in speech
    assert "从传承价值看，文化价值在于" in speech


def test_context_omits_backend_coordinate_fields():
    kb = load_dataset()
    source = next(item for item in kb.items if item.title == "汴绣")

    context = build_context([source], max_chars=3000)

    assert "汴绣" in context
    assert "114.374517" not in context
    assert "经纬度" not in context
    assert "电话" not in context


def test_zhipu_reasoning_models_disable_thinking(monkeypatch):
    from heritage_explorer.ai import call_zhipu_sdk

    captured = {}

    class FakeCompletions:
        def create(self, **kwargs):
            captured.update(kwargs)
            message = types.SimpleNamespace(content="智谱回答")
            choice = types.SimpleNamespace(message=message, finish_reason="stop")
            return types.SimpleNamespace(choices=[choice])

    class FakeClient:
        def __init__(self, **kwargs):
            captured["client"] = kwargs
            self.chat = types.SimpleNamespace(
                completions=FakeCompletions(),
            )

    monkeypatch.setitem(sys.modules, "zhipuai", types.SimpleNamespace(ZhipuAI=FakeClient))
    monkeypatch.setattr(config, "AI_API_KEY", "test-key")
    monkeypatch.setattr(config, "AI_BASE_URL", "https://open.bigmodel.cn/api/paas/v4")
    source = HeritageItem(
        id="shadow",
        title="皮影戏",
        category="传统戏剧",
        summary="皮影戏资料",
        content="皮影戏资料",
        aliases=(),
        search_text="皮影戏",
        source={},
    )

    for model in ("glm-4.5-flash", "glm-4.7-flash", "glm-5.1"):
        captured.clear()
        monkeypatch.setattr(config, "AI_MODEL", model)

        assert call_zhipu_sdk("皮影戏", [source]) == "智谱回答"
        assert captured["thinking"] == {"type": "disabled"}
