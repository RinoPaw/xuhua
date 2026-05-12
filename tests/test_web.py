import json
from pathlib import Path

from heritage_explorer import config
from heritage_explorer.web import create_app


ROOT = Path(__file__).resolve().parents[1]


def _sse_result(response):
    """Parse SSE response from /api/ask and return the result event as dict."""
    text = response.get_data(as_text=True)
    for line in text.split("\n"):
        if line.startswith("data: "):
            event = json.loads(line[6:])
            if event.get("type") == "result":
                return event
    raise AssertionError("No result event in SSE response")


def _sse_events(response):
    text = response.get_data(as_text=True)
    events = []
    for line in text.split("\n"):
        if line.startswith("data: "):
            events.append(json.loads(line[6:]))
    return events


def test_homepage_contains_digital_human_panel():
    app = create_app()
    client = app.test_client()
    response = client.get("/")
    html = response.get_data(as_text=True)
    assert response.status_code == 200
    assert 'id="digitalHumanVideo"' in html
    assert "wait1.mp4" in html
    assert 'id="voiceToggle"' in html
    assert '播放或停止语音播报' in html
    assert 'voice-wave' not in html
    assert 'id="voiceStatus"' in html
    assert 'id="voiceReplayButton"' not in html
    assert 'id="querySuggestions"' in html
    assert "猜你想搜" in html
    assert 'id="relatedTitle"' in html
    assert "vendor/purify.min.js" in html
    assert "vendor/marked.umd.js" in html
    assert "20260512-speechfix" in html
    assert response.headers["Cache-Control"] == "no-store, max-age=0"


def test_static_assets_are_not_cached_during_local_development():
    app = create_app()
    client = app.test_client()
    response = client.get("/static/js/main.js")

    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store, max-age=0"


def test_digital_human_animation_waits_for_speech_end():
    consts = (ROOT / "static" / "js" / "consts.js").read_text(encoding="utf-8")
    ask_script = (ROOT / "static" / "js" / "ask.js").read_text(encoding="utf-8")
    speech_script = (ROOT / "static" / "js" / "speech.js").read_text(encoding="utf-8")

    assert "HUMAN_MIN_THINKING_MS" in consts
    assert "waitForThinkingDissolve(thinkingStartedAt)" in ask_script
    assert "finishSpeechPlayback" in speech_script
    assert "stopSpeech({ preserveHuman: true })" in ask_script
    assert "currentUtterance !== utterance" in speech_script
    assert "}, 7000)" not in speech_script + ask_script
    finish_block = speech_script.split("function finishSpeechPlayback", 1)[1].split("function stopSpeech", 1)[0]
    assert "options." not in finish_block


def test_voice_button_uses_play_stop_without_pause():
    speech_script = (ROOT / "static" / "js" / "speech.js").read_text(encoding="utf-8")
    main_script = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
    styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")

    assert 'label.textContent = { speaking: "停止", idle: "播放", disabled: "播放" }[state] || "播放";' in speech_script
    assert 'setVoiceStatus("已停止")' in main_script
    assert "window.speechSynthesis?.pause()" not in main_script
    assert '"paused"' not in main_script
    assert ".voice-button" in styles
    assert ".voice-toggle" not in styles
    assert ".voice-wave" not in styles


def test_voice_status_guard_does_not_overwrite_manual_stop():
    script = (ROOT / "static" / "js" / "speech.js").read_text(encoding="utf-8")

    assert "let speechStartGuardTimer = 0;" in script
    assert "function clearSpeechStartGuard()" in script
    assert 'finishSpeechPlayback("播报未启动")' in script
    stop_block = script.split("function stopSpeech", 1)[1].split("function unlockSpeech", 1)[0]
    assert "clearSpeechStartGuard();" in stop_block


def test_voice_idle_state_keeps_disabled_support_message():
    script = (ROOT / "static" / "js" / "speech.js").read_text(encoding="utf-8")

    assert "function syncVoiceIdleState(status = \"\")" in script
    sync_block = script.split("function syncVoiceIdleState", 1)[1].split("function speakAnswer", 1)[0]
    assert 'setVoiceState("disabled");' in sync_block
    assert 'setVoiceStatus("浏览器不支持语音");' in sync_block
    assert 'setVoiceState("idle");' in sync_block


