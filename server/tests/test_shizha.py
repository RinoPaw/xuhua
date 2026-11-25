import asyncio
from pathlib import Path

from fastapi.testclient import TestClient

from heritage_explorer import api
from heritage_explorer.admission import AdmissionController, AdmissionPolicy
from heritage_explorer.assistant import AssistantService, SearchService
from heritage_explorer.dataset import item_to_dict
from heritage_explorer.shizha import create_assistant, load_knowledge_base, normalize_asr_final
from heritage_explorer.shizha_api import create_shizha_app
from heritage_explorer.voice_session import build_voice_hotwords, is_assistant_address_only


def test_case_data_uses_shared_models_and_preserves_source_fields():
    kb = load_knowledge_base()
    assert len(kb.items) == 86
    assert len(kb.categories) == 8
    payload = item_to_dict(kb.get("FZ-001"), include_content=True)
    assert payload["case_id"] == "FZ-001"
    assert payload["risk_level"]
    assert payload["source_name"]
    assert payload["key_methods"]
    assert payload["prevention_advice"]
    assert "\u8d44\u6599\u6765\u6e90" in payload["content"]


def test_xuhua_and_shizha_are_independent_applications_and_sessions():
    heritage_app = api.create_app()
    case_app = create_shizha_app()

    with TestClient(heritage_app) as heritage, TestClient(case_app) as cases:
        heritage_meta = heritage.get("/api/meta").json()
        case_meta = cases.get("/api/meta").json()
        assert heritage_meta["agent_name"] == "\u53d9\u534e"
        assert heritage_meta["item_count"] >= 3000
        assert case_meta["agent_name"] == "\u8bc6\u8bc8"
        assert case_meta["item_count"] == 86
        assert case_meta["risk_levels"] and case_meta["entry_channels"] and case_meta["victim_groups"]

        assert heritage.get("/api/items/FZ-001").status_code == 404
        assert cases.get("/api/items/FZ-001").json()["case_id"] == "FZ-001"
        heritage_id = heritage.get("/api/items?limit=1").json()["items"][0]["id"]
        assert cases.get(f"/api/items/{heritage_id}").status_code == 404

        for client in (heritage, cases):
            response = client.post(
                "/api/chat",
                json={"question": "\u4f60\u597d", "session_id": "same-client-id"},
            )
            assert response.status_code == 200

        heritage_history = heritage_app.state.assistant.sessions.history("same-client-id")
        case_history = case_app.state.assistant.sessions.history("same-client-id")
        assert len(heritage_history) == len(case_history) == 1
        assert "\u975e\u9057" in heritage_history[0].answer
        assert "\u8bc6\u8bc8" in case_history[0].answer
        assert heritage_app.state.assistant.sessions is not case_app.state.assistant.sessions
        assert heritage_app.state.admission is not case_app.state.admission
        assert cases.get("/api/wake/status").status_code == 404


def test_case_yunxia_provider_is_separate_from_heritage_xfyun(monkeypatch):
    calls = []

    class Edge:
        def __init__(self, text, **kwargs):
            calls.append(("edge", kwargs["voice"]))

        async def stream(self):
            yield {"type": "audio", "data": b"yunxia-audio"}

    class Xfyun:
        def __init__(self, text, **kwargs):
            calls.append(("xfyun", kwargs["voice"]))

        async def stream(self):
            yield {"type": "audio", "data": b"xiaolu-audio"}

    monkeypatch.setattr(api.edge_tts, "Communicate", Edge)
    monkeypatch.setattr(api.xfyun_tts, "Communicate", Xfyun)

    with TestClient(create_shizha_app()) as cases, TestClient(api.create_app()) as heritage:
        case_meta = cases.get("/api/meta").json()["capabilities"]
        assert case_meta["tts_provider"] == "edge"
        assert case_meta["tts_voice"] == "zh-CN-YunxiaNeural"

        case_token = cases.post(
            "/api/tts", json={"text": "\u6d4b\u8bd5", "locale": "zh-CN"}
        ).json()["token"]
        case_response = cases.get(f"/api/tts/{case_token}?stream=1")
        assert case_response.status_code == 200
        assert case_response.content == b"yunxia-audio"
        assert case_response.headers["x-speech-voice"] == "zh-CN-YunxiaNeural"

        heritage_token = heritage.post(
            "/api/tts", json={"text": "\u6d4b\u8bd5", "locale": "zh-CN"}
        ).json()["token"]
        heritage_response = heritage.get(f"/api/tts/{heritage_token}?stream=1")
        assert heritage_response.status_code == 200
        assert heritage_response.content == b"xiaolu-audio"

    assert calls[0] == ("edge", "zh-CN-YunxiaNeural")
    assert calls[1][0] == "xfyun"


