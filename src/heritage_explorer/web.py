"""Flask web app for the heritage knowledge base."""

from __future__ import annotations

import json
import re

from flask import Flask, Response, abort, jsonify, render_template, request, send_file, stream_with_context

from .agent import Agent, AgentResult, task_type_label
from .config import DEBUG, HOST, PORT, TTS_CACHE_DIR
from .conversation import store as conv_store
from .dataset import get_knowledge_base, item_to_dict, normalize_text
from .search import search_items, search_items_lexical
from .volc_tts import (
    openai_tts_available,
    server_tts_available,
    server_tts_engine,
    stream_speech_audio,
    synthesize_speech_to_file,
    valid_tts_filename,
    volc_tts_available,
)


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="../../templates",
        static_folder="../../static",
    )

    app.logger.info(
        "TTS: engine=%s volc=%s openai=%s",
        server_tts_engine(),
        volc_tts_available(),
        openai_tts_available(),
    )

    @app.after_request
    def prevent_dev_cache(response):
        if request.path == "/" or request.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store, max-age=0"
            response.headers["Pragma"] = "no-cache"
        return response

    @app.get("/")
    def index():
        response = app.make_response(render_template("index.html"))
        response.headers["Cache-Control"] = "no-store, max-age=0"
        return response

    @app.get("/api/meta")
    def meta():
        kb = get_knowledge_base()
        return jsonify({
            "schema_version": kb.schema_version,
            "generated_at": kb.generated_at,
            "source": kb.source,
            "item_count": len(kb.items),
            "category_count": len(kb.categories),
        })

    @app.get("/api/categories")
    def categories():
        kb = get_knowledge_base()
        return jsonify([
            {"id": category.id, "name": category.name, "item_count": category.item_count}
            for category in kb.categories
        ])

    @app.get("/api/items")
    def items():
        kb = get_knowledge_base()
        query = request.args.get("q", "")
        category = request.args.get("category", "")
        province = request.args.get("province", "")
        level = request.args.get("level", "")
        district = request.args.get("district", "")
        keywords = request.args.get("keywords", "")
        limit = max(int(request.args.get("limit", "30")), 1)
        offset = max(int(request.args.get("offset", "0")), 0)

        if request.args.get("stream") == "1":
            return _stream_items(kb, query, category, province, level, district, keywords, limit, offset)

        result, total, _structured = _search_items_for_api(
            kb,
            query=query,
            category=category,
            province=province,
            level=level,
            district=district,
            keywords=keywords,
            limit=limit,
            offset=offset,
        )
        return jsonify({
            "total": total,
            "limit": limit,
            "offset": offset,
            "items": [_item_payload(item) for item in result],
        })

    @app.get("/api/items/<item_id>")
    def item_detail(item_id: str):
        kb = get_knowledge_base()
        item = kb.get(item_id)
        if item is None:
            abort(404)
        return jsonify(_item_payload(item, include_content=True))

    @app.post("/api/ask")
    def ask():
        kb = get_knowledge_base()
        payload = request.get_json(silent=True) or {}
        question = str(payload.get("question") or "")
        category = str(payload.get("category") or "")
        session_id = str(payload.get("session_id") or "")
        voice_enabled = payload.get("voice_enabled", True)
        if isinstance(voice_enabled, str):
            include_speech = voice_enabled.lower() not in {"0", "false", "no", "off"}
        else:
            include_speech = bool(voice_enabled)

        # Auto-generate session_id for new sessions
        import uuid as _uuid
        if not session_id:
            session_id = _uuid.uuid4().hex[:12]
        first_turn = conv_store.is_first_turn(session_id)
        context = conv_store.format_context(session_id) if not first_turn else None
        if context is None and isinstance(payload.get("context"), dict):
            context = payload.get("context")

        def generate():
            agent = Agent(kb)
            for event in agent.dispatch_stream(
                query=question,
                category=category,
                include_speech=include_speech,
                context=context,
            ):
                if isinstance(event, AgentResult):
                    speech_audio = _speech_audio_hint(event.speech) if include_speech else {}
                    # Extract item context for conversation storage.
                    item_titles = []
                    items_full = []
                    seen_item_ids = set()
                    for it in (event.items or []):
                        if not isinstance(it, dict):
                            continue
                        title = str(it.get("title") or "").strip()
                        if title and title not in item_titles:
                            item_titles.append(title)
                        item_id = str(it.get("id") or "").strip()
                        if item_id and item_id not in seen_item_ids:
                            item = kb.get(item_id)
                            if item is not None:
                                items_full.append(item_to_dict(item, include_content=True))
                                seen_item_ids.add(item_id)
                        elif not item_id and title:
                            items_full.append(dict(it))
                    # Save turn
                    conv_store.add_turn(
                        session_id=session_id,
                        query=question,
                        answer=event.answer or "",
                        item_titles=item_titles,
                        items_full=items_full,
                    )
                    result_payload = {
                        'type': 'result',
                        'session_id': session_id,
                        'answer': event.answer,
                        'speech': event.speech,
                        **speech_audio,
                        'mode': event.mode,
                        'task_type': event.task_type.value,
                        'task_label': task_type_label(event.task_type),
                        'confidence': event.confidence,
                        'sources': event.sources,
                        'items': event.items,
                        'evidence': event.evidence,
                        'selection_reason': event.selection_reason,
                        'warnings': event.warnings,
                        'total_count': event.total_count,
                        'decision': event.decision,
                        'bilingual_fields': event.bilingual_fields,
                    }
                    yield f"data: {json.dumps(result_payload, ensure_ascii=False)}\n\n"
                elif isinstance(event, dict) and event.get("type") == "speech":
                    speech_text = str(event.get("text") or "")
                    speech_audio = _speech_audio_hint(speech_text) if include_speech else {}
                    speech_payload = {
                        'type': 'speech',
                        'session_id': session_id,
                        'text': speech_text,
                        **speech_audio,
                    }
                    app.logger.info(
                        "Speech event: engine=%s text_len=%d",
                        speech_payload.get("speech_engine", "browser"),
                        len(speech_text),
                    )
                    yield f"data: {json.dumps(speech_payload, ensure_ascii=False)}\n\n"
                else:
                    evt = dict(event)
                    evt['session_id'] = session_id
                    yield f"data: {json.dumps(evt, ensure_ascii=False)}\n\n"

        return Response(generate(), mimetype="text/event-stream")

    @app.post("/api/tts")
    def create_tts_audio():
        payload = request.get_json(silent=True) or {}
        text = str(payload.get("text") or "").strip()
        if not text:
            return jsonify({"speech_engine": "browser", "error": "empty_text"})
        return jsonify(_speech_audio_payload(text))

    @app.get("/api/tts/stream")
    def stream_tts_audio():
        text = str(request.args.get("text") or "").strip()
        audio_stream = stream_speech_audio(text)
        if audio_stream is None:
            abort(503)
        return Response(
            stream_with_context(audio_stream),
            mimetype=_tts_mime_type(f"audio.{_tts_extension()}"),
            headers={
                "Cache-Control": "no-cache",
                "X-Accel-Buffering": "no",
            },
        )

    @app.get("/api/tts/<filename>")
    def tts_audio(filename: str):
        if not valid_tts_filename(filename):
            abort(404)
        path = TTS_CACHE_DIR / filename
        if not path.is_file():
            abort(404)
        return send_file(path, mimetype=_tts_mime_type(filename), conditional=True, max_age=3600)

    return app


