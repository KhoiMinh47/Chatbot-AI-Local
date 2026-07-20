"""Contract tests for immutable Qdrant collections and store-side ACL filters."""

from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import UTC, datetime
from uuid import UUID

import httpx2 as httpx
import pytest
from app.domain.retrieval import (
    AccessScope,
    ChunkPayload,
    IndexConfig,
    RetrievalPolicy,
    VectorPoint,
    WinnerApproval,
)
from app.infrastructure.qdrant_store import (
    CollectionContractError,
    QdrantStoreError,
    QdrantVectorIndex,
    WinnerApprovalError,
)

TENANT_ID = UUID("10000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("10000000-0000-4000-8000-000000000002")
DOCUMENT_ID = UUID("10000000-0000-4000-8000-000000000003")
VERSION_ID = UUID("10000000-0000-4000-8000-000000000004")
CHUNK_ID = UUID("10000000-0000-4000-8000-000000000005")


def config(*, dimension: int = 2) -> IndexConfig:
    return IndexConfig(
        collection_name="ntc_chunks_candidate_test",
        index_version="candidate-test-v1",
        embedding_model="nvidia/embed-test",
        embedding_model_version="1.0.0",
        vector_dimension=dimension,
        chunk_size=512,
        overlap_percent=10,
    )


def retrieval_policy(*, dense_threshold: float = 0.3) -> RetrievalPolicy:
    return RetrievalPolicy(
        index_config_fingerprint=config().fingerprint,
        dense_candidate_limit=20,
        final_limit=10,
        dense_threshold=dense_threshold,
        hnsw_ef=128,
        reranker_enabled=False,
    )


def winner_approval(
    *,
    evidence: bytes = b"winner-report",
    expected_point_count: int = 1,
    policy: RetrievalPolicy | None = None,
) -> WinnerApproval:
    selected_policy = policy or retrieval_policy()
    return WinnerApproval(
        config_fingerprint=config().fingerprint,
        evidence_sha256=hashlib.sha256(evidence).hexdigest(),
        approved_by="retrieval-review-board",
        approved_at=datetime(2026, 7, 15, tzinfo=UTC),
        retrieval_policy_fingerprint=selected_policy.fingerprint,
        expected_point_count=expected_point_count,
    )


def payload(*, acl_principals: tuple[str, ...] | None = None) -> ChunkPayload:
    return ChunkPayload(
        tenant_id=TENANT_ID,
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
        chunk_id=CHUNK_ID,
        parent_id=None,
        owner_id=OWNER_ID,
        acl_principals=acl_principals or (f"user:{OWNER_ID}", "group:engineering"),
        source_name="handbook.pdf",
        mime_type="application/pdf",
        page=2,
        slide=None,
        section_path=("Leave",),
        language="vi",
        text="Nhân viên có mười hai ngày phép mỗi năm.",
        token_count=12,
        content_hash="b" * 64,
        index_version=config().index_version,
        created_at=datetime(2026, 7, 15, 1, 2, 3, tzinfo=UTC),
    )


def payload_json(value: ChunkPayload) -> dict[str, object]:
    return {
        "tenant_id": str(value.tenant_id),
        "document_id": str(value.document_id),
        "version_id": str(value.version_id),
        "chunk_id": str(value.chunk_id),
        "parent_id": None,
        "owner_id": str(value.owner_id),
        "acl_principals": list(value.acl_principals),
        "source_name": value.source_name,
        "mime_type": value.mime_type,
        "page": value.page,
        "slide": value.slide,
        "section_path": list(value.section_path),
        "language": value.language,
        "text": value.text,
        "token_count": value.token_count,
        "content_hash": value.content_hash,
        "index_version": value.index_version,
        "created_at": value.created_at.isoformat(),
        "chunk_type": "child",
    }


def collection_metadata(value: IndexConfig) -> dict[str, object]:
    return {
        "ntc_schema_version": 1,
        "ntc_config_fingerprint": value.fingerprint,
        "ntc_index_version": value.index_version,
        "ntc_embedding_model": value.embedding_model,
        "ntc_embedding_model_version": value.embedding_model_version,
        "ntc_vector_dimension": value.vector_dimension,
        "ntc_distance": value.distance,
        "ntc_chunk_size": value.chunk_size,
        "ntc_overlap_percent": value.overlap_percent,
    }


def collection_response(
    *,
    dimension: int = 2,
    distance: str = "Cosine",
    metadata: dict[str, object] | None = None,
    collection_status: str | None = None,
    points_count: int | None = None,
) -> dict[str, object]:
    collection_config: dict[str, object] = {
        "params": {"vectors": {"size": dimension, "distance": distance}}
    }
    if metadata is not None:
        collection_config["metadata"] = metadata
    result: dict[str, object] = {"config": collection_config}
    if collection_status is not None:
        result["status"] = collection_status
    if points_count is not None:
        result["points_count"] = points_count
    return {"result": result, "status": "ok"}


def request_json(request: httpx.Request) -> dict[str, object]:
    parsed: object = json.loads(request.content)
    assert isinstance(parsed, dict)
    return parsed


def test_ensure_collection_creates_physical_index_and_payload_indexes() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET":
            return httpx.Response(404, json={"status": {"error": "not found"}})
        return httpx.Response(200, json={"result": True, "status": "ok"})

    async def scenario() -> None:
        client = QdrantVectorIndex(
            base_url="http://qdrant.test:6333",
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.ensure_collection(config())
        finally:
            await client.aclose()

    asyncio.run(scenario())
    create = next(
        request
        for request in requests
        if request.method == "PUT" and request.url.path.endswith("candidate_test")
    )
    create_body = request_json(create)
    assert create.method == "PUT"
    assert create_body["vectors"] == {"size": 2, "distance": "Cosine"}
    assert create_body["metadata"] == collection_metadata(config())

    indexes = [request_json(request) for request in requests if request.url.path.endswith("/index")]
    assert {item["field_name"] for item in indexes} >= {
        "tenant_id",
        "document_id",
        "acl_principals",
        "index_version",
    }


def test_existing_collection_dimension_is_immutable() -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=collection_response(dimension=3))

    async def scenario() -> None:
        client = QdrantVectorIndex(
            base_url="http://qdrant.test:6333",
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(CollectionContractError, match="new physical collection"):
                await client.ensure_collection(config())
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_existing_collection_must_match_complete_index_config() -> None:
    mismatched_metadata = collection_metadata(config())
    mismatched_metadata["ntc_embedding_model"] = "nvidia/another-model"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=collection_response(metadata=mismatched_metadata))

    async def scenario() -> None:
        client = QdrantVectorIndex(
            base_url="http://qdrant.test:6333",
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(CollectionContractError, match="metadata differs"):
                await client.ensure_collection(config())
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_upsert_rejects_dimension_drift_before_network() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"result": True})

    async def scenario() -> None:
        client = QdrantVectorIndex(
            base_url="http://qdrant.test:6333",
            transport=httpx.MockTransport(handler),
        )
        point = VectorPoint(point_id=CHUNK_ID, vector=(1.0, 2.0, 3.0), payload=payload())
        try:
            with pytest.raises(CollectionContractError, match="dimension"):
                await client.upsert(config(), (point,))
        finally:
            await client.aclose()

    asyncio.run(scenario())
    assert called is False