def test_tts_text_strips_display_emoji():
    script = (ROOT / "static" / "js" / "speech.js").read_text(encoding="utf-8")

    assert "function stripSpeechDecorations(value)" in script
    assert "stripSpeechDecorations(value)" in script
    assert "\\u{1F300}-\\u{1FAFF}" in script
    assert "\\u{2600}-\\u{27BF}" in script
    speech_text_block = script.split("function speechText", 1)[1].split("function stripSpeechDecorations", 1)[0]
    assert "text.length > 720" not in speech_text_block


def test_frontend_prefers_server_tts_audio():
    speech_script = (ROOT / "static" / "js" / "speech.js").read_text(encoding="utf-8")
    ask_script = (ROOT / "static" / "js" / "ask.js").read_text(encoding="utf-8")
    consts_script = (ROOT / "static" / "js" / "consts.js").read_text(encoding="utf-8")

    assert "browserSpeechSupported" in consts_script
    assert "audioSpeechSupported" in consts_script
    assert "payload?.speech_audio_url" in speech_script
    assert "payload?.speech_audio_pending" in ask_script
    assert "function requestServerSpeech(text" in speech_script
    assert "function requestServerSpeechFile(text" in speech_script
    assert "function playSpeechSegment(index, playbackSeq)" in speech_script
    assert "function speechPlaybackSegments(text)" in speech_script
    assert "function utf8ByteLength(value)" in speech_script
    assert "function ttsStreamUrl(text)" in speech_script
    assert 'return `/api/tts/stream?${params.toString()}`;' in speech_script
    assert 'fetch("/api/tts"' in speech_script
    assert "function playAudioAnswer(audioUrl" in speech_script
    assert "onEnd: () => playSpeechSegment(index + 1, playbackSeq)" in speech_script
    assert "onError: () => requestServerSpeechFile(currentSpeechSegments.slice(index).join(\"\"), playbackSeq)" in speech_script
    assert "new Audio(audioUrl)" in speech_script
    assert "speakAnswer(speech, speechAudioUrl, { serverTts: speechAudioPending })" in ask_script
    assert "speakText(fallbackText, playbackSeq)" in speech_script


def test_loading_progress_uses_fixed_event_driven_steps():
    ask_script = (ROOT / "static" / "js" / "ask.js").read_text(encoding="utf-8")
    consts_script = (ROOT / "static" / "js" / "consts.js").read_text(encoding="utf-8")
    start_block = ask_script.split("function startLoadingSteps", 1)[1].split("function getLoadingSteps", 1)[0]
    progress_block = ask_script.split("function applyAskProgress", 1)[1].split("function renderSuggestionStrip", 1)[0]

    assert "let loadingStepIndex = 0;" in ask_script
    assert "let loadingTargetIndex = 0;" in ask_script
    assert "const loadingSteps = [" in consts_script
    assert '{ title: "理解问题"' in consts_script
    assert '{ title: "检索资料"' in consts_script
    assert '{ title: "思考回答"' in consts_script
    assert '{ title: "润色播报"' in consts_script
    assert "const LOADING_MIN_STEP_MS = 500;" in consts_script
    assert "window.setInterval" not in start_block
    assert "loadingProgressQueue.push(index);" in progress_block
    assert "scheduleNextLoadingStep();" in progress_block
    assert "function waitForLoadingSteps()" in ask_script
    assert "await waitForLoadingSteps();" in ask_script
    assert "title: event.title" not in progress_block
    assert "let stepIndex = 0;" not in ask_script


