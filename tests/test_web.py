from heritage_explorer import config
from heritage_explorer.web import create_app


def test_homepage_contains_digital_human_panel():
    app = create_app()
    client = app.test_client()
    response = client.get("/")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'id="digitalHumanVideo"' in html
    assert "xuhua-idle.mp4" in html
    assert 'id="voiceEnabled"' in html
    assert 'id="voiceStatus"' in html
    assert 'id="voiceReplayButton"' not in html


def test_items_api_returns_payload():
    app = create_app()
    client = app.test_client()
    response = client.get("/api/items?q=皮影戏&limit=3")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] > 0
    assert len(payload["items"]) <= 3


def test_ask_api_returns_grounded_answer(monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "")
    app = create_app()
    client = app.test_client()
    response = client.post("/api/ask", json={"question": "陈氏太极拳是什么"})
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["mode"] == "local"
    assert "太极拳" in payload["answer"]
    assert payload["sources"]
