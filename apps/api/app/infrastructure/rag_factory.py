"""Factory that wires up the GroundedRagGraph from live settings and NIM clients."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncEngine

from app.application.retrieval import DenseRetriever
from app.core.settings import ApiSettings
from app.domain.retrieval import IndexConfig, RetrievalPolicy
from app.infrastructure.generation_trace_store import PostgresGenerationTraceStore
from app.infrastructure.nim_client_factory import NimClientBundle
from app.infrastructure.postgres_lexical_index import PostgresLexicalIndex
from app.infrastructure.qdrant_store import QdrantVectorIndex
from app.rag.graph import GroundedRagGraph
from app.rag.planner import LlmQueryPlanner

_log = logging.getLogger(__name__)


def build_rag_graph(
    settings: ApiSettings,
    nim_bundle: NimClientBundle,
    async_engine: AsyncEngine,
    redis: Any | None = None,
    semaphore: asyncio.Semaphore | None = None,
) -> GroundedRagGraph:
    """Build a ready-to-use GroundedRagGraph from live settings and NIM clients."""

    # Validate chunk_size is one of the allowed values
    allowed_chunk_sizes = {256, 512, 768, 1024}
    chunk_size = settings.rag_chunk_size if settings.rag_chunk_size in allowed_chunk_sizes else 256

    # Validate overlap_percent is one of the allowed values
    allowed_overlaps = {0, 10, 20}
    overlap_pct = (
        settings.rag_overlap_percent if settings.rag_overlap_percent in allowed_overlaps else 10
    )

    embed_model = settings.nim_embed_model or "unknown-embed"
    embed_version = settings.nim_embed_model_version or "1.0"
    dimension = settings.embedding_dimension or 768

    index_config = IndexConfig(
        collection_name=settings.rag_collection_name,
        index_version=settings.rag_index_version,
        embedding_model=embed_model,
        embedding_model_version=embed_version,
        vector_dimension=dimension,
        chunk_size=chunk_size,
        overlap_percent=overlap_pct,
        distance="Cosine",
    )

    retrieval_policy = RetrievalPolicy(
        index_config_fingerprint=index_config.fingerprint,
        dense_candidate_limit=settings.rag_dense_candidate_limit,
        final_limit=settings.rag_final_limit,
        dense_threshold=settings.rag_dense_threshold,
        hnsw_ef=settings.rag_hnsw_ef,
        reranker_enabled=settings.rag_reranker_enabled,
        reranker_model=(settings.nim_rerank_model if settings.rag_reranker_enabled else None),
        reranker_model_version=(
            settings.nim_rerank_model_version if settings.rag_reranker_enabled else None
        ),
        rerank_threshold=(settings.rag_rerank_threshold if settings.rag_reranker_enabled else None),
        hybrid_enabled=settings.enable_hybrid_retrieval,
        rrf_k=settings.rag_rrf_k,
        dense_weight=settings.rag_dense_weight,
        lexical_weight=settings.rag_lexical_weight,
    )

    qdrant_index = QdrantVectorIndex(
        base_url=settings.qdrant_base_url,
        timeout_seconds=30,
    )

    retriever = DenseRetriever(
        embedding=nim_bundle.embedding,
        vector_index=qdrant_index,
        reranking=nim_bundle.reranking,
        lexical_index=(
            PostgresLexicalIndex(async_engine) if settings.enable_hybrid_retrieval else None
        ),
    )

    planner = LlmQueryPlanner(llm=nim_bundle.llm)

    # Generation and working memory use the exact active-model tokenizer. A silent
    # approximation makes long Vietnamese prompts and audit traces unreliable.
    try:
        from pathlib import Path

        from app.infrastructure.exact_token_counter import ExactHuggingFaceTokenCounter

        base_dir = Path(__file__).resolve().parent
        tokenizer_path = base_dir / "tokenizer"
        token_counter = ExactHuggingFaceTokenCounter(
            tokenizer_path=tokenizer_path,
            tokenizer_id="nemotron-nano-9b-v2",
            expected_sha256="32bd2509c1acc93dc18bdd0f9a2d9a15e72fd3110f24cfc9ff3fb820f4e20b6b",
        )
        _log.info("Wired ExactHuggingFaceTokenCounter successfully")
    except Exception as exc:
        if settings.require_exact_tokenizer:
            raise RuntimeError("the exact Nemotron tokenizer is required") from exc
        raise RuntimeError(
            "approximate token counting is not supported by the grounded RAG graph"
        ) from exc

    trace_store = PostgresGenerationTraceStore(engine=async_engine)

    _log.info(
        "Building GroundedRagGraph: collection=%s model=%s dim=%d",
        settings.rag_collection_name,
        embed_model,
        dimension,
    )

    return GroundedRagGraph(
        llm=nim_bundle.llm,
        retriever=retriever,
        planner=planner,
        token_counter=token_counter,
        trace_store=trace_store,
        index_config=index_config,
        retrieval_policy=retrieval_policy,
        redis=redis,
        semaphore=semaphore,
        adaptive_reasoning_enabled=settings.enable_adaptive_reasoning,
    )
