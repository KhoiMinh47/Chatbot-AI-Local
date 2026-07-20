"""Phase 5 embedding, indexing, dense retrieval, and reranking use cases."""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Protocol

from app.application.ai_clients import (
    EmbeddingClient,
    EmbeddingRequest,
    RerankClient,
    RerankRequest,
)
from app.domain.retrieval import (
    AccessScope,
    ChunkPayload,
    IndexConfig,
    RankedHit,
    RetrievalPolicy,
    SearchHit,
    VectorPoint,
)

_log = logging.getLogger(__name__)


class VectorIndex(Protocol):
    """Application port implemented by a vector-database adapter."""

    async def ensure_collection(self, config: IndexConfig) -> None:
        """Create a physical collection or verify its immutable vector contract."""

    async def upsert(self, config: IndexConfig, points: Sequence[VectorPoint]) -> None:
        """Insert or replace exact point IDs in one physical collection."""

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
        """Run vector search with tenant/document/ACL constraints inside the query."""


class LexicalIndex(Protocol):
    """Tenant-scoped lexical search over the same immutable chunk versions."""

    async def search(
        self,
        *,
        query: str,
        scope: AccessScope,
        index_version: str,
        limit: int,
    ) -> tuple[SearchHit, ...]: ...


@dataclass(frozen=True, slots=True)
class IndexingResult:
    indexed_points: int
    batches: int
    model: str
    model_version: str | None
    dimension: int


@dataclass(frozen=True, slots=True)
class RetrievalResult:
    hits: tuple[RankedHit, ...]
    dense_candidates: int
    embedding_model: str
    embedding_model_version: str | None
    reranking_model: str | None = None
    reranking_model_version: str | None = None
    retrieval_policy_fingerprint: str | None = None
    lexical_candidates: int = 0
    hybrid: bool = False


class EmbeddingBatchPipeline:
    """Embed passage batches and index them without weakening dimension checks."""

    def __init__(
        self,
        *,
        embedding: EmbeddingClient,
        vector_index: VectorIndex,
        batch_size: int = 16,
    ) -> None:
        if isinstance(batch_size, bool) or not 1 <= batch_size <= 2048:
            raise ValueError("batch_size must be an integer between 1 and 2048")
        self._embedding = embedding
        self._vector_index = vector_index
        self._batch_size = batch_size

    async def index(
        self,
        config: IndexConfig,
        chunks: Sequence[ChunkPayload],
    ) -> IndexingResult:
        if not chunks:
            raise ValueError("chunks must not be empty")
        if len({chunk.chunk_id for chunk in chunks}) != len(chunks):
            raise ValueError("chunks must have unique chunk_id values")
        if any(chunk.index_version != config.index_version for chunk in chunks):
            raise ValueError("every chunk index_version must match the index config")

        await self._vector_index.ensure_collection(config)
        batch_count = 0
        indexed_count = 0
        observed_model: str | None = None
        observed_version: str | None = None

        for offset in range(0, len(chunks), self._batch_size):
            batch = chunks[offset : offset + self._batch_size]
            response = await self._embedding.embed(
                EmbeddingRequest(
                    texts=tuple(chunk.text for chunk in batch),
                    input_type="passage",
                    truncate="NONE",
                )
            )
            if len(response.vectors) != len(batch):
                raise RuntimeError("embedding service returned the wrong number of vectors")
            if response.dimension != config.vector_dimension:
                raise RuntimeError(
                    "embedding response dimension does not match the physical collection"
                )
            if response.model != config.embedding_model:
                raise RuntimeError("embedding response model does not match the index config")
            if (
                response.model_version is not None
                and response.model_version != config.embedding_model_version
            ):
                raise RuntimeError(
                    "embedding response model version does not match the index config"
                )
            if observed_model is not None and response.model != observed_model:
                raise RuntimeError("embedding model changed within one indexing run")
            if observed_version is not None and response.model_version != observed_version:
                raise RuntimeError("embedding model version changed within one indexing run")

            points = tuple(
                VectorPoint(point_id=chunk.chunk_id, vector=vector, payload=chunk)
                for chunk, vector in zip(batch, response.vectors, strict=True)
            )
            await self._vector_index.upsert(config, points)
            observed_model = response.model
            observed_version = response.model_version
            batch_count += 1
            indexed_count += len(points)

        if observed_model is None:
            raise RuntimeError("indexing completed without an embedding response")
        return IndexingResult(
            indexed_points=indexed_count,
            batches=batch_count,
            model=observed_model,
            model_version=observed_version,
            dimension=config.vector_dimension,
        )


