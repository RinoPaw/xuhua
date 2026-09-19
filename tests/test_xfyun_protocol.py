from urllib.parse import parse_qs, urlparse

from heritage_explorer.xfyun_protocol import (
    TranscriptAccumulator,
    extract_candidates,
    extract_language,
    format_hotwords,
    signed_url,
)


def test_hotwords_are_deduplicated_and_bounded():
    value = format_hotwords([" 苏绣 ", "苏绣", "木|版年画", "甲\n乙"])
    assert value == "utf-8;苏绣|木|版年画|甲|乙"
    assert len(format_hotwords(["词" * 1000]).encode("utf-8")) <= 1024


def test_signed_url_uses_selected_host_and_auth_fields():
    parsed = urlparse(
        signed_url(
            host="iat.xf-yun.com",
            path="/v1",
            api_key="key",
            api_secret="secret",
            date="Sun, 20 Sep 2026 00:00:00 GMT",
        )
    )
    query = parse_qs(parsed.query)
    assert parsed.hostname == "iat.xf-yun.com"
    assert query["host"] == ["iat.xf-yun.com"]
    assert query["date"] == ["Sun, 20 Sep 2026 00:00:00 GMT"]
    assert query["authorization"]


def test_candidates_preserve_provider_order():
    result = {
        "ws": [
            {"cw": [{"w": "朱仙镇"}, {"w": "朱仙阵"}]},
            {"cw": [{"w": "木版年画"}, {"w": "木板年画"}]},
        ]
    }
    assert extract_candidates(result) == ("朱仙镇木版年画", "朱仙阵木板年画")


def test_accumulator_applies_wpgs_replacement_to_text_candidates_and_language():
    state = TranscriptAccumulator()
    state.apply({"sn": 0, "ws": [{"cw": [{"w": "hello", "lg": "en"}]}]})
    state.apply({"sn": 1, "ws": [{"cw": [{"w": "书秀", "lg": "zh"}, {"w": "旧候选"}]}]})
    state.apply(
        {
            "sn": 2,
            "pgs": "rpl",
            "rg": [1, 1],
            "ws": [{"cw": [{"w": "苏绣", "lg": "zh"}, {"w": "新候选"}]}],
        }
    )
    assert state.text == "hello苏绣"
    assert state.alternatives == ("hello苏绣", "hello新候选")
    assert state.detected_language in {"en", "zh"}
    assert extract_language({"ws": [{"cw": [{"w": "hello", "lg": "en"}]}]}) == "en"