def test_ask_flow_uses_request_guards_and_single_sse_path():
    ask_script = (ROOT / "static" / "js" / "ask.js").read_text(encoding="utf-8")
    state_script = (ROOT / "static" / "js" / "state.js").read_text(encoding="utf-8")
    main_script = (ROOT / "static" / "js" / "main.js").read_text(encoding="utf-8")
    search_script = (ROOT / "static" / "js" / "search.js").read_text(encoding="utf-8")

    assert "let askRequestId = 0;" in ask_script
    assert "function beginAskSession(question)" in ask_script
    assert "askAbortController?.abort();" in ask_script
    assert "stopSpeech({ preserveHuman: true });" in ask_script
    assert "function isActiveAskRequest(requestId, controller = askAbortController)" in ask_script
    assert "await presentAskResponse(session.requestId, session.controller, question, payload, session.thinkingStartedAt);" in ask_script
    assert "presentAskError(session.requestId, session.controller, error);" in ask_script
    assert "voice_enabled: speechSupported" in ask_script
    assert "lastAskContext: null" in state_script
    assert "function buildAskContext(question)" in ask_script
    assert "requestData.context = context;" in ask_script
    assert "rememberAskContext(question, payload);" in ask_script
    assert "async function postJson" not in ask_script
    assert 'answerMode.textContent = "正在识别任务";' in ask_script
    assert "setAnswerResult(question, payload);" in ask_script
    assert "renderQuerySuggestions();" in main_script
    assert "beginAskSessionRelated(requestId);" in ask_script
    assert "beginAskSessionRelated" in search_script


def test_digital_human_caption_does_not_show_answer_text():
    human_script = (ROOT / "static" / "js" / "human.js").read_text(encoding="utf-8")
    ask_script = (ROOT / "static" / "js" / "ask.js").read_text(encoding="utf-8")
    speech_script = (ROOT / "static" / "js" / "speech.js").read_text(encoding="utf-8")
    search_script = (ROOT / "static" / "js" / "search.js").read_text(encoding="utf-8")
    consts_script = (ROOT / "static" / "js" / "consts.js").read_text(encoding="utf-8")
    joined = ask_script + human_script + speech_script + search_script + consts_script
    state_block = human_script.split("function setDigitalHumanState", 1)[1].split("function transitionHumanVideo", 1)[0]

    assert "digitalHumanCaption" in state_block
    assert "compactSpeech" not in joined
    assert "我先从资料库里找和问题最相关的内容。" in human_script + ask_script
    assert 'setDigitalHumanState("thinking", "正在思考"' in ask_script
    assert 'relatedCount.textContent = "思考中"' in search_script
    assert 'relatedList.innerHTML = `<p class="marginalia-empty is-live">正在思考</p>`' in search_script
    assert 'askButton.textContent = "提问"' in ask_script
    assert 'const text = withThinkingVoice ? "正在检索" : "语音播报已准备";' in speech_script
    assert "理解问题" in consts_script + ask_script
    assert "思考回答" in consts_script + ask_script
    assert "进入思考" not in joined
    assert "我先想一想。" not in joined
    assert "正在为你讲述。" in human_script


def test_digital_human_thinking_state_has_mask():
    styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")

    assert '.hanging-scroll[data-state="thinking"] .scroll-body::after' in styles
    assert "rgba(36, 88, 74, 0.72)" in styles
    assert '.hanging-scroll[data-state="speaking"] .scroll-body::after' in styles


def test_result_markdown_lists_keep_visible_markers():
    styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")

    assert ".result-markdown ul," in styles
    assert ".result-markdown ol {" in styles
    assert "padding-left: 1.65em;" in styles
    assert "list-style: decimal;" in styles


def test_result_markdown_uses_mature_engine_with_sanitizer():
    script = (ROOT / "static" / "js" / "markdown.js").read_text(encoding="utf-8")
    styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")

    assert "window.marked" in script
    assert "window.DOMPurify" in script
    assert "function normalizeMarkdownSource(value)" in script
    assert 'replace(/\\\\([*_`~])/g, "$1")' in script
    assert "markedEngine.parse(source" in script
    assert "sanitizer.sanitize(rawHtml)" in script
    assert "renderMarkdownFallback(source)" in script
    assert "gfm: true" in script
    assert "breaks: true" in script
    assert ".result-markdown table" in styles
    assert ".result-markdown blockquote" in styles


def test_item_cards_use_title_and_family_fields():
    search_script = (ROOT / "static" / "js" / "search.js").read_text(encoding="utf-8")
    ask_script = (ROOT / "static" / "js" / "ask.js").read_text(encoding="utf-8")

    assert "function itemTitle(item)" in search_script
    assert "item?.family" in search_script
    assert "官方名称：" not in search_script + ask_script
    assert "detailTitle.textContent = itemTitle(item);" in search_script
    assert "escapeHtml(itemTitle(item))" in ask_script


