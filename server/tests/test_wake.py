import asyncio
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import pytest

import heritage_explorer.wake as module


def make_client(monkeypatch):
    monkeypatch.setenv('XF_WAKE_URL', 'ws://private-wake:5052/api/wake')
    monkeypatch.setenv('XF_WAKE_TOKEN', 'private-service-secret')
    monkeypatch.setenv('XF_WAKE_TERMINAL_KEY', 'terminal-key-for-tests-1234')
    app = FastAPI()
    assert module.register_wake_routes(app)
    return TestClient(app)


def pair(client):
    response = client.post('/api/wake/authorize', json={'code': 'terminal-key-for-tests-1234'})
    assert response.status_code == 200
    assert 'HttpOnly' in response.headers['set-cookie']
    assert 'samesite=strict' in response.headers['set-cookie'].lower()


def test_unauthorized_cannot_claim_engine_or_read_metrics(monkeypatch):
    client = make_client(monkeypatch)
    assert not client.get('/api/wake/status').json()['authorized']
    assert client.get('/api/wake/metrics').status_code == 403
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/wake'):
            pass
    assert client.post('/api/wake/authorize', json={'code': 'incorrect-credential'}).status_code == 403
    pair(client)
    assert client.get('/api/wake/status').json()['authorized']


def test_pairing_rejects_other_origins_and_hides_secrets(monkeypatch):
    client = make_client(monkeypatch)
    response = client.post('/api/wake/authorize', headers={'origin': 'https://other.example'},
                           json={'code': 'terminal-key-for-tests-1234'})
    assert response.status_code == 403
    public = client.get('/api/wake/status').text
    assert 'private-service-secret' not in public and 'terminal-key-for-tests' not in public


def test_metrics_separate_acknowledgements_failures_and_successful_playback(monkeypatch):
    client = make_client(monkeypatch)
    pair(client)
    for attempt, kind, outcome, played, elapsed in (
        ('a', 'wake', 'completed', True, 200),
        ('b', 'conversation', 'completed', True, 2500),
        ('c', 'conversation', 'failed', False, 7000),
    ):
        body = dict(attempt=attempt, kind=kind, outcome=outcome, played=played, elapsed_ms=elapsed)
        assert client.post('/api/wake/metrics', json=body).status_code == 204
        assert client.post('/api/wake/metrics', json=body).status_code == 204
    report = client.get('/api/wake/metrics').json()
    assert report['wake']['mean_ms'] == 200
    assert report['conversation'] == {'attempts': 2, 'played': 1, 'not_played': 1,
                                      'mean_ms': 2500, 'p50_ms': 2500, 'p95_ms': 2500}
    client.post('/api/wake/metrics', json=dict(attempt='d', kind='conversation', outcome='completed',
                                             played=True, elapsed_ms=3500))
    report = client.get('/api/wake/metrics').json()
    assert report['conversation']['p95_ms'] == 3500
    assert report['conversation']['mean_ms'] == 3000


def test_bridge_keeps_private_token_server_side_and_releases_owner(monkeypatch):
    received = []

    class Upstream:
        async def __aenter__(self):
            self.events = asyncio.Queue()
            return self

        async def __aexit__(self, *args):
            pass

        async def send(self, value):
            received.append(value)
            if isinstance(value, str) and json.loads(value).get('type') == 'ping':
                await self.events.put(json.dumps({'type': 'pong'}))

        async def recv(self):
            return json.dumps({'type': 'ready', 'stream_id': 'stream-a'})

        def __aiter__(self):
            return self

        async def __anext__(self):
            return await self.events.get()

    monkeypatch.setattr(module, 'connect', lambda *args, **kwargs: Upstream())
    client = make_client(monkeypatch)
    pair(client)
    for _ in range(2):
        with client.websocket_connect('/api/wake') as ws:
            assert ws.receive_json() == {'type': 'ready', 'stream_id': 'stream-a'}
            ws.send_bytes(bytes(640))
            ws.send_json({'type': 'ping'})
            assert ws.receive_json() == {'type': 'pong'}
    assert json.loads(received[0])['token'] == 'private-service-secret'
    assert bytes(640) in received


def test_secure_cookie_cannot_be_used_with_cross_site_websocket(monkeypatch):
    client = make_client(monkeypatch)
    pair(client)
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect('/api/wake', headers={'origin': 'https://other.example'}):
            pass
