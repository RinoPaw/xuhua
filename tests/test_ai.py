from heritage_explorer.ai import answer_question
from heritage_explorer import config
from heritage_explorer.dataset import load_dataset


def test_local_answer_uses_sources(monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "")
    kb = load_dataset()
    answer = answer_question(kb, "罗山皮影戏")
    assert answer.sources
    assert answer.mode == "local"
    assert "皮影" in answer.answer
