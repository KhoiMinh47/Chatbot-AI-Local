"""Strict Qdrant REST adapter for versioned Phase 5 dense indexes."""

from __future__ import annotations

import hashlib
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from itertools import pairwise
from typing import cast
from urllib.parse import quote, urlsplit
from uuid import UUID

import httpx2 as httpx

from app.domain.retrieval import (
    AccessScope,
    ChunkPayload,
    IndexConfig,
    RetrievalPolicy,
    SearchHit,
    VectorPoint,
    WinnerApproval,
)

_PAYLOAD_INDEXES: tuple[tuple[str, str], ...] = (
    ("tenant_id", "keyword"),
    ("document_id", "keyword"),
    ("version_id", "keyword"),
    ("owner_id", "keyword"),
    ("acl_principals", "keyword"),
    ("index_version", "keyword"),
    ("chunk_type", "keyword"),
)


@dataclass(frozen=True, slots=True)
class _CollectionContract:
    dimension: int
    distance: str
    metadata: Mapping[str, object]
    status: str | None
    points_count: int | None


class QdrantStoreError(RuntimeError):
    """A safe vector-store error that never includes a response body or secret."""


class CollectionContractError(QdrantStoreError):
    """An existing collection conflicts with the immutable index contract."""


class WinnerApprovalError(QdrantStoreError):
    """The supplied approval is not bound to the exact candidate config."""


def _base_url(value: str) -> str:
    candidate = value.strip().rstrip("/")
    parsed = urlsplit(candidate)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError(
            "base_url must be an HTTP(S) origin without credentials, path, query, or fragment"
        )
    return f"{candidate}/"