def test_search_sends_tenant_acl_index_and_document_filters_inside_query() -> None:
    captured: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(request_json(request))
        return httpx.Response(
            200,
            json={
                "result": {
                    "points": [
                        {"id": str(CHUNK_ID), "score": 0.92, "payload": payload_json(payload())}
                    ]
                },
                "status": "ok",
            },
        )

    async def scenario() -> None:
        client = QdrantVectorIndex(
            base_url="http://qdrant.test:6333",
            transport=httpx.MockTransport(handler),
        )
        try:
            hits = await client.search(
                config(),
                (1.0, 0.0),
                AccessScope(
                    tenant_id=TENANT_ID,
                    acl_principals=("group:engineering",),
                    document_ids=(DOCUMENT_ID,),
                ),
                limit=10,
                score_threshold=0.2,
            )
            assert len(hits) == 1
        finally:
            await client.aclose()

    asyncio.run(scenario())
    query_filter = captured["filter"]
    assert isinstance(query_filter, dict)
    conditions = query_filter["must"]
    assert isinstance(conditions, list)
    assert {condition["key"] for condition in conditions} == {
        "tenant_id",
        "acl_principals",
        "index_version",
        "chunk_type",
        "document_id",
    }
    acl = next(condition for condition in conditions if condition["key"] == "acl_principals")
    assert acl["match"] == {"any": ["group:engineering"]}