def test_result_items_render_all_returned_items():
    script = (ROOT / "static" / "js" / "ask.js").read_text(encoding="utf-8")
    render_block = script.split("function renderResultItems", 1)[1].split("function renderSelectionReason", 1)[0]

    assert "items.map((item)" in render_block
    assert "items.slice(0, 6)" not in render_block
    assert "重点项目${itemCountLabel}" in render_block


def test_answer_result_area_remains_scrollable():
    styles = (ROOT / "static" / "styles.css").read_text(encoding="utf-8")
    answer_block = styles.split(".answer-scroll {", 1)[1].split(".answer-scroll::-webkit-scrollbar", 1)[0]

    assert "overflow: auto;" in answer_block
    assert "min-height: 0;" in answer_block


def test_all_digital_human_video_states_use_dissolve_scheduler():
    script = (ROOT / "static" / "js" / "human.js").read_text(encoding="utf-8")

    assert "video.loop = false" in script
    assert "scheduleHumanVideoAdvance" in script
    assert "scheduleIdleAdvance" not in script
    assert "HUMAN_DISSOLVE_LEAD_MS" in script
    assert "allowSame: true" in script
    assert "force: true" in script


def test_agent_progress_uses_search_wording_outside_preserved_thinking_states():
    agent_source = (ROOT / "src" / "heritage_explorer" / "agent" / "__init__.py").read_text(encoding="utf-8")

    assert 'self._progress_event("search", "检索资料"' in agent_source
    assert '"title": "思考资料"' not in agent_source


def test_items_api_returns_payload():
    app = create_app()
    client = app.test_client()
    response = client.get("/api/items?q=汴绣&limit=3")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["total"] > 0
    assert len(payload["items"]) <= 3
    item = payload["items"][0]
    assert "level" in item
    assert "display_forms" in item
    assert "cultural_keywords" in item
    assert "family" in item
    assert "aliases" not in item
    assert "official_title" not in item
    assert "display_title" not in item
    assert "title_family" not in item


def test_items_api_returns_normalized_title_and_family():
    app = create_app()
    client = app.test_client()
    response = client.get("/api/items?q=滑县木版年画&limit=5")
    assert response.status_code == 200
    payload = response.get_json()
    item = next(item for item in payload["items"] if item["title"] == "滑县木版年画")

    assert item["family"] == "木版年画"
    assert "aliases" not in item
    assert "official_title" not in item
    assert "display_title" not in item
    assert "title_family" not in item


def test_item_detail_returns_enriched_metadata():
    app = create_app()
    client = app.test_client()
    search_response = client.get("/api/items?q=汴绣&limit=1")
    item = search_response.get_json()["items"][0]

    response = client.get(f"/api/items/{item['id']}")
    assert response.status_code == 200
    payload = response.get_json()
    assert payload["title"]
    assert "content" in payload
    assert "level" in payload
    assert "display_forms" in payload


def test_ask_api_returns_grounded_answer(monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "")
    app = create_app()
    client = app.test_client()
    response = client.post("/api/ask", json={"question": "陈氏太极拳是什么"})
    assert response.status_code == 200
    payload = _sse_result(response)
    assert payload["mode"] == "local"
    assert "太极拳" in payload["answer"]
    assert payload["speech"]
    assert payload["sources"]


def test_ask_api_marks_server_tts_without_blocking_result(monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "")
    monkeypatch.setattr("heritage_explorer.web.volc_tts_available", lambda: True)
    monkeypatch.setattr(
        "heritage_explorer.web.synthesize_speech_to_file",
        lambda _speech: (_ for _ in ()).throw(AssertionError("ask should not synthesize audio")),
    )
    app = create_app()
    client = app.test_client()
    response = client.post("/api/ask", json={"question": "陈氏太极拳是什么"})
    payload = _sse_result(response)

    assert payload["speech_engine"] == "volcengine"
    assert payload["speech_audio_pending"] is True
    assert "speech_audio_url" not in payload


