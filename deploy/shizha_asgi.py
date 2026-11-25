"""Standalone Shizha ASGI entry point."""

from heritage_explorer.shizha_api import create_shizha_app

app = create_shizha_app()
