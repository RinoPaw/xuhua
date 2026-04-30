"""Flask web app for the heritage knowledge base."""

from __future__ import annotations

from flask import Flask, abort, jsonify, render_template, request

from .ai import answer_question
from .config import DEBUG, HOST, PORT
from .dataset import get_knowledge_base, item_to_dict
from .search import search_items


def create_app() -> Flask:
    app = Flask(
        __name__,
        template_folder="../../templates",
        static_folder="../../static",
    )

    @app.get("/")
    def index():
        return render_template("index.html")

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
        limit = min(max(int(request.args.get("limit", "30")), 1), 100)
        offset = max(int(request.args.get("offset", "0")), 0)
        result, total = search_items(kb, query=query, category=category, limit=limit, offset=offset)
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
        answer = answer_question(kb, question=question, category=category)
        return jsonify({
            "answer": answer.answer,
            "mode": answer.mode,
            "sources": answer.sources,
        })

    return app


def main() -> None:
    create_app().run(host=HOST, port=PORT, debug=DEBUG)


if __name__ == "__main__":
    main()
