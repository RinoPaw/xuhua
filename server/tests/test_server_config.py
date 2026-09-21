from __future__ import annotations

import heritage_explorer.api as api_module
from heritage_explorer.voice_transport import MAX_VOICE_FRAME_BYTES
import uvicorn


def test_server_topology_is_explicitly_single_worker(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_run(app: str, **kwargs: object) -> None:
        captured["app"] = app
        captured.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)
    api_module.main()

    assert captured["app"] == "heritage_explorer.api:app"
    assert captured["workers"] == 1
    assert captured["ws_max_size"] == MAX_VOICE_FRAME_BYTES
