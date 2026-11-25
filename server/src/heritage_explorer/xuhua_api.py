"""Standalone Xuhua application, including its browser frontend."""

from fastapi import FastAPI
from fastapi.responses import FileResponse

from .api import create_app
from .config import FRONTEND_DIR


def create_xuhua_app() -> FastAPI:
    app = create_app()

    if FRONTEND_DIR.is_dir():
        @app.get("/persona", include_in_schema=False)
        @app.get("/persona/", include_in_schema=False)
        async def persona_page():
            return FileResponse(FRONTEND_DIR / "index.html", media_type="text/html")

        app.frontend("/", directory=FRONTEND_DIR, fallback=None)

    return app