def _mapping(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise QdrantStoreError(f"Qdrant response field {field_name} must be an object")
    return cast(dict[str, object], value)


def _array(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise QdrantStoreError(f"Qdrant response field {field_name} must be an array")
    return cast(list[object], value)


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise QdrantStoreError(f"Qdrant response field {field_name} must be a non-blank string")
    return value


def _optional_integer(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise QdrantStoreError(f"Qdrant response field {field_name} must be an integer or null")
    return value


def _finite_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise QdrantStoreError(f"Qdrant response field {field_name} must be numeric")
    result = float(value)
    if not math.isfinite(result):
        raise QdrantStoreError(f"Qdrant response field {field_name} must be finite")
    return result


def _uuid(value: object, field_name: str) -> UUID:
    try:
        return UUID(_string(value, field_name))
    except ValueError:
        raise QdrantStoreError(f"Qdrant response field {field_name} must be a UUID") from None


def _payload_json(payload: ChunkPayload) -> dict[str, object]:
    return {
        "tenant_id": str(payload.tenant_id),
        "document_id": str(payload.document_id),
        "version_id": str(payload.version_id),
        "chunk_id": str(payload.chunk_id),
        "parent_id": None if payload.parent_id is None else str(payload.parent_id),
        "owner_id": str(payload.owner_id),
        "acl_principals": list(payload.acl_principals),
        "source_name": payload.source_name,
        "mime_type": payload.mime_type,
        "page": payload.page,
        "slide": payload.slide,
        "sheet": payload.sheet,
        "cell_range": payload.cell_range,
        "line_start": payload.line_start,
        "line_end": payload.line_end,
        "section_path": list(payload.section_path),
        "language": payload.language,
        "text": payload.text,
        "token_count": payload.token_count,
        "content_hash": payload.content_hash,
        "index_version": payload.index_version,
        "created_at": payload.created_at.isoformat(),
        "chunk_type": payload.chunk_type,
    }


def _collection_metadata(config: IndexConfig) -> dict[str, object]:
    """Bind a physical collection to the complete index configuration."""

    return {
        "ntc_schema_version": 1,
        "ntc_config_fingerprint": config.fingerprint,
        "ntc_index_version": config.index_version,
        "ntc_embedding_model": config.embedding_model,
        "ntc_embedding_model_version": config.embedding_model_version,
        "ntc_vector_dimension": config.vector_dimension,
        "ntc_distance": config.distance,
        "ntc_chunk_size": config.chunk_size,
        "ntc_overlap_percent": config.overlap_percent,
    }


def _chunk_payload(value: object) -> ChunkPayload:
    payload = _mapping(value, "point.payload")
    raw_acl = _array(payload.get("acl_principals"), "payload.acl_principals")
    raw_sections = _array(payload.get("section_path"), "payload.section_path")
    raw_parent = payload.get("parent_id")
    raw_token_count = payload.get("token_count")
    if isinstance(raw_token_count, bool) or not isinstance(raw_token_count, int):
        raise QdrantStoreError("Qdrant response field payload.token_count must be an integer")
    try:
        created_at = datetime.fromisoformat(
            _string(payload.get("created_at"), "payload.created_at")
        )
    except ValueError:
        raise QdrantStoreError(
            "Qdrant response field payload.created_at must be an ISO datetime"
        ) from None
    try:
        return ChunkPayload(
            tenant_id=_uuid(payload.get("tenant_id"), "payload.tenant_id"),
            document_id=_uuid(payload.get("document_id"), "payload.document_id"),
            version_id=_uuid(payload.get("version_id"), "payload.version_id"),
            chunk_id=_uuid(payload.get("chunk_id"), "payload.chunk_id"),
            parent_id=None if raw_parent is None else _uuid(raw_parent, "payload.parent_id"),
            owner_id=_uuid(payload.get("owner_id"), "payload.owner_id"),
            acl_principals=tuple(_string(item, "payload.acl_principals[]") for item in raw_acl),
            source_name=_string(payload.get("source_name"), "payload.source_name"),
            mime_type=_string(payload.get("mime_type"), "payload.mime_type"),
            page=_optional_integer(payload.get("page"), "payload.page"),
            slide=_optional_integer(payload.get("slide"), "payload.slide"),
            sheet=(
                None
                if payload.get("sheet") is None
                else _string(payload.get("sheet"), "payload.sheet")
            ),
            cell_range=(
                None
                if payload.get("cell_range") is None
                else _string(payload.get("cell_range"), "payload.cell_range")
            ),
            line_start=_optional_integer(payload.get("line_start"), "payload.line_start"),
            line_end=_optional_integer(payload.get("line_end"), "payload.line_end"),
            section_path=tuple(_string(item, "payload.section_path[]") for item in raw_sections),
            language=_string(payload.get("language"), "payload.language"),
            text=_string(payload.get("text"), "payload.text"),
            token_count=raw_token_count,
            content_hash=_string(payload.get("content_hash"), "payload.content_hash"),
            index_version=_string(payload.get("index_version"), "payload.index_version"),
            created_at=created_at,
            chunk_type=_string(payload.get("chunk_type"), "payload.chunk_type"),  # type: ignore[arg-type]
        )
    except ValueError as error:
        raise QdrantStoreError(
            f"Qdrant point payload violates the domain contract: {error}"
        ) from None


class QdrantVectorIndex:
    """Qdrant adapter with immutable dimensions and mandatory in-query ACL filters."""

    def __init__(
        self,
        *,
        base_url: str,
        api_key: str | None = None,
        timeout_seconds: float = 30,
        hnsw_ef: int = 256,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if api_key is not None and not api_key:
            raise ValueError("api_key must be non-empty when provided")
        if not math.isfinite(timeout_seconds) or not 0 < timeout_seconds <= 300:
            raise ValueError("timeout_seconds must be finite and between 0 and 300")
        if isinstance(hnsw_ef, bool) or not 1 <= hnsw_ef <= 4096:
            raise ValueError("hnsw_ef must be an integer between 1 and 4096")
        headers = {"Accept": "application/json"}
        if api_key is not None:
            headers["api-key"] = api_key
        self._client = httpx.AsyncClient(
            base_url=_base_url(base_url),
            headers=headers,
            timeout=httpx.Timeout(timeout_seconds),
            follow_redirects=False,
            trust_env=False,
            transport=transport,
        )
        self._hnsw_ef = hnsw_ef

    def __repr__(self) -> str:
        return f"{type(self).__name__}()"

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, object] | None = None,
        allowed_statuses: frozenset[int] = frozenset({200}),
    ) -> tuple[int, Mapping[str, object] | None]:
        try:
            response = await self._client.request(method, path, json=body)
        except httpx.TransportError:
            raise QdrantStoreError("Qdrant request failed") from None
        if response.status_code not in allowed_statuses:
            raise QdrantStoreError(f"Qdrant returned HTTP {response.status_code}")
        if response.status_code == 404:
            return response.status_code, None
        try:
            parsed: object = response.json()
        except (ValueError, UnicodeDecodeError):
            raise QdrantStoreError("Qdrant returned a non-JSON response") from None
        return response.status_code, _mapping(parsed, "root")

    async def _collection_contract(self, collection_name: str) -> _CollectionContract | None:
        path = f"collections/{quote(collection_name, safe='')}"
        status, response = await self._request("GET", path, allowed_statuses=frozenset({200, 404}))
        if status == 404 or response is None:
            return None
        result = _mapping(response.get("result"), "result")
        config = _mapping(result.get("config"), "result.config")
        params = _mapping(config.get("params"), "result.config.params")
        vectors = _mapping(params.get("vectors"), "result.config.params.vectors")
        raw_size = vectors.get("size")
        if isinstance(raw_size, bool) or not isinstance(raw_size, int) or raw_size <= 0:
            raise QdrantStoreError("Qdrant collection vector size is invalid")
        distance = _string(vectors.get("distance"), "result.config.params.vectors.distance")
        raw_metadata = config.get("metadata")
        metadata: Mapping[str, object] = (
            {} if raw_metadata is None else _mapping(raw_metadata, "result.config.metadata")
        )
        raw_status = result.get("status")
        status_value = None if raw_status is None else _string(raw_status, "result.status").lower()
        raw_points_count = result.get("points_count")
        if raw_points_count is not None and (
            isinstance(raw_points_count, bool)
            or not isinstance(raw_points_count, int)
            or raw_points_count < 0
        ):
            raise QdrantStoreError(
                "Qdrant response field result.points_count must be a non-negative integer"
            )
        return _CollectionContract(
            raw_size,
            distance,
            metadata,
            status_value,
            raw_points_count,
        )

    @staticmethod
    def _verify_contract(config: IndexConfig, observed: _CollectionContract) -> None:
        if observed.dimension != config.vector_dimension:
            raise CollectionContractError(
                "existing collection dimension differs; create a new physical collection"
            )
        if observed.distance.lower() != config.distance.lower():
            raise CollectionContractError(
                "existing collection distance differs; create a new physical collection"
            )
        expected_metadata = _collection_metadata(config)
        if any(observed.metadata.get(key) != value for key, value in expected_metadata.items()):
            raise CollectionContractError(
                "existing collection metadata differs from the exact index config; "
                "create a new physical collection"
            )

    async def ensure_collection(self, config: IndexConfig) -> None:
        observed = await self._collection_contract(config.collection_name)
        if observed is None:
            path = f"collections/{quote(config.collection_name, safe='')}"
            status, _ = await self._request(
                "PUT",
                path,
                body={
                    "vectors": {
                        "size": config.vector_dimension,
                        "distance": config.distance,
                    },
                    "hnsw_config": {"m": 16, "ef_construct": 100},
                    "on_disk_payload": True,
                    "metadata": _collection_metadata(config),
                },
                allowed_statuses=frozenset({200, 409}),
            )
            if status == 409:
                observed = await self._collection_contract(config.collection_name)
                if observed is None:
                    raise QdrantStoreError("Qdrant collection create raced but remains absent")
                self._verify_contract(config, observed)
        else:
            self._verify_contract(config, observed)

        index_path = f"collections/{quote(config.collection_name, safe='')}/index"
        for field_name, field_schema in _PAYLOAD_INDEXES:
            await self._request(
                "PUT",
                index_path,
                body={"field_name": field_name, "field_schema": field_schema},
            )

    async def upsert(self, config: IndexConfig, points: Sequence[VectorPoint]) -> None:
        if not points:
            raise ValueError("points must not be empty")
        if len({point.point_id for point in points}) != len(points):
            raise ValueError("points must have unique point_id values")
        if any(len(point.vector) != config.vector_dimension for point in points):
            raise CollectionContractError("point vector dimension differs from index config")
        if any(point.payload.index_version != config.index_version for point in points):
            raise CollectionContractError("point index_version differs from index config")
        path = f"collections/{quote(config.collection_name, safe='')}/points?wait=true"
        await self._request(
            "PUT",
            path,
            body={
                "points": [
                    {
                        "id": str(point.point_id),
                        "vector": list(point.vector),
                        "payload": _payload_json(point.payload),
                    }
                    for point in points
                ]
            },
        )

    async def _alias_target(self, alias_name: str) -> str | None:
        _, response = await self._request("GET", "aliases")
        if response is None:
            raise QdrantStoreError("Qdrant aliases request returned no response")
        result = _mapping(response.get("result"), "result")
        aliases = _array(result.get("aliases"), "result.aliases")
        for position, value in enumerate(aliases):
            alias = _mapping(value, f"result.aliases[{position}]")
            if _string(alias.get("alias_name"), "alias_name") == alias_name:
                return _string(alias.get("collection_name"), "collection_name")
        return None

    async def search(
        self,
        config: IndexConfig,
        query_vector: tuple[float, ...],
        scope: AccessScope,
        *,
        limit: int,
        score_threshold: float | None,
        collection_target: str | None = None,
        hnsw_ef: int | None = None,
    ) -> tuple[SearchHit, ...]:
        if len(query_vector) != config.vector_dimension:
            raise CollectionContractError("query vector dimension differs from index config")
        if any(not math.isfinite(value) for value in query_vector):
            raise ValueError("query_vector must contain only finite values")
        if isinstance(limit, bool) or not 1 <= limit <= 100:
            raise ValueError("limit must be an integer between 1 and 100")
        if score_threshold is not None and not math.isfinite(score_threshold):
            raise ValueError("score_threshold must be finite when provided")
        resolved_hnsw_ef = self._hnsw_ef if hnsw_ef is None else hnsw_ef
        if isinstance(resolved_hnsw_ef, bool) or not 1 <= resolved_hnsw_ef <= 4096:
            raise ValueError("hnsw_ef must be an integer between 1 and 4096")

        target = config.collection_name if collection_target is None else collection_target
        if target != config.collection_name:
            if target != "ntc_chunks_active":
                raise ValueError(
                    "collection_target must be the physical collection or active alias"
                )
            active_target = await self._alias_target(target)
            if active_target != config.collection_name:
                raise CollectionContractError(
                    "active alias is not bound to the supplied physical index config"
                )

        must: list[object] = [
            {"key": "tenant_id", "match": {"value": str(scope.tenant_id)}},
            {"key": "acl_principals", "match": {"any": list(scope.acl_principals)}},
            {"key": "index_version", "match": {"value": config.index_version}},
            {"key": "chunk_type", "match": {"value": "child"}},
        ]
        if scope.document_ids:
            must.append(
                {
                    "key": "document_id",
                    "match": {"any": [str(document_id) for document_id in scope.document_ids]},
                }
            )
        body: dict[str, object] = {
            "query": list(query_vector),
            "filter": {"must": must},
            "limit": limit,
            "with_payload": True,
            "with_vector": False,
            "params": {"hnsw_ef": resolved_hnsw_ef, "exact": False},
        }
        if score_threshold is not None:
            body["score_threshold"] = score_threshold

        path = f"collections/{quote(target, safe='')}/points/query"
        status, response = await self._request(
            "POST", path, body=body, allowed_statuses=frozenset({200, 404})
        )
        if status == 404 or response is None:
            # Collection doesn't exist yet (no documents indexed) - return empty
            return ()
        result = _mapping(response.get("result"), "result")
        raw_points = _array(result.get("points"), "result.points")
        hits: list[SearchHit] = []
        for position, value in enumerate(raw_points):
            point = _mapping(value, f"result.points[{position}]")
            point_id = _uuid(point.get("id"), f"result.points[{position}].id")
            payload = _chunk_payload(point.get("payload"))
            if payload.tenant_id != scope.tenant_id:
                raise QdrantStoreError("Qdrant returned a point outside the tenant filter")
            if not set(payload.acl_principals).intersection(scope.acl_principals):
                raise QdrantStoreError("Qdrant returned a point outside the ACL filter")
            if scope.document_ids and payload.document_id not in scope.document_ids:
                raise QdrantStoreError("Qdrant returned a point outside the document filter")
            if payload.index_version != config.index_version:
                raise QdrantStoreError("Qdrant returned a point from another index version")
            if payload.chunk_type != "child":
                raise QdrantStoreError("Qdrant returned a point outside the child-chunk filter")
            hits.append(
                SearchHit(
                    point_id=point_id,
                    score=_finite_number(point.get("score"), f"result.points[{position}].score"),
                    payload=payload,
                )
            )
        if any(left.score < right.score for left, right in pairwise(hits)):
            raise QdrantStoreError("Qdrant returned points outside descending score order")
        return tuple(hits)

    async def activate_approved_winner(
        self,
        config: IndexConfig,
        approval: WinnerApproval,
        *,
        retrieval_policy: RetrievalPolicy,
        evidence: bytes,
        alias_name: str = "ntc_chunks_active",
    ) -> None:
        """Atomically switch the active alias only with exact human decision evidence."""

        if alias_name != "ntc_chunks_active":
            raise WinnerApprovalError("only the reviewed active alias may be changed")
        if approval.config_fingerprint != config.fingerprint:
            raise WinnerApprovalError("approval is not bound to this exact index config")
        if retrieval_policy.index_config_fingerprint != config.fingerprint:
            raise WinnerApprovalError("retrieval policy is not bound to this exact index config")
        if approval.retrieval_policy_fingerprint is None:
            raise WinnerApprovalError("approval does not bind a complete retrieval policy")
        if approval.retrieval_policy_fingerprint != retrieval_policy.fingerprint:
            raise WinnerApprovalError("approval is not bound to this exact retrieval policy")
        if approval.expected_point_count is None:
            raise WinnerApprovalError("approval does not bind the expected winner point count")
        if not evidence:
            raise WinnerApprovalError("approval evidence must not be empty")
        if hashlib.sha256(evidence).hexdigest() != approval.evidence_sha256:
            raise WinnerApprovalError("approval evidence hash does not match the supplied report")
        if config.collection_name == alias_name:
            raise WinnerApprovalError("physical collection name must differ from the active alias")

        observed = await self._collection_contract(config.collection_name)
        if observed is None:
            raise CollectionContractError(
                "approved winner collection does not exist; rebuild it before activation"
            )
        self._verify_contract(config, observed)
        if observed.status != "green":
            raise CollectionContractError("approved winner collection is not green")
        if observed.points_count != approval.expected_point_count:
            raise CollectionContractError(
                "approved winner collection point count differs from approval evidence"
            )

        current_collection = await self._alias_target(alias_name)
        if current_collection == config.collection_name:
            return

        actions: list[object] = []
        if current_collection is not None:
            actions.append({"delete_alias": {"alias_name": alias_name}})
        actions.append(
            {
                "create_alias": {
                    "collection_name": config.collection_name,
                    "alias_name": alias_name,
                }
            }
        )
        await self._request("POST", "collections/aliases", body={"actions": actions})
        if await self._alias_target(alias_name) != config.collection_name:
            raise QdrantStoreError("active alias readback does not match the approved winner")