def test_tts_create_route_returns_audio_url(monkeypatch, tmp_path):
    from types import SimpleNamespace

    filename = f"{'a' * 64}.mp3"
    audio_path = tmp_path / filename
    audio_path.write_bytes(b"mp3")

    def fake_tts(speech: str):
        assert speech == "汴绣适合现场讲解。"
        return SimpleNamespace(path=audio_path, mime_type="audio/mpeg", engine="volcengine")

    monkeypatch.setattr("heritage_explorer.web.synthesize_speech_to_file", fake_tts)
    app = create_app()
    client = app.test_client()
    response = client.post("/api/tts", json={"text": "汴绣适合现场讲解。"})

    assert response.status_code == 200
    payload = response.get_json()
    assert payload["speech_audio_url"] == f"/api/tts/{filename}"
    assert payload["speech_mime_type"] == "audio/mpeg"
    assert payload["speech_engine"] == "volcengine"


def test_tts_audio_route_serves_cached_mp3(monkeypatch, tmp_path):
    filename = f"{'b' * 64}.mp3"
    (tmp_path / filename).write_bytes(b"mp3")
    monkeypatch.setattr("heritage_explorer.web.TTS_CACHE_DIR", tmp_path)

    app = create_app()
    client = app.test_client()
    response = client.get(f"/api/tts/{filename}")

    assert response.status_code == 200
    assert response.mimetype == "audio/mpeg"
    assert response.get_data() == b"mp3"


def test_tts_stream_route_streams_audio(monkeypatch):
    monkeypatch.setattr("heritage_explorer.web.stream_speech_audio", lambda text: iter([b"mp", text.encode()]))

    app = create_app()
    client = app.test_client()
    response = client.get("/api/tts/stream?text=3")

    assert response.status_code == 200
    assert response.mimetype == "audio/mpeg"
    assert response.headers["Cache-Control"] == "no-cache"
    assert response.get_data() == b"mp3"


def test_ask_api_uses_previous_context_for_short_transform_followup(monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "")
    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/ask",
        json={
            "question": "再生成一个更年轻化的版本",
            "voice_enabled": False,
            "context": {
                "question": "给朱仙镇木版年画生成讲解词",
                "answer": "## 朱仙镇木版年画 · 讲解词\n\n朱仙镇木版年画是开封地区的传统美术项目。",
                "items": [{"id": "x", "title": "朱仙镇木版年画", "category": "传统美术"}],
            },
        },
    )
    assert response.status_code == 200
    payload = _sse_result(response)

    assert payload["task_type"] == "content_transform"
    assert payload["items"][0]["title"] == "朱仙镇木版年画"
    assert "朱仙镇木版年画" in payload["answer"]
    assert "缺少原始文本" not in payload["answer"]


def test_ask_api_omits_speech_progress_when_voice_disabled(monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "")
    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/ask",
        json={"question": "陈氏太极拳是什么", "voice_enabled": False},
    )
    assert response.status_code == 200
    events = _sse_events(response)
    progress_steps = [event.get("step") for event in events if event.get("type") == "progress"]
    result = next(event for event in events if event.get("type") == "result")

    assert "speech" not in progress_steps
    assert result["speech"] == ""
    assert result["answer"]


def test_ask_api_handles_greeting_without_retrieval_or_model(monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "should-not-be-needed")
    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/ask",
        json={"question": "你好", "voice_enabled": False},
    )
    assert response.status_code == 200
    payload = _sse_result(response)

    assert payload["task_type"] == "chitchat"
    assert payload["task_label"] == "对话回应"
    assert payload["mode"] == "local"
    assert "我在这里" in payload["answer"]
    assert payload["speech"] == ""
    assert payload["items"] == []
    assert payload["sources"] == []
    assert payload["evidence"] == []
    assert payload["decision"]["needs_retrieval"] is False
    assert payload["decision"]["needs_llm"] is False


