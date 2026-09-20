from __future__ import annotations

from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

import heritage_explorer.api as api_module


def test_voice_capability_and_route_share_composed_availability(monkeypatch) -> None:
    monkeypatch.setattr(api_module, "XF_APP_ID", "app")
    monkeypatch.setattr(api_module, "XF_API_KEY", "key")
    monkeypatch.setattr(api_module, "XF_API_SECRET", "secret")
    monkeypatch.setattr(api_module, "XF_ASR_HOST", "")

    with TestClient(api_module.create_app()) as client:
        meta = client.get("/api/meta").json()
        assert meta["capabilities"]["realtime_voice"] is False
        assert meta["capabilities"]["voice_provider"] == ""

        try:
            with client.websocket_connect("/api/voice"):
                raise AssertionError("unavailable voice route accepted a WebSocket")
        except WebSocketDisconnect as exc:
            assert exc.code == 1013