def test_case_filters_and_shared_search_return_matching_cases():
    with TestClient(create_shizha_app()) as client:
        detail = client.get("/api/items/FZ-001").json()
        response = client.get(
            "/api/items",
            params={"risk_level": detail["risk_level"], "limit": 100},
        )
        assert response.json()["total"] > 0
        assert all(row["risk_level"] == detail["risk_level"] for row in response.json()["items"])

        cases = client.get("/api/items", params={"q": "\u5237\u5355\u8fd4\u5229"}).json()
        assert cases["total"] > 0
        assert any(
            "\u5237\u5355" in row["category"] or "\u5237\u5355" in row["title"]
            for row in cases["items"]
        )
        assert client.get(
            "/api/items", params={"victim_group": "\u4e0d\u5b58\u5728\u7684\u4eba\u7fa4"}
        ).json()["total"] == 0


def test_case_voice_names_do_not_consume_real_questions_or_heritage_name():
    names = ("\u8bc6\u8bc8", "\u718a\u732b\u8b66\u5b98")
    for name in ("\u8bc6\u8bc8", "\u4f60\u597d\u8bc6\u8bc8", "\u718a\u732b\u8b66\u5b98\u4f60\u5728\u5417"):
        assert is_assistant_address_only(name, names)
    for question in (
        "\u53d9\u534e",
        "\u8bc6\u8bc8\u4ecb\u7ecd\u4e00\u4e0b\u5237\u5355\u8fd4\u5229",
        "\u718a\u732b\u8b66\u5b98\uff0c\u6211\u6b63\u5728\u8f6c\u8d26",
    ):
        assert not is_assistant_address_only(question, names)
    assert normalize_asr_final("\u65f6\u5dee\u3002").canonical_text == "\u8bc6\u8bc8\u3002"
    assert normalize_asr_final("\u4ec0\u4e48\u662f\u65f6\u5dee\uff1f").canonical_text == "\u4ec0\u4e48\u662f\u65f6\u5dee\uff1f"
    assert normalize_asr_final("\u8bb8\u534e\u3002", kb=load_knowledge_base()).canonical_text == "\u8bb8\u534e\u3002"
    assert build_voice_hotwords("", [], [], names) == names


