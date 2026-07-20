"""Opt-in live Qdrant acceptance tests for Phase 5 security invariants."""

from __future__ import annotations

import hashlib
import os
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx2 as httpx
import pytest
from app.domain.retrieval import AccessScope, ChunkPayload, IndexConfig, VectorPoint
from app.infrastructure.qdrant_store import CollectionContractError, QdrantVectorIndex

QDRANT_URL = os.getenv("PHASE5_QDRANT_URL")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not QDRANT_URL, reason="PHASE5_QDRANT_URL is not configured"),
]

TENANT_A = UUID("30000000-0000-4000-8000-000000000001")
TENANT_B = UUID("30000000-0000-4000-8000-000000000002")
USER_A = UUID("30000000-0000-4000-8000-000000000011")
USER_B = UUID("30000000-0000-4000-8000-000000000012")
DOCUMENT_A = UUID("30000000-0000-4000-8000-000000000021")
DOCUMENT_B = UUID("30000000-0000-4000-8000-000000000022")
VERSION_A = UUID("30000000-0000-4000-8000-000000000031")
VERSION_B = UUID("30000000-0000-4000-8000-000000000032")


def make_payload(
    *,
    chunk_id: UUID,
    tenant_id: UUID,
    owner_id: UUID,
    document_id: UUID,
    version_id: UUID,
    index_version: str,
) -> ChunkPayload:
    text = f"private evidence for {owner_id}"
    return ChunkPayload(
        tenant_id=tenant_id,
        document_id=document_id,
        version_id=version_id,
        chunk_id=chunk_id,
        parent_id=None,
        owner_id=owner_id,
        acl_principals=(f"user:{owner_id}",),
        source_name="acl-fixture.md",
        mime_type="text/markdown",
        page=1,
        slide=None,
        section_path=("ACL",),
        language="en",
        text=text,
        token_count=5,
        content_hash=hashlib.sha256(text.encode()).hexdigest(),
        index_version=index_version,
        created_at=datetime.now(UTC),
    )


@pytest.mark.anyio
async def test_live_collection_dimension_and_acl_are_enforced() -> None:
    assert QDRANT_URL is not None
    suffix = uuid4().hex[:12]
    collection_name = f"ntc_phase5_acl_{suffix}"
    index_version = f"phase5-acl-{suffix}"
    config = IndexConfig(
        collection_name=collection_name,
        index_version=index_version,
        embedding_model="integration-fixture",
        embedding_model_version="1",
        vector_dimension=2,
        chunk_size=512,
        overlap_percent=10,
    )
    client = QdrantVectorIndex(base_url=QDRANT_URL)
    cleanup_client = httpx.AsyncClient(base_url=f"{QDRANT_URL.rstrip('/')}/", trust_env=False)
    try:
        await client.ensure_collection(config)
        point_a = uuid4()
        point_b = uuid4()
        point_other_tenant = uuid4()
        await client.upsert(
            config,
            (
                VectorPoint(
                    point_id=point_a,
                    vector=(1.0, 0.0),
                    payload=make_payload(
                        chunk_id=point_a,
                        tenant_id=TENANT_A,
                        owner_id=USER_A,
                        document_id=DOCUMENT_A,
                        version_id=VERSION_A,
                        index_version=index_version,
                    ),
                ),
                VectorPoint(
                    point_id=point_b,
                    vector=(1.0, 0.0),
                    payload=make_payload(
                        chunk_id=point_b,
                        tenant_id=TENANT_A,
                        owner_id=USER_B,
                        document_id=DOCUMENT_B,
                        version_id=VERSION_B,
                        index_version=index_version,
                    ),
                ),
                VectorPoint(
                    point_id=point_other_tenant,
                    vector=(1.0, 0.0),
                    payload=make_payload(
                        chunk_id=point_other_tenant,
                        tenant_id=TENANT_B,
                        owner_id=USER_A,
                        document_id=DOCUMENT_A,
                        version_id=VERSION_A,
                        index_version=index_version,
                    ),
                ),
            ),
        )

        user_a_hits = await client.search(
            config,
            (1.0, 0.0),
            AccessScope(TENANT_A, (f"user:{USER_A}",)),
            limit=10,
            score_threshold=None,
        )
        user_b_hits = await client.search(
            config,
            (1.0, 0.0),
            AccessScope(TENANT_A, (f"user:{USER_B}",)),
            limit=10,
            score_threshold=None,
        )
        other_tenant_hits = await client.search(
            config,
            (1.0, 0.0),
            AccessScope(TENANT_B, (f"user:{USER_A}",)),
            limit=10,
            score_threshold=None,
        )

        assert [hit.point_id for hit in user_a_hits] == [point_a]
        assert [hit.point_id for hit in user_b_hits] == [point_b]
        assert [hit.point_id for hit in other_tenant_hits] == [point_other_tenant]

        incompatible = IndexConfig(
            collection_name=collection_name,
            index_version=index_version,
            embedding_model="integration-fixture",
            embedding_model_version="1",
            vector_dimension=3,
            chunk_size=512,
            overlap_percent=10,
        )
        with pytest.raises(CollectionContractError, match="new physical collection"):
            await client.ensure_collection(incompatible)

        same_dimension_wrong_model = IndexConfig(
            collection_name=collection_name,
            index_version=index_version,
            embedding_model="integration-fixture-other-model",
            embedding_model_version="1",
            vector_dimension=2,
            chunk_size=512,
            overlap_percent=10,
        )
        with pytest.raises(CollectionContractError, match="metadata differs"):
            await client.ensure_collection(same_dimension_wrong_model)
    finally:
        await client.aclose()
        await cleanup_client.delete(f"collections/{collection_name}")
        await cleanup_client.aclose()
