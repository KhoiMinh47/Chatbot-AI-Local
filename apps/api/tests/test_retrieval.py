"""Unit tests for Phase 5 embedding and dense retrieval use cases."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID

import pytest
from app.application.ai_clients import (
    EmbeddingRequest,
    EmbeddingResponse,
    RankedPassage,
    RerankRequest,
    RerankResponse,
)
from app.application.retrieval import DenseRetriever, EmbeddingBatchPipeline
from app.domain.retrieval import (
    AccessScope,
    ChunkPayload,
    IndexConfig,
    RetrievalPolicy,
    SearchHit,
    VectorPoint,
)

TENANT_ID = UUID("00000000-0000-4000-8000-000000000001")
OWNER_ID = UUID("00000000-0000-4000-8000-000000000002")
DOCUMENT_ID = UUID("00000000-0000-4000-8000-000000000003")
VERSION_ID = UUID("00000000-0000-4000-8000-000000000004")


def index_config(*, dimension: int = 2) -> IndexConfig:
    return IndexConfig(
        collection_name="ntc_chunks_embed300m_chunk512_o10_test",
        index_version="embed300m-v2_chunk512_o10_test",
        embedding_model="nvidia/embed-test",
        embedding_model_version="1.0.0",
        vector_dimension=dimension,
        chunk_size=512,
        overlap_percent=10,
    )


def retrieval_policy(
    *,
    dense_threshold: float = 0.3,
    hnsw_ef: int = 128,
    reranker_enabled: bool = False,
    hybrid_enabled: bool = False,
) -> RetrievalPolicy:
    return RetrievalPolicy(
        index_config_fingerprint=index_config().fingerprint,
        dense_candidate_limit=2,
        final_limit=1,
        dense_threshold=dense_threshold,
        hnsw_ef=hnsw_ef,
        reranker_enabled=reranker_enabled,
        reranker_model="nvidia/rerank-test" if reranker_enabled else None,
        reranker_model_version="1.0.0" if reranker_enabled else None,
        rerank_threshold=1.5 if reranker_enabled else None,
        hybrid_enabled=hybrid_enabled,
    )


def chunk(number: int) -> ChunkPayload:
    chunk_id = UUID(f"00000000-0000-4000-8000-{number:012d}")
    return ChunkPayload(
        tenant_id=TENANT_ID,
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
        chunk_id=chunk_id,
        parent_id=None,
        owner_id=OWNER_ID,
        acl_principals=(f"user:{OWNER_ID}", "group:engineering"),
        source_name="policy.md",
        mime_type="text/markdown",
        page=number,
        slide=None,
        section_path=(f"section-{number}",),
        language="vi",
        text=f"Nội dung kiểm thử {number}",
        token_count=4,
        content_hash=f"{number:064x}",
        index_version=index_config().index_version,
        created_at=datetime(2026, 7, 15, tzinfo=UTC),
    )


class FakeEmbeddingClient:
    def __init__(self, *, dimension: int = 2) -> None:
        self.dimension = dimension
        self.requests: list[EmbeddingRequest] = []

    async def embed(self, request: EmbeddingRequest) -> EmbeddingResponse:
        self.requests.append(request)
        vectors = tuple((float(index + 1), 0.5) for index, _ in enumerate(request.texts))
        if self.dimension != 2:
            vectors = tuple(
                tuple(float(index) for index in range(self.dimension)) for _ in request.texts
            )
        return EmbeddingResponse(
            vectors=vectors,
            dimension=self.dimension,
            model="nvidia/embed-test",
            model_version="1.0.0",
            latency_seconds=0.01,
        )

    async def aclose(self) -> None:
        return None


class FakeVectorIndex:
    def __init__(
        self,
        hits: tuple[SearchHit, ...] = (),
        *,
        respect_limit: bool = True,
    ) -> None:
        self.ensure_calls: list[IndexConfig] = []
        self.upsert_batches: list[tuple[object, ...]] = []
        self.search_calls: list[
            tuple[
                IndexConfig,
                tuple[float, ...],
                AccessScope,
                int,
                float | None,
                str | None,
                int | None,
            ]
        ] = []
        self.hits = hits
        self.respect_limit = respect_limit

    async def ensure_collection(self, config: IndexConfig) -> None:
        self.ensure_calls.append(config)

    async def upsert(self, config: IndexConfig, points: Sequence[VectorPoint]) -> None:
        del config
        self.upsert_batches.append(tuple(points))

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
        self.search_calls.append(
            (
                config,
                query_vector,
                scope,
                limit,
                score_threshold,
                collection_target,
                hnsw_ef,
            )
        )
        return self.hits[:limit] if self.respect_limit else self.hits


class FakeReranker:
    def __init__(self) -> None:
        self.requests: list[RerankRequest] = []

    async def rerank(self, request: RerankRequest) -> RerankResponse:
        self.requests.append(request)
        return RerankResponse(
            rankings=(
                RankedPassage(source_index=1, passage=request.passages[1], score=4.0),
                RankedPassage(source_index=0, passage=request.passages[0], score=2.0),
            ),
            model="nvidia/rerank-test",
            model_version="1.0.0",
            latency_seconds=0.02,
        )

    async def aclose(self) -> None:
        return None


class FakeLexicalIndex:
    def __init__(self, hits: tuple[SearchHit, ...]) -> None:
        self.hits = hits
        self.calls: list[tuple[str, AccessScope, str, int]] = []

    async def search(
        self,
        *,
        query: str,
        scope: AccessScope,
        index_version: str,
        limit: int,
    ) -> tuple[SearchHit, ...]:
        self.calls.append((query, scope, index_version, limit))
        return self.hits[:limit]


def test_index_config_fingerprint_is_stable_and_binds_dimension() -> None:
    baseline = index_config()
    assert baseline.fingerprint == index_config().fingerprint
    assert baseline.fingerprint != index_config(dimension=3).fingerprint


def test_retrieval_policy_fingerprint_binds_runtime_ranking_controls() -> None:
    baseline = retrieval_policy()

    assert baseline.fingerprint == retrieval_policy().fingerprint
    assert baseline.fingerprint != retrieval_policy(dense_threshold=0.4).fingerprint
    assert baseline.fingerprint != retrieval_policy(hnsw_ef=256).fingerprint
    assert baseline.fingerprint != retrieval_policy(reranker_enabled=True).fingerprint
    assert baseline.fingerprint != retrieval_policy(hybrid_enabled=True).fingerprint


def test_disabled_reranker_rejects_unbound_model_configuration() -> None:
    with pytest.raises(ValueError, match="disabled reranker"):
        RetrievalPolicy(
            index_config_fingerprint=index_config().fingerprint,
            dense_candidate_limit=20,
            final_limit=10,
            dense_threshold=0.3,
            hnsw_ef=128,
            reranker_enabled=False,
            reranker_model="unexpected-model",
        )


def test_chunk_payload_requires_owner_in_acl() -> None:
    payload = chunk(1)
    with pytest.raises(ValueError, match="include the owner"):
        replace(payload, acl_principals=("group:engineering",))


@pytest.mark.anyio
async def test_embedding_pipeline_batches_passages_and_preserves_order() -> None:
    embedding = FakeEmbeddingClient()
    vector_index = FakeVectorIndex()
    pipeline = EmbeddingBatchPipeline(
        embedding=embedding,
        vector_index=vector_index,
        batch_size=2,
    )

    result = await pipeline.index(index_config(), (chunk(1), chunk(2), chunk(3)))

    assert result.indexed_points == 3
    assert result.batches == 2
    assert vector_index.ensure_calls == [index_config()]
    assert [request.input_type for request in embedding.requests] == ["passage", "passage"]
    assert [request.texts for request in embedding.requests] == [
        (chunk(1).text, chunk(2).text),
        (chunk(3).text,),
    ]
    assert [len(batch) for batch in vector_index.upsert_batches] == [2, 1]


@pytest.mark.anyio
async def test_embedding_pipeline_rejects_dimension_drift_before_upsert() -> None:
    vector_index = FakeVectorIndex()
    pipeline = EmbeddingBatchPipeline(
        embedding=FakeEmbeddingClient(dimension=3),
        vector_index=vector_index,
    )

    with pytest.raises(RuntimeError, match="dimension"):
        await pipeline.index(index_config(), (chunk(1),))

    assert vector_index.upsert_batches == []


@pytest.mark.anyio
async def test_dense_retriever_uses_query_mode_and_retains_both_ranks() -> None:
    first = SearchHit(point_id=chunk(1).chunk_id, score=0.9, payload=chunk(1))
    second = SearchHit(point_id=chunk(2).chunk_id, score=0.8, payload=chunk(2))
    vector_index = FakeVectorIndex((first, second))
    embedding = FakeEmbeddingClient()
    reranker = FakeReranker()
    retriever = DenseRetriever(
        embedding=embedding,
        vector_index=vector_index,
        reranking=reranker,
    )
    scope = AccessScope(TENANT_ID, (f"user:{OWNER_ID}",))

    result = await retriever.retrieve(
        query="Chính sách là gì?",
        scope=scope,
        config=index_config(),
        candidate_limit=2,
        final_limit=2,
    )

    assert embedding.requests[0].input_type == "query"
    assert vector_index.search_calls[0][2] == scope
    assert [ranked.hit.point_id for ranked in result.hits] == [second.point_id, first.point_id]
    assert [ranked.dense_rank for ranked in result.hits] == [2, 1]
    assert [ranked.final_rank for ranked in result.hits] == [1, 2]
    assert [ranked.rerank_score for ranked in result.hits] == [4.0, 2.0]


@pytest.mark.anyio
async def test_dense_retriever_applies_rerank_threshold_without_backfilling() -> None:
    hits = tuple(
        SearchHit(point_id=chunk(number).chunk_id, score=1.0 - number / 10, payload=chunk(number))
        for number in (1, 2)
    )
    retriever = DenseRetriever(
        embedding=FakeEmbeddingClient(),
        vector_index=FakeVectorIndex(hits),
        reranking=FakeReranker(),
    )

    result = await retriever.retrieve(
        query="policy",
        scope=AccessScope(TENANT_ID, (f"user:{OWNER_ID}",)),
        config=index_config(),
        candidate_limit=2,
        final_limit=2,
        rerank_threshold=3.0,
    )

    assert len(result.hits) == 1
    assert result.hits[0].hit.point_id == chunk(2).chunk_id


@pytest.mark.anyio
async def test_dense_retriever_diversifies_sections_before_final_limit() -> None:
    first_payload = chunk(1)
    duplicate_section = replace(
        chunk(2),
        document_id=first_payload.document_id,
        section_path=first_payload.section_path,
    )
    hits = (
        SearchHit(point_id=first_payload.chunk_id, score=0.9, payload=first_payload),
        SearchHit(
            point_id=duplicate_section.chunk_id,
            score=0.8,
            payload=duplicate_section,
        ),
        SearchHit(point_id=chunk(3).chunk_id, score=0.7, payload=chunk(3)),
    )
    retriever = DenseRetriever(
        embedding=FakeEmbeddingClient(),
        vector_index=FakeVectorIndex(hits),
    )

    result = await retriever.retrieve(
        query="policy",
        scope=AccessScope(TENANT_ID, (f"user:{OWNER_ID}",)),
        config=index_config(),
        candidate_limit=3,
        final_limit=2,
    )

    assert [ranked.hit.point_id for ranked in result.hits] == [
        first_payload.chunk_id,
        duplicate_section.chunk_id,
    ]
    assert [ranked.dense_rank for ranked in result.hits] == [1, 2]


@pytest.mark.anyio
async def test_hybrid_retriever_fuses_dense_and_lexical_with_rrf() -> None:
    dense = (
        SearchHit(point_id=chunk(1).chunk_id, score=0.9, payload=chunk(1)),
        SearchHit(point_id=chunk(2).chunk_id, score=0.8, payload=chunk(2)),
    )
    lexical = FakeLexicalIndex(
        (
            SearchHit(point_id=chunk(2).chunk_id, score=0.7, payload=chunk(2)),
            SearchHit(point_id=chunk(3).chunk_id, score=0.6, payload=chunk(3)),
        )
    )
    retriever = DenseRetriever(
        embedding=FakeEmbeddingClient(),
        vector_index=FakeVectorIndex(dense),
        lexical_index=lexical,
    )
    scope = AccessScope(TENANT_ID, (f"user:{OWNER_ID}",))

    result = await retriever.retrieve(
        query="Mã chính sách 123",
        scope=scope,
        config=index_config(),
        candidate_limit=3,
        final_limit=3,
    )

    assert result.hybrid is True
    assert result.lexical_candidates == 2
    assert result.dense_candidates == 3
    assert [ranked.hit.point_id for ranked in result.hits] == [
        chunk(2).chunk_id,
        chunk(1).chunk_id,
        chunk(3).chunk_id,
    ]
    assert lexical.calls == [("Mã chính sách 123", scope, index_config().index_version, 3)]


@pytest.mark.anyio
async def test_dense_retriever_applies_bound_policy_and_active_alias_route() -> None:
    hits = (
        SearchHit(point_id=chunk(1).chunk_id, score=0.9, payload=chunk(1)),
        SearchHit(point_id=chunk(2).chunk_id, score=0.8, payload=chunk(2)),
    )
    vector_index = FakeVectorIndex(hits)
    reranker = FakeReranker()
    policy = retrieval_policy(hnsw_ef=321)
    retriever = DenseRetriever(
        embedding=FakeEmbeddingClient(),
        vector_index=vector_index,
        reranking=reranker,
        collection_target="ntc_chunks_active",
    )

    result = await retriever.retrieve(
        query="policy",
        scope=AccessScope(TENANT_ID, (f"user:{OWNER_ID}",)),
        config=index_config(),
        retrieval_policy=policy,
    )

    assert len(result.hits) == 1
    assert reranker.requests == []
    assert vector_index.search_calls[0][3:] == (
        2,
        0.3,
        "ntc_chunks_active",
        321,
    )
    assert result.retrieval_policy_fingerprint == policy.fingerprint


@pytest.mark.anyio
async def test_dense_retriever_applies_mode_cap_to_policy_bound_qdrant_search() -> None:
    hits = (
        SearchHit(point_id=chunk(1).chunk_id, score=0.9, payload=chunk(1)),
        SearchHit(point_id=chunk(2).chunk_id, score=0.8, payload=chunk(2)),
    )
    vector_index = FakeVectorIndex(hits)
    retriever = DenseRetriever(
        embedding=FakeEmbeddingClient(),
        vector_index=vector_index,
        collection_target="ntc_chunks_active",
    )

    result = await retriever.retrieve(
        query="policy",
        scope=AccessScope(TENANT_ID, (f"user:{OWNER_ID}",)),
        config=index_config(),
        retrieval_policy=retrieval_policy(),
        candidate_limit_cap=1,
    )

    assert vector_index.search_calls[0][3] == 1
    assert result.dense_candidates == 1
    assert len(result.hits) == 1


@pytest.mark.anyio
async def test_dense_retriever_rejects_index_returning_more_than_requested_cap() -> None:
    hits = (
        SearchHit(point_id=chunk(1).chunk_id, score=0.9, payload=chunk(1)),
        SearchHit(point_id=chunk(2).chunk_id, score=0.8, payload=chunk(2)),
    )
    retriever = DenseRetriever(
        embedding=FakeEmbeddingClient(),
        vector_index=FakeVectorIndex(hits, respect_limit=False),
    )

    with pytest.raises(RuntimeError, match="more hits than the requested"):
        await retriever.retrieve(
            query="policy",
            scope=AccessScope(TENANT_ID, (f"user:{OWNER_ID}",)),
            config=index_config(),
            retrieval_policy=retrieval_policy(),
            candidate_limit_cap=1,
        )


@pytest.mark.anyio
@pytest.mark.parametrize("invalid_cap", [True, 0, 101])
async def test_dense_retriever_rejects_invalid_candidate_limit_cap(
    invalid_cap: int,
) -> None:
    retriever = DenseRetriever(
        embedding=FakeEmbeddingClient(),
        vector_index=FakeVectorIndex(),
    )

    with pytest.raises(ValueError, match="candidate_limit_cap"):
        await retriever.retrieve(
            query="policy",
            scope=AccessScope(TENANT_ID, (f"user:{OWNER_ID}",)),
            config=index_config(),
            retrieval_policy=retrieval_policy(),
            candidate_limit_cap=invalid_cap,
        )


@pytest.mark.anyio
async def test_dense_retriever_rejects_policy_bound_to_another_index() -> None:
    wrong_policy = replace(
        retrieval_policy(),
        index_config_fingerprint=index_config(dimension=3).fingerprint,
    )
    retriever = DenseRetriever(
        embedding=FakeEmbeddingClient(),
        vector_index=FakeVectorIndex(),
    )

    with pytest.raises(ValueError, match="not bound"):
        await retriever.retrieve(
            query="policy",
            scope=AccessScope(TENANT_ID, (f"user:{OWNER_ID}",)),
            config=index_config(),
            retrieval_policy=wrong_policy,
        )
