import base64
import json

from heritage_explorer import config
from heritage_explorer.volc_tts import stream_speech_audio, synthesize_speech_to_file, volc_tts_available


def _enable_tts(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "VOLC_TTS_ENABLED", True)
    monkeypatch.setattr(config, "VOLC_TTS_API_VERSION", "v1")
    monkeypatch.setattr(config, "VOLC_TTS_API_KEY", "")
    monkeypatch.setattr(config, "VOLC_TTS_APP_ID", "app-id")
    monkeypatch.setattr(config, "VOLC_TTS_ACCESS_TOKEN", "access-token")
    monkeypatch.setattr(config, "VOLC_TTS_CLUSTER", "volcano_tts")
    monkeypatch.setattr(config, "VOLC_TTS_RESOURCE_ID", "volc.service_type.10029")
    monkeypatch.setattr(config, "VOLC_TTS_VOICE_TYPE", "zh_female_gaolengyujie_emo_v2_mars_bigtts")
    monkeypatch.setattr(config, "VOLC_TTS_EMOTION", "coldness")
    monkeypatch.setattr(config, "VOLC_TTS_EMOTION_SCALE", 4)
    monkeypatch.setattr(config, "VOLC_TTS_ENCODING", "mp3")
    monkeypatch.setattr(config, "VOLC_TTS_RATE", 24000)
    monkeypatch.setattr(config, "VOLC_TTS_SPEED_RATIO", 1.0)
    monkeypatch.setattr(config, "VOLC_TTS_VOLUME_RATIO", 1.0)
    monkeypatch.setattr(config, "VOLC_TTS_PITCH_RATIO", 1.0)
    monkeypatch.setattr(config, "VOLC_TTS_TIMEOUT", 3)
    monkeypatch.setattr(config, "VOLC_TTS_MAX_CHUNK_BYTES", 900)
    monkeypatch.setattr(config, "TTS_CACHE_DIR", tmp_path)


def test_volc_tts_requires_app_credentials(monkeypatch):
    monkeypatch.setattr(config, "VOLC_TTS_ENABLED", True)
    monkeypatch.setattr(config, "VOLC_TTS_API_VERSION", "v1")
    monkeypatch.setattr(config, "VOLC_TTS_API_KEY", "")
    monkeypatch.setattr(config, "VOLC_TTS_APP_ID", "")
    monkeypatch.setattr(config, "VOLC_TTS_ACCESS_TOKEN", "")

    assert volc_tts_available() is False
    assert synthesize_speech_to_file("汴绣适合现场讲解。") is None


def test_volc_tts_synthesizes_and_caches_audio(monkeypatch, tmp_path):
    from heritage_explorer import volc_tts

    _enable_tts(monkeypatch, tmp_path)
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps({
                "code": 3000,
                "data": base64.b64encode(b"audio-bytes").decode("ascii"),
            }).encode("utf-8")

    def fake_urlopen(req, timeout):
        calls.append((req, json.loads(req.data.decode("utf-8")), timeout))
        return FakeResponse()

    monkeypatch.setattr(volc_tts.request, "urlopen", fake_urlopen)

    audio = synthesize_speech_to_file("朱仙镇木版年画适合现场讲解。")
    cached = synthesize_speech_to_file("朱仙镇木版年画适合现场讲解。")

    assert audio is not None
    assert cached is not None
    assert audio.path == cached.path
    assert audio.path.read_bytes() == b"audio-bytes"
    assert audio.mime_type == "audio/mpeg"
    assert len(calls) == 1
    req, payload, timeout = calls[0]
    assert req.get_header("Authorization") == "Bearer;access-token"
    assert payload["app"]["appid"] == "app-id"
    assert payload["app"]["token"] == "access-token"
    assert payload["audio"]["voice_type"] == "zh_female_gaolengyujie_emo_v2_mars_bigtts"
    assert payload["audio"]["emotion"] == "coldness"
    assert payload["request"]["operation"] == "query"
    assert timeout == 3


def test_volc_tts_supports_new_console_api_key(monkeypatch, tmp_path):
    from heritage_explorer import volc_tts

    _enable_tts(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "VOLC_TTS_API_VERSION", "auto")
    monkeypatch.setattr(config, "VOLC_TTS_API_KEY", "api-key")
    calls = []

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            first = json.dumps({"code": 0, "data": base64.b64encode(b"audio-").decode("ascii")})
            second = json.dumps({"code": 20000000, "data": base64.b64encode(b"bytes").decode("ascii")})
            return f"{first}\n{second}\n".encode("utf-8")

    def fake_urlopen(req, timeout):
        calls.append((req, json.loads(req.data.decode("utf-8")), timeout))
        return FakeResponse()

    monkeypatch.setattr(volc_tts.request, "urlopen", fake_urlopen)

    audio = synthesize_speech_to_file("朱仙镇木版年画适合现场讲解。")

    assert audio is not None
    assert audio.path.read_bytes() == b"audio-bytes"
    req, payload, _timeout = calls[0]
    assert req.get_header("X-api-key") == "api-key"
    assert req.get_header("X-api-resource-id") == "volc.service_type.10029"
    assert "Authorization" not in req.headers
    assert payload["req_params"]["speaker"] == "zh_female_gaolengyujie_emo_v2_mars_bigtts"
    assert payload["req_params"]["emotion"] == "coldness"
    assert payload["req_params"]["audio_params"]["format"] == "mp3"


def test_volc_tts_streams_v3_audio_chunks(monkeypatch, tmp_path):
    from heritage_explorer import volc_tts

    _enable_tts(monkeypatch, tmp_path)
    monkeypatch.setattr(config, "VOLC_TTS_API_VERSION", "auto")
    monkeypatch.setattr(config, "VOLC_TTS_API_KEY", "api-key")

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def __iter__(self):
            first = json.dumps({"code": 0, "data": base64.b64encode(b"audio-").decode("ascii")})
            second = json.dumps({"code": 20000000, "data": base64.b64encode(b"bytes").decode("ascii")})
            return iter([f"data: {first}\n".encode(), f"data: {second}\n".encode()])

    def fake_urlopen(req, timeout):
        assert req.get_header("X-api-key") == "api-key"
        assert timeout == 3
        return FakeResponse()

    monkeypatch.setattr(volc_tts.request, "urlopen", fake_urlopen)

    audio = b"".join(stream_speech_audio("朱仙镇木版年画适合现场讲解。"))

    assert audio == b"audio-bytes"
