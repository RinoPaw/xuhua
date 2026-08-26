from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from build_dataset import CORE_FIELDS, build_dataset  # noqa: E402
from enrich_dataset import enrich_dataset  # noqa: E402


def test_build_is_deterministic_and_has_only_runtime_fields(tmp_path: Path) -> None:
    source = tmp_path / "heritage_source.json"
    source.write_text(
        json.dumps(
            {
                "meta": {"source": "fixture-v1"},
                "items": [
                    {
                        "id": "one",
                        "title": "京剧（北京）",
                        "type": "传统戏剧",
                        "unit": "北京市东城区",
                        "content": "<p>传统戏剧内容。校园研学。</p>",
                    },
                    {"title": "木板年画", "type": "传统美术", "content": "abc"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    first = build_dataset(source)
    second = build_dataset(source)
    assert first == second
    assert all(tuple(item) == CORE_FIELDS for item in first["items"])
    assert first["generated_at"] == ""
    assert first["meta"]["item_count"] == 2
    assert first["items"][0]["province"] == "北京市"
    assert first["items"][0]["district"] == "东城区"
    assert all(item["level"] == "" for item in first["items"])


def test_missing_level_is_inferred_only_from_national_batch_provenance(tmp_path: Path) -> None:
    source = tmp_path / "heritage_source.json"
    source.write_text(
        json.dumps(
            {
                "items": [
                    {"title": "有批次", "type": "民俗", "rx_time": "2021</br>(第五批)"},
                    {"title": "无批次", "type": "民俗"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    items = build_dataset(source)["items"]
    assert [item["level"] for item in items] == ["国家级", ""]


class FakeProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def stream_chat(self, messages, **kwargs):
        self.calls += 1
        yield '```json\n{"features":"特色", "history":"历史", "cultural_value":"价值"}\n```'


def test_enrichment_resumes_and_writes_failure_manifest(tmp_path: Path) -> None:
    dataset = tmp_path / "dataset.json"
    dataset.write_text(json.dumps({"items": [{"id": "one", "content": "正文"}]}), encoding="utf-8")
    output = tmp_path / "ai_fields.json"
    provider = FakeProvider()
    result = asyncio.run(enrich_dataset(dataset, output, provider, retries=1))
    assert result["one"]["features"] == "特色"
    assert provider.calls == 1
    asyncio.run(enrich_dataset(dataset, output, provider, retries=1))
    assert provider.calls == 1
    assert json.loads(output.read_text(encoding="utf-8"))["one"]["history"] == "历史"