class DenseRetriever:
    """Dense retrieval baseline with optional auditable cross-encoder reranking."""

    def __init__(
        self,
        *,
        embedding: EmbeddingClient,
        vector_index: VectorIndex,
        reranking: RerankClient | None = None,
        lexical_index: LexicalIndex | None = None,
        collection_target: str | None = None,
    ) -> None:
        if collection_target is not None and not collection_target.strip():
            raise ValueError("collection_target must be non-blank when provided")
        self._embedding = embedding
        self._vector_index = vector_index
        self._reranking = reranking
        self._lexical_index = lexical_index
        self._collection_target = collection_target

    @staticmethod
    def _rrf_fuse(
        dense_hits: tuple[SearchHit, ...],
        lexical_hits: tuple[SearchHit, ...],
        *,
        k: int,
        dense_weight: float,
        lexical_weight: float,
    ) -> tuple[SearchHit, ...]:
        by_id = {hit.point_id: hit for hit in (*dense_hits, *lexical_hits)}
        scores: dict[object, float] = {}
        for rank, hit in enumerate(dense_hits, start=1):
            scores[hit.point_id] = scores.get(hit.point_id, 0.0) + dense_weight / (k + rank)
        for rank, hit in enumerate(lexical_hits, start=1):
            scores[hit.point_id] = scores.get(hit.point_id, 0.0) + lexical_weight / (k + rank)
        dense_ranks = {hit.point_id: rank for rank, hit in enumerate(dense_hits, start=1)}
        lexical_ranks = {hit.point_id: rank for rank, hit in enumerate(lexical_hits, start=1)}
        ordered_ids = sorted(
            by_id,
            key=lambda point_id: (
                -scores[point_id],
                dense_ranks.get(point_id, 1_000_000),
                lexical_ranks.get(point_id, 1_000_000),
                str(point_id),
            ),
        )
        return tuple(
            SearchHit(
                point_id=point_id,
                score=scores[point_id],
                payload=by_id[point_id].payload,
            )
            for point_id in ordered_ids
        )

    @staticmethod
    def _deduplicate_and_diversify(hits: tuple[SearchHit, ...]) -> tuple[SearchHit, ...]:
        """Deduplicate content and keep up to three chunks per document section."""

        selected: list[SearchHit] = []
        content_hashes: set[str] = set()
        section_counts: dict[tuple[object, tuple[str, ...]], int] = {}
        for hit in hits:
            if hit.payload.content_hash in content_hashes:
                continue
            section_key = (hit.payload.document_id, hit.payload.section_path)
            count = section_counts.get(section_key, 0)
            if count >= 3:
                continue
            content_hashes.add(hit.payload.content_hash)
            section_counts[section_key] = count + 1
            selected.append(hit)
        return tuple(selected)

    async def retrieve(
        self,
        *,
        query: str,
        scope: AccessScope,
        config: IndexConfig,
        candidate_limit: int | None = None,
        final_limit: int | None = None,
        dense_threshold: float | None = None,
        rerank_threshold: float | None = None,
        retrieval_policy: RetrievalPolicy | None = None,
        candidate_limit_cap: int | None = None,
    ) -> RetrievalResult:
        if not query.strip():
            raise ValueError("query must not be blank")
        if candidate_limit_cap is not None and (
            isinstance(candidate_limit_cap, bool) or not 1 <= candidate_limit_cap <= 100
        ):
            raise ValueError("candidate_limit_cap must be an integer between 1 and 100")

        if retrieval_policy is not None:
            if any(
                value is not None
                for value in (
                    candidate_limit,
                    final_limit,
                    dense_threshold,
                    rerank_threshold,
                )
            ):
                raise ValueError(
                    "retrieval_policy cannot be combined with individual retrieval settings"
                )
            if retrieval_policy.index_config_fingerprint != config.fingerprint:
                raise ValueError("retrieval_policy is not bound to the supplied index config")
            resolved_candidate_limit = retrieval_policy.dense_candidate_limit
            resolved_final_limit = retrieval_policy.final_limit
            resolved_dense_threshold = retrieval_policy.dense_threshold
            resolved_rerank_threshold = retrieval_policy.rerank_threshold
            resolved_hnsw_ef: int | None = retrieval_policy.hnsw_ef
            use_reranker = retrieval_policy.reranker_enabled
            use_hybrid = retrieval_policy.hybrid_enabled
            rrf_k = retrieval_policy.rrf_k
            dense_weight = retrieval_policy.dense_weight
            lexical_weight = retrieval_policy.lexical_weight
        else:
            resolved_candidate_limit = 20 if candidate_limit is None else candidate_limit
            resolved_final_limit = 10 if final_limit is None else final_limit
            resolved_dense_threshold = dense_threshold
            resolved_rerank_threshold = rerank_threshold
            resolved_hnsw_ef = None
            use_reranker = self._reranking is not None
            use_hybrid = self._lexical_index is not None
            rrf_k = 60
            dense_weight = 1.0
            lexical_weight = 1.0

        if candidate_limit_cap is not None:
            resolved_candidate_limit = min(resolved_candidate_limit, candidate_limit_cap)
            resolved_final_limit = min(resolved_final_limit, resolved_candidate_limit)

        if isinstance(resolved_candidate_limit, bool) or not 1 <= resolved_candidate_limit <= 100:
            raise ValueError("candidate_limit must be between 1 and 100")
        if (
            isinstance(resolved_final_limit, bool)
            or not 1 <= resolved_final_limit <= resolved_candidate_limit
        ):
            raise ValueError("final_limit must be between 1 and candidate_limit")
        for threshold, field_name in (
            (resolved_dense_threshold, "dense_threshold"),
            (resolved_rerank_threshold, "rerank_threshold"),
        ):
            if threshold is not None and not math.isfinite(threshold):
                raise ValueError(f"{field_name} must be finite when provided")
        if use_reranker and self._reranking is None:
            raise RuntimeError("retrieval policy requires a reranking client")
        if use_hybrid and self._lexical_index is None:
            raise RuntimeError("retrieval policy requires a lexical index")

        lexical_task: asyncio.Task[tuple[SearchHit, ...]] | None = None
        if use_hybrid and self._lexical_index is not None:
            lexical_task = asyncio.create_task(
                self._lexical_index.search(
                    query=query,
                    scope=scope,
                    index_version=config.index_version,
                    limit=resolved_candidate_limit,
                )
            )

        try:
            embedded = await self._embedding.embed(
                EmbeddingRequest(texts=(query,), input_type="query", truncate="NONE")
            )
        except BaseException:
            if lexical_task is not None:
                lexical_task.cancel()
            raise
        if len(embedded.vectors) != 1 or embedded.dimension != config.vector_dimension:
            raise RuntimeError("query embedding is incompatible with the physical collection")
        if embedded.model != config.embedding_model:
            raise RuntimeError("query embedding model does not match the index config")
        if (
            embedded.model_version is not None
            and embedded.model_version != config.embedding_model_version
        ):
            raise RuntimeError("query embedding model version does not match the index config")

        dense_hits = await self._vector_index.search(
            config,
            embedded.vectors[0],
            scope,
            limit=resolved_candidate_limit,
            score_threshold=resolved_dense_threshold,
            collection_target=self._collection_target,
            hnsw_ef=resolved_hnsw_ef,
        )
        if len(dense_hits) > resolved_candidate_limit:
            raise RuntimeError("vector index returned more hits than the requested candidate limit")
        if any(current.score < following.score for current, following in pairwise(dense_hits)):
            raise RuntimeError("vector index returned dense hits outside descending score order")
        if len({hit.point_id for hit in dense_hits}) != len(dense_hits):
            raise RuntimeError("vector index returned duplicate point IDs")
        lexical_hits: tuple[SearchHit, ...] = ()
        if lexical_task is not None:
            try:
                lexical_hits = await lexical_task
            except Exception:
                _log.warning(
                    "Lexical retrieval failed; continuing with dense results", exc_info=True
                )
        if len(lexical_hits) > resolved_candidate_limit:
            raise RuntimeError("lexical index returned more hits than requested")
        if len({hit.point_id for hit in lexical_hits}) != len(lexical_hits):
            raise RuntimeError("lexical index returned duplicate point IDs")

        fused_hits = (
            self._rrf_fuse(
                dense_hits,
                lexical_hits,
                k=rrf_k,
                dense_weight=dense_weight,
                lexical_weight=lexical_weight,
            )
            if use_hybrid
            else dense_hits
        )
        fused_hits = fused_hits[:resolved_candidate_limit]
        original_dense_ranks = {hit.point_id: rank for rank, hit in enumerate(dense_hits, start=1)}
        for lexical_rank, hit in enumerate(lexical_hits, start=1):
            original_dense_ranks.setdefault(
                hit.point_id,
                len(dense_hits) + lexical_rank,
            )
        diverse_hits = self._deduplicate_and_diversify(fused_hits)

        if not use_reranker or not diverse_hits:
            hits = tuple(
                RankedHit(
                    hit=hit,
                    dense_rank=original_dense_ranks[hit.point_id],
                    final_rank=final_rank,
                )
                for final_rank, hit in enumerate(diverse_hits[:resolved_final_limit], start=1)
            )
            return RetrievalResult(
                hits=hits,
                dense_candidates=len(fused_hits) if use_hybrid else len(dense_hits),
                embedding_model=embedded.model,
                embedding_model_version=embedded.model_version,
                retrieval_policy_fingerprint=(
                    None if retrieval_policy is None else retrieval_policy.fingerprint
                ),
                lexical_candidates=len(lexical_hits),
                hybrid=use_hybrid,
            )

        if self._reranking is None:
            raise RuntimeError("reranking client disappeared during retrieval")
        reranked = await self._reranking.rerank(
            RerankRequest(
                query=query,
                passages=tuple(hit.payload.text for hit in diverse_hits),
                truncate="END",
            )
        )
        if len(reranked.rankings) != len(diverse_hits):
            raise RuntimeError("reranker must return every dense candidate exactly once")
        if retrieval_policy is not None:
            if reranked.model != retrieval_policy.reranker_model:
                raise RuntimeError("reranking response model does not match retrieval policy")
            if (
                reranked.model_version is not None
                and reranked.model_version != retrieval_policy.reranker_model_version
            ):
                raise RuntimeError(
                    "reranking response model version does not match retrieval policy"
                )
        source_indices = [ranked.source_index for ranked in reranked.rankings]
        if set(source_indices) != set(range(len(diverse_hits))):
            raise RuntimeError("reranker returned duplicate or invalid source indices")

        selected: list[RankedHit] = []
        for ranked in reranked.rankings:
            if resolved_rerank_threshold is not None and ranked.score < resolved_rerank_threshold:
                continue
            hit = diverse_hits[ranked.source_index]
            selected.append(
                RankedHit(
                    hit=hit,
                    dense_rank=original_dense_ranks[hit.point_id],
                    final_rank=len(selected) + 1,
                    rerank_score=ranked.score,
                )
            )
            if len(selected) == resolved_final_limit:
                break

        return RetrievalResult(
            hits=tuple(selected),
            dense_candidates=len(fused_hits) if use_hybrid else len(dense_hits),
            embedding_model=embedded.model,
            embedding_model_version=embedded.model_version,
            reranking_model=reranked.model,
            reranking_model_version=reranked.model_version,
            retrieval_policy_fingerprint=(
                None if retrieval_policy is None else retrieval_policy.fingerprint
            ),
            lexical_candidates=len(lexical_hits),
            hybrid=use_hybrid,
        )