def test_ask_api_handles_identity_question_without_retrieval_or_model(monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "should-not-be-needed")
    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/ask",
        json={"question": "你是谁", "voice_enabled": False},
    )
    assert response.status_code == 200
    payload = _sse_result(response)

    assert payload["task_type"] == "chitchat"
    assert payload["task_label"] == "对话回应"
    assert payload["mode"] == "local"
    assert "我是叙华" in payload["answer"]
    assert "水晶雕刻" not in payload["answer"]
    assert payload["speech"] == ""
    assert payload["items"] == []
    assert payload["sources"] == []
    assert payload["evidence"] == []
    assert payload["decision"]["reason"]
    assert payload["decision"]["needs_retrieval"] is False


def test_ask_api_handles_knowledge_inventory_as_agent_capability(monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "should-not-be-needed")
    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/ask",
        json={"question": "你知道什么", "voice_enabled": False},
    )
    assert response.status_code == 200
    payload = _sse_result(response)

    assert payload["task_type"] == "chitchat"
    assert payload["task_label"] == "对话回应"
    assert payload["mode"] == "local"
    assert "非遗项目" in payload["answer"]
    assert "筛选" in payload["answer"]
    assert "这个问题看起来不属于" not in payload["answer"]
    assert payload["speech"] == ""
    assert payload["decision"]["needs_retrieval"] is False
    assert payload["decision"]["needs_llm"] is False


def test_ask_api_skips_model_for_out_of_scope_question(monkeypatch):
    monkeypatch.setattr(config, "AI_API_KEY", "should-not-be-needed")
    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/ask",
        json={"question": "天气怎么样", "voice_enabled": False},
    )
    assert response.status_code == 200
    payload = _sse_result(response)

    assert payload["task_type"] == "fact_qa"
    assert payload["mode"] == "no_context"
    assert "非遗资料库" in payload["answer"]
    assert payload["speech"] == ""
    assert payload["sources"] == []
    assert payload["items"] == []
    assert payload["warnings"]
    assert payload["decision"]["needs_retrieval"] is False
    assert payload["decision"]["needs_llm"] is False


# ── MVP E2E demo tests ──


def test_e2e_browse_query_returns_items(monkeypatch):
    """A. BROWSE_QUERY: 河南有哪些传统美术？"""
    monkeypatch.setattr(config, "AI_API_KEY", "")
    app = create_app()
    client = app.test_client()
    response = client.post("/api/ask", json={"question": "河南有哪些传统美术"})
    assert response.status_code == 200

    payload = _sse_result(response)

    # task classification
    assert payload["task_type"] == "browse_query"
    assert payload["mode"] == "local"

    # answer
    assert "找到" in payload["answer"]
    assert "传统美术" in payload["answer"]

    # items
    assert isinstance(payload["items"], list)
    assert len(payload["items"]) > 0
    assert "title" in payload["items"][0]
    assert "category" in payload["items"][0]

    # evidence — only source type or empty
    for ev in payload["evidence"]:
        assert ev["type"] in ("source", "inferred")

    # new fields present
    assert isinstance(payload["selection_reason"], str)
    assert isinstance(payload["warnings"], list)

    # legacy fields present
    assert payload["answer"]
    assert isinstance(payload["sources"], list)
    assert isinstance(payload["confidence"], (int, float))


def test_e2e_recommendation_returns_items(monkeypatch):
    """B. RECOMMENDATION: 推荐三个适合校园展示的非遗项目"""
    monkeypatch.setattr(config, "AI_API_KEY", "")
    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/ask",
        json={"question": "推荐三个适合校园展示的非遗项目"},
    )
    assert response.status_code == 200

    payload = _sse_result(response)

    assert payload["task_type"] == "recommendation"
    assert len(payload["items"]) >= 1
    assert payload["selection_reason"]
    assert not any("error" in str(w).lower() for w in payload["warnings"])

    # evidence should contain at least inferred items
    assert len(payload["evidence"]) >= 1
    for ev in payload["evidence"]:
        assert ev["type"] in ("source", "inferred")
        assert "item_id" in ev

    # legacy fields
    assert payload["answer"]
    assert payload["speech"] is not None
    assert isinstance(payload["sources"], list)