def _speech_audio_hint(speech: str) -> dict:
    lang = _speech_language(speech)
    if speech and server_tts_available():
        return {
            "speech_engine": server_tts_engine(),
            "speech_audio_pending": True,
            "speech_lang": lang,
        }
    return {
        "speech_engine": "browser",
        "speech_lang": lang,
    }


def _speech_language(speech: str) -> str:
    text = str(speech or "")
    latin_count = len(re.findall(r"[A-Za-z]", text))
    chinese_count = len(re.findall(r"[\u4e00-\u9fff]", text))
    if latin_count >= 24 and latin_count > chinese_count * 2:
        return "en-US"
    return "zh-CN"


def _speech_audio_payload(speech: str) -> dict:
    try:
        audio = synthesize_speech_to_file(speech)
    except Exception:
        return {"speech_engine": "browser"}
    if audio is None:
        return {"speech_engine": "browser"}
    return {
        "speech_audio_url": f"/api/tts/{audio.path.name}",
        "speech_mime_type": audio.mime_type,
        "speech_engine": audio.engine,
    }


def _tts_mime_type(filename: str) -> str:
    if filename.endswith(".mp3"):
        return "audio/mpeg"
    if filename.endswith(".ogg") or filename.endswith(".opus"):
        return "audio/ogg"
    if filename.endswith(".wav"):
        return "audio/wav"
    return "application/octet-stream"


