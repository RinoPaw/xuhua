"""Flask web app for the heritage knowledge base."""

from __future__ import annotations

import json
import re

from flask import Flask, Response, abort, jsonify, render_template, request, send_file, stream_with_context

from .agent import Agent, AgentResult, task_type_label
from .config import DEBUG, HOST, PORT, TTS_CACHE_DIR
from .dataset import get_knowledge_base, item_to_dict
from .search import search_items, search_items_lexical
from .volc_tts import (
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
        limit = min(max(int(request.args.get("limit", "30")), 1), 100)
        offset = max(int(request.args.get("offset", "0")), 0)

        if request.args.get("stream") == "1":
            return _stream_items(kb, query, category, province, level, district, keywords, limit, offset)

        result, total = search_items(
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
        agent_question = _question_with_context(question, payload.get("context"))
        voice_enabled = payload.get("voice_enabled", True)
        if isinstance(voice_enabled, str):
            include_speech = voice_enabled.lower() not in {"0", "false", "no", "off"}
        else:
            include_speech = bool(voice_enabled)

        def generate():
            agent = Agent(kb)
            for event in agent.dispatch_stream(
                query=agent_question,
                category=category,
                include_speech=include_speech,
            ):
                if isinstance(event, AgentResult):
                    speech_audio = _speech_audio_hint(event.speech) if include_speech else {}
                    result_payload = {
                        'type': 'result',
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
                    }
                    yield f"data: {json.dumps(result_payload, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

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
    if speech and volc_tts_available():
        return {"speech_engine": "volcengine", "speech_audio_pending": True}
    return {"speech_engine": "browser"}


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


_CONTEXT_LEAD_RE = re.compile(r"^\s*(再|继续|接着|然后|上一|上个|这个|这份|这段|它|把它|把这个|帮我把它|帮我把这个|基于)")
_CONTEXT_TRANSFORM_RE = re.compile(r"(年轻化|口语化|轻松|双语|英文|翻译|压缩|精简|扩写|改写|润色|换个版本|讲解词|口播稿|文案)")


def _question_with_context(question: str, context) -> str:
    """Attach previous answer context for short follow-up transformations."""
    question = str(question or "").strip()
    if not question or not isinstance(context, dict) or not _needs_previous_context(question):
        return question

    previous_question = _compact_context_text(context.get("question"), 240)
    previous_answer = _compact_context_text(context.get("answer"), 2400)
    item_titles = _context_item_titles(context.get("items"))
    if not previous_question and not previous_answer and not item_titles:
        return question

    parts = [
        question,
        "",
        "上一轮上下文（供本轮理解指代，不要逐字复述）：",
    ]
    if previous_question:
        parts.append(f"上一轮问题：{previous_question}")
    if item_titles:
        parts.append(f"相关项目：{'、'.join(item_titles)}")
    if previous_answer:
        parts.append(f"可改写原文：\n{previous_answer}")
    return "\n".join(parts)


def _needs_previous_context(question: str) -> bool:
    text = str(question or "").strip()
    if not text:
        return False
    if _CONTEXT_LEAD_RE.search(text):
        return True
    if re.search(r"^\s*(改成|改为|换成|润色|压缩|精简|扩写|翻译|做成|来个|更)", text) and _CONTEXT_TRANSFORM_RE.search(text):
        return True
    return False


def _compact_context_text(value, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "……"


def _context_item_titles(items) -> list[str]:
    if not isinstance(items, list):
        return []
    titles: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()
        if title and title not in titles:
            titles.append(title)
        if len(titles) >= 5:
            break
    return titles


def _stream_items(
    kb, query: str, category: str, province: str, level: str, district: str,
    keywords: str, limit: int, offset: int,
):
    """SSE helper: push lexical results immediately, hybrid results when ready."""

    def generate():
        # Establish SSE connection to force first chunk flush
        yield ":ready\n\n"

        # Phase 1 — lexical (instant)
        lex_result, lex_total = search_items_lexical(
            kb, query=query, category=category,
            province=province, level=level, district=district, keywords=keywords,
            limit=limit, offset=offset,
        )
        yield _sse_event({
            "phase": "lexical",
            "total": lex_total,
            "items": [_item_payload(item) for item in lex_result],
        })

        # Phase 2 — hybrid (with embedding, may be slower)
        from . import config as cfg

        if cfg.SEARCH_USE_EMBEDDING and query:
            try:
                hybrid_result, hybrid_total = search_items(
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


def _sse_event(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _item_payload(item, include_content: bool = False) -> dict:
    data = item_to_dict(item, include_content=include_content)
    data["suitable_scenarios"] = list(item.suitable_scenarios[:4])
    data["target_audience"] = list(item.target_audience[:4])
    data["interaction_potential"] = item.interaction_potential
    data["education_value"] = item.education_value
    data["cultural_keywords"] = list(item.cultural_keywords[:6])
    return data


def main() -> None:
    create_app().run(host=HOST, port=PORT, debug=DEBUG)


if __name__ == "__main__":
    main()
