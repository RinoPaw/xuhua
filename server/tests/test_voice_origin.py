from heritage_explorer.voice_transport import websocket_origin_allowed


def test_voice_origin_allows_same_origin_direct_connection() -> None:
    assert websocket_origin_allowed(
        "http://127.0.0.1:5050",
        "127.0.0.1:5050",
        websocket_scheme="ws",
    )


def test_voice_origin_uses_forwarded_public_scheme_behind_proxy() -> None:
    assert websocket_origin_allowed(
        "https://xuhua.520207.xyz",
        "xuhua.520207.xyz",
        websocket_scheme="ws",
        forwarded_proto="https",
    )


def test_voice_origin_rejects_cross_site_browser_handshake() -> None:
    assert not websocket_origin_allowed(
        "https://evil.example",
        "xuhua.520207.xyz",
        websocket_scheme="ws",
        forwarded_proto="https",
    )


def test_voice_origin_rejects_scheme_or_port_mismatch() -> None:
    assert not websocket_origin_allowed(
        "http://xuhua.520207.xyz",
        "xuhua.520207.xyz",
        websocket_scheme="ws",
        forwarded_proto="https",
    )
    assert not websocket_origin_allowed(
        "http://localhost:5174",
        "localhost:5173",
        websocket_scheme="ws",
    )


def test_voice_origin_rejects_null_or_malformed_origin() -> None:
    assert not websocket_origin_allowed(
        "null",
        "xuhua.520207.xyz",
        websocket_scheme="wss",
    )
    assert not websocket_origin_allowed(
        "https://[invalid",
        "xuhua.520207.xyz",
        websocket_scheme="wss",
    )


def test_voice_origin_keeps_non_browser_clients_compatible() -> None:
    assert websocket_origin_allowed(
        None,
        "127.0.0.1:5050",
        websocket_scheme="ws",
    )