def _tts_extension() -> str:
    from . import config as cfg

    return cfg.VOLC_TTS_ENCODING.lower()


def _stream_items(
    kb, query: str, category: str, province: str, level: str, district: str,
    keywords: str, limit: int, offset: int,
):
    """SSE helper: push lexical results immediately, hybrid results when ready."""

    def generate():
        # Establish SSE connection to force first chunk flush
        yield ":ready\n\n"

        # Phase 1 — lexical (instant)
        lex_result, lex_total, structured = _search_items_for_api(
            kb, query=query, category=category,
            province=province, level=level, district=district, keywords=keywords,
            limit=limit, offset=offset, use_hybrid=False,
        )
        yield _sse_event({
            "phase": "lexical",
            "total": lex_total,
            "items": [_item_payload(item) for item in lex_result],
        })

        # Phase 2 — hybrid (with embedding, may be slower)
        from . import config as cfg

        if cfg.SEARCH_USE_EMBEDDING and query and not structured:
            try:
                hybrid_result, hybrid_total, _ = _search_items_for_api(
                    kb, query=query, category=category,
                    province=province, level=level, district=district, keywords=keywords,
                    limit=limit, offset=offset,
                )
                yield _sse_event({
                    "phase": "hybrid",
                    "total": hybrid_total,
                    "items": [_item_payload(item) for item in hybrid_result],
                })
            except Exception:
                pass

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


def _search_items_for_api(
    kb,
    query: str = "",
    category: str = "",
    province: str = "",
    level: str = "",
    district: str = "",
    keywords: str = "",
    limit: int = 30,
    offset: int = 0,
    use_hybrid: bool = True,
):
    structured = _structured_search_parts(kb, query, province, level)
    scenario = structured["scenario"]
    derived_province = province or structured["province"]
    derived_level = level or structured["level"]

    if scenario or (derived_province and not province) or (derived_level and not level):
        result, total = _search_structured_items(
            kb,
            query=structured["query"],
            category=category,
            province=derived_province,
            level=derived_level,
            district=district,
            keywords=keywords,
            scenario=scenario,
            limit=limit,
            offset=offset,
        )
        return result, total, True

    search_func = search_items if use_hybrid else search_items_lexical
    result, total = search_func(
        kb,
        query=query,
        category=category,
        province=province,
        level=level,
        district=district,
        keywords=keywords,
        limit=limit,
        offset=offset,
    )
    return result, total, False


def _structured_search_parts(kb, query: str, province: str, level: str) -> dict[str, str]:
    text = normalize_text(query)
    scenario = _query_scenario(text)
    derived_level = "" if level else _query_level(text)
    derived_province = "" if province else _query_province(kb, text, bool(scenario or derived_level))
    cleaned = _clean_structured_query(text, derived_province, derived_level, scenario)
    return {
        "province": derived_province,
        "level": derived_level,
        "scenario": scenario,
        "query": cleaned,
    }


def _search_structured_items(
    kb,
    query: str,
    category: str,
    province: str,
    level: str,
    district: str,
    keywords: str,
    scenario: str,
    limit: int,
    offset: int,
):
    category = normalize_text(category)
    province = normalize_text(province)
    level = normalize_text(level)
    district = normalize_text(district)
    query = " ".join(part for part in [normalize_text(keywords), normalize_text(query)] if part)

    candidates = []
    for item in kb.items:
        if category and item.category != category:
            continue
        if province and item.province != province:
            continue
        if level and item.level != level:
            continue
        if district and district not in item.district:
            continue
        if scenario and not _item_matches_scenario(item, scenario):
            continue
        candidates.append(item)

    if query:
        result, _ = search_items_lexical(
            _FilteredKnowledgeBase(kb, candidates),
            query=query,
            limit=len(candidates) or limit,
        )
        return result[offset : offset + limit], len(result)

    scored = sorted(
        candidates,
        key=lambda item: (-_structured_item_score(item, scenario), item.category, item.title),
    )
    return scored[offset : offset + limit], len(scored)