def test_prompt_and_urgent_response_use_shared_stream_and_no_heritage_identity():
    class RecordingLLM:
        def __init__(self):
            self.calls = []

        async def stream_chat(self, messages, **kwargs):
            self.calls.append(messages)
            yield "\u6ce8\u610f\u5237\u5355\u8fd4\u5229\u7684\u98ce\u9669\u4fe1\u53f7\u3002"

    async def scenario():
        llm = RecordingLLM()
        assistant = create_assistant(llm=llm)
        assert type(assistant) is AssistantService
        assert isinstance(assistant.search, SearchService)
        events = [
            event
            async for event in assistant.stream_turn(
                "\u5237\u5355\u8fd4\u5229\u6709\u54ea\u4e9b\u98ce\u9669\uff1f",
                session_id="case",
            )
        ]
        assert events[-1].type == "turn.completed"
        assert llm.calls
        assert "\u4f60\u662f\u8bc6\u8bc8" in llm.calls[0][0]["content"]
        assert "\u975e\u7269\u8d28\u6587\u5316\u9057\u4ea7" not in llm.calls[0][0]["content"]
        assert any("\u8d44\u6599\u6765\u6e90" in message["content"] for message in llm.calls[0])

        count = len(llm.calls)
        urgent = [
            event
            async for event in assistant.stream_turn(
                "\u5bf9\u65b9\u8ba9\u6211\u5171\u4eab\u5c4f\u5e55\u5e76\u63d0\u4f9b\u9a8c\u8bc1\u7801",
                session_id="case",
            )
        ]
        assert urgent[-1].type == "turn.completed"
        assert "\u505c\u6b62" in urgent[-1].payload["answer"]
        assert len(llm.calls) == count

    asyncio.run(scenario())


def test_case_routes_enforce_independent_body_and_admission_limits():
    admission = AdmissionController({"chat": AdmissionPolicy(2, 1, 1)})
    with TestClient(create_shizha_app(admission=admission)) as cases:
        assert cases.post(
            "/api/chat",
            content=b"x" * 70000,
            headers={"Content-Type": "application/json"},
        ).status_code == 413
        assert cases.post("/api/chat", json={"question": "\u4f60\u597d"}).status_code == 200
        assert cases.post("/api/chat", json={"question": "\u4f60\u597d"}).status_code == 429

    with TestClient(api.create_app()) as heritage:
        assert heritage.post("/api/chat", json={"question": "\u4f60\u597d"}).status_code == 200


def test_case_voice_uses_its_own_websocket_and_acknowledgement(monkeypatch):
    class Stream:
        detected_language = "zh"
        candidates = ()

        def __init__(self, **kwargs):
            assert kwargs["hotwords"][0:2] == ("\u8bc6\u8bc8", "\u718a\u732b\u8b66\u5b98")

        async def start(self):
            pass

        async def send_audio(self, data):
            pass

        async def finish(self):
            return "\u718a\u732b\u8b66\u5b98"

        async def close(self):
            pass

    monkeypatch.setattr(api, "XF_APP_ID", "test")
    monkeypatch.setattr(api, "XF_API_KEY", "test")
    monkeypatch.setattr(api, "XF_API_SECRET", "test")
    monkeypatch.setattr(api, "XfyunStream", Stream)

    with TestClient(create_shizha_app()) as client:
        with client.websocket_connect("/api/voice") as ws:
            assert ws.receive_json()["type"] == "ready"
            ws.send_json({"type": "utterance.start"})
            ws.send_json({"type": "utterance.end"})
            while True:
                event = ws.receive_json()
                assert event["type"] != "error", event
                if event["type"] == "assistant.done":
                    assert event["text"] == "\u6211\u5728\u3002"
                    assert event["acknowledgement"] is True
                    break


def test_deployment_defines_separate_shizha_process_and_routes():
    root = Path(__file__).resolve().parents[2]
    nginx = (root / "deploy/nginx-xuhua-https.conf").read_text(encoding="utf-8")
    service = (root / "deploy/shizha.service").read_text(encoding="utf-8")
    shizha_entry = (root / "deploy/shizha_asgi.py").read_text(encoding="utf-8")

    assert "create_shizha_app" in shizha_entry
    assert "shizha_asgi:app" in service
    assert "--port 5051" in service
    assert "After=xuhua.service" not in service
    assert "location ^~ /shizha/api/" in nginx
    assert "proxy_pass http://127.0.0.1:5051/api/;" in nginx
    assert "location ^~ /shizha/" in nginx
    assert "proxy_pass http://127.0.0.1:5051/;" in nginx
    assert "alias /opt/xuhua/web/dist/client/assets/;" in nginx