def test_e2e_exhibition_plan_returns_template(monkeypatch):
    """C. EXHIBITION_PLAN: 帮我策划一个河南非遗校园展"""
    monkeypatch.setattr(config, "AI_API_KEY", "")
    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/ask",
        json={"question": "帮我策划一个河南非遗校园展"},
    )
    assert response.status_code == 200

    payload = _sse_result(response)

    assert payload["task_type"] == "exhibition_plan"

    # answer should contain exhibition structure
    answer = payload["answer"]
    assert any(kw in answer for kw in ["展项", "展示", "方案"])

    # items non-empty
    assert isinstance(payload["items"], list)
    assert len(payload["items"]) >= 1

    # mode should not be an error
    assert payload["mode"] in ("fallback", "llm", "local")

    # warnings should not contain fatal errors
    for w in payload["warnings"]:
        assert "error" not in str(w).lower()

    # legacy compat
    assert payload["answer"]
    assert isinstance(payload["sources"], list)


def test_ask_api_new_fields_always_present(monkeypatch):
    """New fields items/evidence/selection_reason/warnings always present."""
    monkeypatch.setattr(config, "AI_API_KEY", "")
    app = create_app()
    client = app.test_client()

    # test with FACT_QA (fallthrough)
    response = client.post(
        "/api/ask",
        json={"question": "太极拳的哲学基础是什么"},
    )
    assert response.status_code == 200
    payload = _sse_result(response)

    assert "items" in payload
    assert "evidence" in payload
    assert "selection_reason" in payload
    assert "warnings" in payload
    assert isinstance(payload["items"], list)
    assert isinstance(payload["evidence"], list)
    assert isinstance(payload["selection_reason"], str)
    assert isinstance(payload["warnings"], list)

    # legacy still works
    assert payload["answer"]
    assert "speech" in payload
    assert "mode" in payload
    assert "task_type" in payload
    assert "task_label" in payload
    assert "confidence" in payload
    assert "sources" in payload


# ── API contract hardening tests ──


def test_recommend_enforces_item_count_three(monkeypatch):
    """推荐三个 → items 长度 = 3，非默认 10。"""
    monkeypatch.setattr(config, "AI_API_KEY", "")
    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/ask",
        json={"question": "推荐三个适合校园展示的非遗项目"},
    )
    assert response.status_code == 200
    payload = _sse_result(response)

    assert payload["task_type"] == "recommendation"
    assert len(payload["items"]) == 3
    assert payload["selection_reason"]


def test_recommend_enforces_item_count_five(monkeypatch):
    """推荐五个 → items 长度 = 5。"""
    monkeypatch.setattr(config, "AI_API_KEY", "")
    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/ask",
        json={"question": "推荐五个适合社区活动的非遗项目"},
    )
    assert response.status_code == 200
    payload = _sse_result(response)
    assert len(payload["items"]) == 5


def test_recommend_digit_count_three(monkeypatch):
    """推荐3个 → items 长度 = 3。"""
    monkeypatch.setattr(config, "AI_API_KEY", "")
    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/ask",
        json={"question": "推荐3个适合校园展览的非遗"},
    )
    assert response.status_code == 200
    payload = _sse_result(response)
    assert len(payload["items"]) == 3


def test_browse_query_returns_total_count(monkeypatch):
    """BROWSE_QUERY 返回 total_count 字段。"""
    monkeypatch.setattr(config, "AI_API_KEY", "")
    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/ask",
        json={"question": "河南有哪些传统美术"},
    )
    assert response.status_code == 200
    payload = _sse_result(response)

    assert "total_count" in payload
    assert payload["total_count"] > 0
    # total_count should exceed items when truncated
    assert payload["total_count"] >= len(payload["items"])


def test_browse_query_truncation_warning(monkeypatch):
    """总匹配数超过展示限制时 warnings 提示截断。"""
    monkeypatch.setattr(config, "AI_API_KEY", "")
    app = create_app()
    client = app.test_client()
    response = client.post(
        "/api/ask",
        json={"question": "列出河南省的传统技艺"},
    )
    assert response.status_code == 200
    payload = _sse_result(response)

    assert payload["total_count"] > 0
    has_truncation = any(
        "仅展示" in w for w in payload["warnings"]
    )
    # Only expect truncation warning when total > returned items
    if payload["total_count"] > len(payload["items"]):
        assert has_truncation
    else:
        # Small result sets don't need truncation warning
        pass