class _FilteredKnowledgeBase:
    def __init__(self, kb, items):
        self.items = items
        self.generated_at = kb.generated_at

    def get(self, item_id: str):
        return next((item for item in self.items if item.id == item_id), None)


def _query_province(kb, query: str, allow_short_match: bool) -> str:
    for province in sorted({item.province for item in kb.items if item.province}, key=len, reverse=True):
        if province in query:
            return province
    if not allow_short_match:
        return ""

    short_map = {
        "河南": "河南省",
        "河北": "河北省",
        "山东": "山东省",
        "山西": "山西省",
        "陕西": "陕西省",
        "湖北": "湖北省",
        "湖南": "湖南省",
        "广东": "广东省",
        "广西": "广西壮族自治区",
        "江苏": "江苏省",
        "浙江": "浙江省",
        "福建": "福建省",
        "四川": "四川省",
        "云南": "云南省",
        "贵州": "贵州省",
        "甘肃": "甘肃省",
        "青海": "青海省",
        "辽宁": "辽宁省",
        "吉林": "吉林省",
        "黑龙江": "黑龙江省",
        "安徽": "安徽省",
        "江西": "江西省",
        "海南": "海南省",
        "台湾": "台湾省",
        "北京": "北京市",
        "天津": "天津市",
        "上海": "上海市",
        "重庆": "重庆市",
        "内蒙古": "内蒙古自治区",
        "西藏": "西藏自治区",
        "宁夏": "宁夏回族自治区",
        "新疆": "新疆维吾尔自治区",
    }
    tokens = re.findall(r"[\w\u4e00-\u9fff]+", query)
    for short, full in short_map.items():
        if short in tokens:
            return full
    return ""


def _query_level(query: str) -> str:
    if "人类" in query:
        return "人类"
    if "国家级" in query:
        return "国家级"
    if "省级" in query:
        return "省级"
    return ""


def _query_scenario(query: str) -> str:
    if "社区" in query:
        return "社区活动"
    if "校园" in query or "学校" in query or "学生" in query:
        return "校园展示"
    if "研学" in query or "课堂" in query:
        return "研学体验"
    if "文创" in query or "包装" in query or "设计" in query:
        return "文创设计"
    if "展馆" in query or "讲解" in query:
        return "展馆讲解"
    return ""


def _clean_structured_query(query: str, province: str, level: str, scenario: str) -> str:
    cleaned = query
    if province:
        cleaned = cleaned.replace(province, " ")
        cleaned = cleaned.replace(province.removesuffix("省").removesuffix("市"), " ")
    if level:
        cleaned = cleaned.replace(level, " ")
    scenario_terms = {
        "社区活动": ("社区活动", "社区", "活动", "适合"),
        "校园展示": ("校园展示", "校园", "学校", "学生", "展示", "适合"),
        "研学体验": ("研学体验", "研学", "课堂", "体验", "适合"),
        "文创设计": ("文创设计", "文创", "包装", "设计", "适合"),
        "展馆讲解": ("展馆讲解", "展馆", "讲解", "介绍", "适合"),
    }
    for term in scenario_terms.get(scenario, ()):
        cleaned = cleaned.replace(term, " ")
    for term in ("非遗", "项目", "推荐", "哪些", "有哪些", "几个", "找", "筛选"):
        cleaned = cleaned.replace(term, " ")
    return normalize_text(cleaned)


def _item_matches_scenario(item, scenario: str) -> bool:
    return (
        scenario in item.suitable_scenarios
        or any(scenario in form for form in item.display_forms)
    )


def _structured_item_score(item, scenario: str) -> int:
    score = 0
    if scenario in item.suitable_scenarios:
        score += 8
    if any(scenario in form for form in item.display_forms):
        score += 5
    if item.level == "人类":
        score += 4
    elif item.level == "国家级":
        score += 3
    elif item.level == "省级":
        score += 1
    score += min(len(item.display_forms), 3)
    return score


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _item_payload(item, include_content: bool = False) -> dict:
    data = item_to_dict(item, include_content=include_content)
    data["suitable_scenarios"] = list(item.suitable_scenarios[:4])
    return data


def main() -> None:
    create_app().run(host=HOST, port=PORT, debug=DEBUG)


if __name__ == "__main__":
    main()
