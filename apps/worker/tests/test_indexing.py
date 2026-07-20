from __future__ import annotations

from typing import Any

from worker import indexing


def test_embed_sends_nim_passage_contract(monkeypatch) -> None:
    observed: dict[str, Any] = {}

    def fake_request(url: str, **kwargs: object) -> dict[str, Any]:
        observed.update({"url": url, **kwargs})
        return {"data": [{"index": 0, "embedding": [0.25, 0.75]}]}

    monkeypatch.setattr(indexing, "_json_request", fake_request)

    result = indexing._embed("http://embed/v1", "embed-winner", ["passage"], 2)

    assert result == [[0.25, 0.75]]
    assert observed["payload"] == {
        "model": "embed-winner",
        "input": ["passage"],
        "input_type": "passage",
        "truncate": "NONE",
        "encoding_format": "float",
    }


def test_ensure_alias_atomically_switches_wrong_target(monkeypatch) -> None:
    writes: list[dict[str, object]] = []

    def fake_request(
        url: str,
        *,
        method: str = "GET",
        payload: dict[str, object] | None = None,
        **_: object,
    ) -> dict[str, Any]:
        if method == "GET":
            return {
                "result": {
                    "aliases": [{"alias_name": "active", "collection_name": "old-collection"}]
                }
            }
        writes.append(payload or {})
        return {"result": True}

    monkeypatch.setattr(indexing, "_json_request", fake_request)

    indexing._ensure_alias("http://qdrant:6333", "winner-collection", "active")

    assert writes == [
        {
            "actions": [
                {"delete_alias": {"alias_name": "active"}},
                {
                    "create_alias": {
                        "collection_name": "winner-collection",
                        "alias_name": "active",
                    }
                },
            ]
        }
    ]
