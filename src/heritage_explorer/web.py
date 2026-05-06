"""Flask web app for the heritage knowledge base."""

from __future__ import annotations

import json

from flask import Flask, Response, abort, jsonify, render_template, request

from .agent import Agent, AgentResult, task_type_label
from .config import DEBUG, HOST, PORT
from .dataset import get_knowledge_base, item_to_dict
from .search import search_items, search_items_lexical


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="../../templates",
        static_folder="../../static",
    )

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
            "items": [item_to_dict(item) for item in result],
        })

    @app.get("/api/items/<item_id>")
    def item_detail(item_id: str):
        kb = get_knowledge_base()
        item = kb.get(item_id)
        if item is None:
            abort(404)
        return jsonify(item_to_dict(item, include_content=True))

    @app.post("/api/ask")
    def ask():
        kb = get_knowledge_base()
        payload = request.get_json(silent=True) or {}
        question = str(payload.get("question") or "")
        category = str(payload.get("category") or "")
        voice_enabled = payload.get("voice_enabled", True)
        if isinstance(voice_enabled, str):
            include_speech = voice_enabled.lower() not in {"0", "false", "no", "off"}
        else:
            include_speech = bool(voice_enabled)

        def generate():
            agent = Agent(kb)
            for event in agent.dispatch_stream(
                query=question,
                category=category,
                include_speech=include_speech,
            ):
                if isinstance(event, AgentResult):
                    yield f"data: {json.dumps({
                        'type': 'result',
                        'answer': event.answer,
                        'speech': event.speech,
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
                    }, ensure_ascii=False)}\n\n"
                else:
                    yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"

        return Response(generate(), mimetype="text/event-stream")

    return app


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
            "items": [item_to_dict(item) for item in lex_result],
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
                    "items": [item_to_dict(item) for item in hybrid_result],
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


def main() -> None:
    create_app().run(host=HOST, port=PORT, debug=DEBUG)


if __name__ == "__main__":
    main()
