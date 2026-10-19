import asyncio

from fastapi.testclient import TestClient
from heritage_explorer import api
from heritage_explorer.assistant import AssistantService, SearchService
from heritage_explorer.dataset import item_to_dict
from heritage_explorer.shizha import create_assistant, load_knowledge_base, normalize_asr_final
from heritage_explorer.admission import AdmissionController, AdmissionPolicy
from heritage_explorer.voice_session import is_assistant_address_only, build_voice_hotwords


def test_case_data_uses_shared_models_and_preserves_source_fields():
    kb = load_knowledge_base()
    assert len(kb.items) == 86
    assert len(kb.categories) == 8
    item = kb.get("FZ-001")
    payload = item_to_dict(item, include_content=True)
    assert payload["case_id"] == "FZ-001"
    assert payload["risk_level"]
    assert payload["source_name"]
    assert payload["key_methods"]
    assert payload["prevention_advice"]
    assert "资料来源" in payload["content"]


def test_case_entry_serves_shared_html_without_redirects(tmp_path, monkeypatch):
    html = '<html><div id="root"></div><script src="/assets/shared.js"></script></html>'
    (tmp_path / "index.html").write_text(html, encoding="utf-8")
    monkeypatch.setattr(api, "FRONTEND_DIR", tmp_path)
    with TestClient(api.create_app()) as client:
        for path in ("/shizha", "/shizha/"):
            response = client.get(path, follow_redirects=False)
            assert response.status_code == 200
            assert response.text == html
            assert response.headers["content-type"].startswith("text/html")
        assert client.get("/shizha/api/meta").json()["item_count"] == 86


def test_shared_app_mounts_independent_case_apis_and_sessions():
    app = api.create_app()
    with TestClient(app) as client:
        assert client.get("/api/meta").json()["item_count"] >= 3000
        meta = client.get("/shizha/api/meta").json()
        assert meta["agent_name"] == "识诈"
        assert meta["item_count"] == 86
        assert meta["risk_levels"] and meta["entry_channels"] and meta["victim_groups"]
        assert client.get("/api/items/FZ-001").status_code == 404
        assert client.get("/shizha/api/items/FZ-001").json()["case_id"] == "FZ-001"
        heritage_id = client.get("/api/items?limit=1").json()["items"][0]["id"]
        assert client.get(f"/shizha/api/items/{heritage_id}").status_code == 404
        for prefix in ("", "/shizha"):
            response = client.post(prefix + "/api/chat", json={"question": "你好", "session_id": "same-client-id"})
            assert response.status_code == 200
        root = app.state.assistant.sessions.history("same-client-id")
        case = app.state.shizha.state.assistant.sessions.history("same-client-id")
        assert len(root) == len(case) == 1
        assert "非遗" in root[0].answer and "识诈" in case[0].answer
        assert app.state.assistant.sessions is not app.state.shizha.state.assistant.sessions
        assert app.state.admission is app.state.shizha.state.admission
        assert client.get("/shizha/api/wake/status").status_code == 404


def test_case_filters_and_shared_search_return_matching_cases():
    app = api.create_app()
    with TestClient(app) as client:
        detail = client.get("/shizha/api/items/FZ-001").json()
        response = client.get("/shizha/api/items", params={"risk_level": detail["risk_level"], "limit": 100})
        assert response.json()["total"] > 0
        assert all(row["risk_level"] == detail["risk_level"] for row in response.json()["items"])
        cases = client.get("/shizha/api/items", params={"q": "刷单返利"}).json()
        assert cases["total"] > 0
        assert any("刷单" in row["category"] or "刷单" in row["title"] for row in cases["items"])
        assert client.get("/shizha/api/items", params={"victim_group": "不存在的人群"}).json()["total"] == 0


def test_case_voice_names_do_not_consume_real_questions_or_heritage_name():
    names = ("识诈", "熊猫警官")
    for name in ("识诈", "你好识诈", "熊猫警官你在吗"):
        assert is_assistant_address_only(name, names)
    for question in ("叙华", "识诈介绍一下刷单返利", "熊猫警官，我正在转账"):
        assert not is_assistant_address_only(question, names)
    assert normalize_asr_final("时差。").canonical_text == "识诈。"
    assert normalize_asr_final("什么是时差？").canonical_text == "什么是时差？"
    assert normalize_asr_final("许华。", kb=load_knowledge_base()).canonical_text == "许华。"
    assert build_voice_hotwords("", [], [], names) == names


def test_prompt_and_urgent_response_use_shared_stream_and_no_heritage_identity():
    class RecordingLLM:
        def __init__(self):
            self.calls = []

        async def stream_chat(self, messages, **kwargs):
            self.calls.append(messages)
            yield "注意刷单返利的风险信号。"

    async def scenario():
        llm = RecordingLLM()
        assistant = create_assistant(llm=llm)
        assert type(assistant) is AssistantService
        assert isinstance(assistant.search, SearchService)
        events = [event async for event in assistant.stream_turn("刷单返利有哪些风险？", session_id="case")]
        assert events[-1].type == "turn.completed"
        assert llm.calls
        assert "你是识诈" in llm.calls[0][0]["content"]
        assert "非物质文化遗产" not in llm.calls[0][0]["content"]
        assert any("资料来源" in message["content"] for message in llm.calls[0])
        count = len(llm.calls)
        urgent = [event async for event in assistant.stream_turn("对方让我共享屏幕并提供验证码", session_id="case")]
        assert urgent[-1].type == "turn.completed"
        assert "停止" in urgent[-1].payload["answer"]
        assert len(llm.calls) == count
    asyncio.run(scenario())


def test_case_routes_enforce_shared_body_and_admission_limits():
    admission = AdmissionController({"chat": AdmissionPolicy(2, 1, 1)})
    app = api.create_app(admission=admission)
    with TestClient(app) as client:
        assert client.post("/shizha/api/chat", content=b"x" * 70000, headers={"Content-Type": "application/json"}).status_code == 413
        # Oversize bodies are rejected before consuming the shared chat budget.
        assert client.post("/shizha/api/chat", json={"question": "你好"}).status_code == 200
        assert client.post("/api/chat", json={"question": "你好"}).status_code == 429


def test_case_voice_uses_shared_websocket_and_acknowledgement(monkeypatch):
    class Stream:
        detected_language = "zh"
        candidates = ()
        def __init__(self, **kwargs):
            assert kwargs["hotwords"][0:2] == ("识诈", "熊猫警官")
        async def start(self): pass
        async def send_audio(self, data): pass
        async def finish(self): return "熊猫警官"
        async def close(self): pass
    monkeypatch.setattr(api, "XF_APP_ID", "test")
    monkeypatch.setattr(api, "XF_API_KEY", "test")
    monkeypatch.setattr(api, "XF_API_SECRET", "test")
    monkeypatch.setattr(api, "XfyunStream", Stream)
    app = api.create_app()
    with TestClient(app) as client:
        with client.websocket_connect("/shizha/api/voice") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "utterance.start"})
            ws.send_json({"type": "utterance.end"})
            while True:
                event = ws.receive_json()
                assert event["type"] != "error", event
                if event["type"] == "assistant.done":
                    assert event["text"] == "我在。"
                    assert event["acknowledgement"] is True
                    break