def test_search_fails_closed_if_store_returns_point_outside_acl() -> None:
    foreign_owner = UUID("20000000-0000-4000-8000-000000000002")
    foreign_payload = payload(acl_principals=(f"user:{OWNER_ID}", f"user:{foreign_owner}"))

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": {
                    "points": [
                        {
                            "id": str(CHUNK_ID),
                            "score": 0.9,
                            "payload": payload_json(foreign_payload),
                        }
                    ]
                }
            },
        )

    async def scenario() -> None:
        client = QdrantVectorIndex(
            base_url="http://qdrant.test:6333",
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(QdrantStoreError, match="outside the ACL"):
                await client.search(
                    config(),
                    (1.0, 0.0),
                    AccessScope(TENANT_ID, ("group:finance",)),
                    limit=10,
                    score_threshold=None,
                )
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_search_fails_closed_if_store_returns_non_child_point() -> None:
    returned_payload = payload_json(payload())
    returned_payload["chunk_type"] = "parent"

    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "result": {
                    "points": [{"id": str(CHUNK_ID), "score": 0.9, "payload": returned_payload}]
                }
            },
        )

    async def scenario() -> None:
        client = QdrantVectorIndex(
            base_url="http://qdrant.test:6333",
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(QdrantStoreError, match="domain contract"):
                await client.search(
                    config(),
                    (1.0, 0.0),
                    AccessScope(TENANT_ID, (f"user:{OWNER_ID}",)),
                    limit=10,
                    score_threshold=None,
                )
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_search_routes_through_active_alias_with_physical_config_binding() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.method == "GET" and request.url.path.endswith("/aliases"):
            return httpx.Response(
                200,
                json={
                    "result": {
                        "aliases": [
                            {
                                "alias_name": "ntc_chunks_active",
                                "collection_name": config().collection_name,
                            }
                        ]
                    }
                },
            )
        return httpx.Response(200, json={"result": {"points": []}})

    async def scenario() -> None:
        client = QdrantVectorIndex(
            base_url="http://qdrant.test:6333",
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.search(
                config(),
                (1.0, 0.0),
                AccessScope(TENANT_ID, (f"user:{OWNER_ID}",)),
                limit=10,
                score_threshold=0.2,
                collection_target="ntc_chunks_active",
                hnsw_ef=321,
            )
        finally:
            await client.aclose()

    asyncio.run(scenario())
    query = next(request for request in requests if request.method == "POST")
    assert query.url.path.endswith("/collections/ntc_chunks_active/points/query")
    assert request_json(query)["params"] == {"hnsw_ef": 321, "exact": False}


def test_search_rejects_active_alias_bound_to_another_physical_config() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "result": {
                    "aliases": [
                        {
                            "alias_name": "ntc_chunks_active",
                            "collection_name": "ntc_chunks_other_winner",
                        }
                    ]
                }
            },
        )

    async def scenario() -> None:
        client = QdrantVectorIndex(
            base_url="http://qdrant.test:6333",
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(CollectionContractError, match="active alias"):
                await client.search(
                    config(),
                    (1.0, 0.0),
                    AccessScope(TENANT_ID, (f"user:{OWNER_ID}",)),
                    limit=10,
                    score_threshold=None,
                    collection_target="ntc_chunks_active",
                )
        finally:
            await client.aclose()

    asyncio.run(scenario())
    assert [request.method for request in requests] == ["GET"]


def test_active_alias_requires_exact_approval_binding() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"result": True})

    approval = WinnerApproval(
        config_fingerprint="0" * 64,
        evidence_sha256="1" * 64,
        approved_by="retrieval-review-board",
        approved_at=datetime(2026, 7, 15, tzinfo=UTC),
        retrieval_policy_fingerprint=retrieval_policy().fingerprint,
        expected_point_count=1,
    )

    async def scenario() -> None:
        client = QdrantVectorIndex(
            base_url="http://qdrant.test:6333",
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(WinnerApprovalError, match="not bound"):
                await client.activate_approved_winner(
                    config(),
                    approval,
                    retrieval_policy=retrieval_policy(),
                    evidence=b"report",
                )
        finally:
            await client.aclose()

    asyncio.run(scenario())
    assert called is False


def test_active_alias_verifies_approval_evidence_content() -> None:
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"result": True})

    approval = WinnerApproval(
        config_fingerprint=config().fingerprint,
        evidence_sha256="1" * 64,
        approved_by="retrieval-review-board",
        approved_at=datetime(2026, 7, 15, tzinfo=UTC),
        retrieval_policy_fingerprint=retrieval_policy().fingerprint,
        expected_point_count=1,
    )

    async def scenario() -> None:
        client = QdrantVectorIndex(
            base_url="http://qdrant.test:6333",
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(WinnerApprovalError, match="evidence hash"):
                await client.activate_approved_winner(
                    config(),
                    approval,
                    retrieval_policy=retrieval_policy(),
                    evidence=b"report",
                )
        finally:
            await client.aclose()

    asyncio.run(scenario())
    assert called is False


def test_active_alias_requires_complete_retrieval_policy_binding() -> None:
    called = False
    approved_policy = retrieval_policy(dense_threshold=0.4)
    approval = winner_approval(policy=approved_policy)

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(200, json={"result": True})

    async def scenario() -> None:
        client = QdrantVectorIndex(
            base_url="http://qdrant.test:6333",
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(WinnerApprovalError, match="retrieval policy"):
                await client.activate_approved_winner(
                    config(),
                    approval,
                    retrieval_policy=retrieval_policy(),
                    evidence=b"winner-report",
                )
        finally:
            await client.aclose()

    asyncio.run(scenario())
    assert called is False


def test_activation_never_creates_a_missing_winner_collection() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(404, json={"status": {"error": "not found"}})

    async def scenario() -> None:
        client = QdrantVectorIndex(
            base_url="http://qdrant.test:6333",
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(CollectionContractError, match="does not exist"):
                await client.activate_approved_winner(
                    config(),
                    winner_approval(),
                    retrieval_policy=retrieval_policy(),
                    evidence=b"winner-report",
                )
        finally:
            await client.aclose()

    asyncio.run(scenario())
    assert [request.method for request in requests] == ["GET"]


@pytest.mark.parametrize(
    ("collection_status", "points_count", "error"),
    (("yellow", 1, "not green"), ("green", 2, "point count")),
)
def test_activation_requires_green_collection_and_approved_point_count(
    collection_status: str,
    points_count: int,
    error: str,
) -> None:
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json=collection_response(
                metadata=collection_metadata(config()),
                collection_status=collection_status,
                points_count=points_count,
            ),
        )

    async def scenario() -> None:
        client = QdrantVectorIndex(
            base_url="http://qdrant.test:6333",
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(CollectionContractError, match=error):
                await client.activate_approved_winner(
                    config(),
                    winner_approval(),
                    retrieval_policy=retrieval_policy(),
                    evidence=b"winner-report",
                )
        finally:
            await client.aclose()

    asyncio.run(scenario())


def test_activation_switches_alias_atomically_and_verifies_readback() -> None:
    requests: list[httpx.Request] = []
    activated = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal activated
        requests.append(request)
        if request.method == "GET" and "/collections/" in request.url.path:
            return httpx.Response(
                200,
                json=collection_response(
                    metadata=collection_metadata(config()),
                    collection_status="green",
                    points_count=1,
                ),
            )
        if request.method == "GET" and request.url.path.endswith("/aliases"):
            aliases: list[dict[str, str]] = []
            if activated:
                aliases.append(
                    {
                        "alias_name": "ntc_chunks_active",
                        "collection_name": config().collection_name,
                    }
                )
            return httpx.Response(200, json={"result": {"aliases": aliases}})
        if request.method == "POST" and request.url.path.endswith("/collections/aliases"):
            activated = True
            return httpx.Response(200, json={"result": True})
        raise AssertionError(f"unexpected request: {request.method} {request.url.path}")

    async def scenario() -> None:
        client = QdrantVectorIndex(
            base_url="http://qdrant.test:6333",
            transport=httpx.MockTransport(handler),
        )
        try:
            await client.activate_approved_winner(
                config(),
                winner_approval(),
                retrieval_policy=retrieval_policy(),
                evidence=b"winner-report",
            )
        finally:
            await client.aclose()

    asyncio.run(scenario())
    alias_update = next(request for request in requests if request.method == "POST")
    assert request_json(alias_update) == {
        "actions": [
            {
                "create_alias": {
                    "collection_name": config().collection_name,
                    "alias_name": "ntc_chunks_active",
                }
            }
        ]
    }
    assert activated is True


def test_activation_fails_if_alias_readback_does_not_confirm_switch() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and "/collections/" in request.url.path:
            return httpx.Response(
                200,
                json=collection_response(
                    metadata=collection_metadata(config()),
                    collection_status="green",
                    points_count=1,
                ),
            )
        if request.method == "GET" and request.url.path.endswith("/aliases"):
            return httpx.Response(200, json={"result": {"aliases": []}})
        return httpx.Response(200, json={"result": True})

    async def scenario() -> None:
        client = QdrantVectorIndex(
            base_url="http://qdrant.test:6333",
            transport=httpx.MockTransport(handler),
        )
        try:
            with pytest.raises(QdrantStoreError, match="readback"):
                await client.activate_approved_winner(
                    config(),
                    winner_approval(),
                    retrieval_policy=retrieval_policy(),
                    evidence=b"winner-report",
                )
        finally:
            await client.aclose()

    asyncio.run(scenario())
