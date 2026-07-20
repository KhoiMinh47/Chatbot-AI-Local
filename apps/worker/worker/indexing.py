"""Local embedding and Qdrant indexing for completed ingestion chunks."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from uuid import UUID

from worker.domain import Chunk, ChunkType


class IndexingError(RuntimeError):
    """Stable error that does not expose service response bodies."""


def _json_request(
    url: str,
    *,
    method: str = "GET",
    payload: dict[str, object] | None = None,
    timeout_seconds: int = 120,
    allowed_statuses: frozenset[int] = frozenset({200}),
) -> dict[str, Any]:
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(
        url,
        data=data,
        method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            if response.status not in allowed_statuses:
                raise IndexingError(f"index dependency returned HTTP {response.status}")
            raw = response.read()
    except HTTPError as error:
        if error.code in allowed_statuses:
            return {"status": error.code}
        raise IndexingError(f"index dependency returned HTTP {error.code}") from None
    except (URLError, TimeoutError, OSError):
        raise IndexingError("index dependency is unavailable") from None
    try:
        value = json.loads(raw) if raw else {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise IndexingError("index dependency returned invalid JSON") from None
    if not isinstance(value, dict):
        raise IndexingError("index dependency returned an invalid object")
    return value


def _ensure_collection(qdrant_url: str, collection: str, dimension: int) -> None:
    target = f"{qdrant_url.rstrip('/')}/collections/{quote(collection, safe='')}"
    observed = _json_request(target, allowed_statuses=frozenset({200, 404}))
    if observed.get("status") == 404:
        _json_request(
            target,
            method="PUT",
            payload={
                "vectors": {"size": dimension, "distance": "Cosine"},
                "hnsw_config": {"m": 16, "ef_construct": 100},
                "on_disk_payload": True,
            },
            allowed_statuses=frozenset({200, 409}),
        )
    elif observed:
        try:
            size = observed["result"]["config"]["params"]["vectors"]["size"]
        except (KeyError, TypeError):
            raise IndexingError("Qdrant collection contract is invalid") from None
        if size != dimension:
            raise IndexingError("Qdrant collection dimension does not match embedding output")

    index_url = f"{target}/index"
    index_fields = (
        "tenant_id",
        "document_id",
        "owner_id",
        "acl_principals",
        "index_version",
        "chunk_type",
    )
    for name in index_fields:
        _json_request(
            index_url,
            method="PUT",
            payload={"field_name": name, "field_schema": "keyword"},
            allowed_statuses=frozenset({200, 409}),
        )


def _ensure_alias(qdrant_url: str, collection: str, alias: str | None) -> None:
    if alias is None or alias == collection:
        return
    base = qdrant_url.rstrip("/")
    observed = _json_request(
        f"{base}/aliases/{quote(alias, safe='')}",
        allowed_statuses=frozenset({200, 404}),
    )
    aliases = observed.get("result", {}).get("aliases", []) if observed.get("result") else []
    current = next(
        (
            item.get("collection_name")
            for item in aliases
            if isinstance(item, dict) and item.get("alias_name") == alias
        ),
        None,
    )
    if current == collection:
        return
    actions: list[dict[str, object]] = []
    if current is not None:
        actions.append({"delete_alias": {"alias_name": alias}})
    actions.append({"create_alias": {"collection_name": collection, "alias_name": alias}})
    _json_request(
        f"{base}/collections/aliases",
        method="POST",
        payload={"actions": actions},
    )


def _embed(
    base_url: str,
    model: str,
    texts: list[str],
    expected_dimension: int,
) -> list[list[float]]:
    response = _json_request(
        f"{base_url.rstrip('/')}/embeddings",
        method="POST",
        payload={
            "model": model,
            "input": texts,
            "input_type": "passage",
            "truncate": "NONE",
            "encoding_format": "float",
        },
    )
    data = response.get("data")
    if not isinstance(data, list) or len(data) != len(texts):
        raise IndexingError("embedding response count is invalid")
    ordered: list[list[float] | None] = [None] * len(texts)
    for item in data:
        if not isinstance(item, dict) or not isinstance(item.get("index"), int):
            raise IndexingError("embedding response item is invalid")
        index = item["index"]
        vector = item.get("embedding")
        if not 0 <= index < len(texts) or not isinstance(vector, list):
            raise IndexingError("embedding response index is invalid")
        values = [float(value) for value in vector]
        if len(values) != expected_dimension or any(not math.isfinite(value) for value in values):
            raise IndexingError("embedding response dimension or values are invalid")
        ordered[index] = values
    if any(vector is None for vector in ordered):
        raise IndexingError("embedding response is incomplete")
    return [vector for vector in ordered if vector is not None]


def index_chunks(
    *,
    chunks: list[Chunk],
    tenant_id: UUID,
    document_id: UUID,
    version_id: UUID,
    owner_id: UUID,
    acl_principals: tuple[str, ...],
    source_name: str,
    mime_type: str,
    embedding_base_url: str,
    embedding_model: str,
    embedding_dimension: int,
    qdrant_url: str,
    collection: str,
    active_alias: str | None,
    index_version: str,
    batch_size: int = 16,
) -> int:
    children = [chunk for chunk in chunks if chunk.chunk_type is ChunkType.CHILD]
    if not children:
        raise IndexingError("no child chunks are available for indexing")
    _ensure_collection(qdrant_url, collection, embedding_dimension)
    _ensure_alias(qdrant_url, collection, active_alias)
    indexed = 0
    created_at = datetime.now(UTC).isoformat()
    points_url = (
        f"{qdrant_url.rstrip('/')}/collections/{quote(collection, safe='')}/points?wait=true"
    )
    for offset in range(0, len(children), batch_size):
        batch = children[offset : offset + batch_size]
        vectors = _embed(
            embedding_base_url,
            embedding_model,
            [chunk.text for chunk in batch],
            embedding_dimension,
        )
        points: list[dict[str, object]] = []
        for chunk, vector in zip(batch, vectors, strict=True):
            points.append(
                {
                    "id": str(chunk.chunk_id),
                    "vector": vector,
                    "payload": {
                        "tenant_id": str(tenant_id),
                        "document_id": str(document_id),
                        "version_id": str(version_id),
                        "chunk_id": str(chunk.chunk_id),
                        "parent_id": (
                            None if chunk.parent_chunk_id is None else str(chunk.parent_chunk_id)
                        ),
                        "owner_id": str(owner_id),
                        "acl_principals": list(acl_principals),
                        "source_name": source_name,
                        "mime_type": mime_type,
                        "page": chunk.page,
                        "slide": chunk.slide,
                        "sheet": chunk.sheet,
                        "cell_range": chunk.cell_range,
                        "line_start": chunk.line_start,
                        "line_end": chunk.line_end,
                        "section_path": chunk.section_path,
                        "language": chunk.language or "unknown",
                        "text": chunk.text,
                        "token_count": chunk.token_count,
                        "content_hash": chunk.content_hash,
                        "index_version": index_version,
                        "created_at": created_at,
                        "chunk_type": "child",
                    },
                }
            )
        _json_request(points_url, method="PUT", payload={"points": points})
        indexed += len(points)
    return indexed


__all__ = ["IndexingError", "index_chunks"]
