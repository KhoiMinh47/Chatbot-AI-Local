import asyncio
import json
from collections.abc import AsyncIterator, Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.application.ai_clients import ChatRequest, ChatStreamChunk, TokenUsage
from app.application.rag import OverloadError
from app.application.retrieval import RetrievalResult
from app.domain.rag import RagEventType, RagMode, RagRequest, sha256_text
from app.domain.retrieval import (
    ChunkPayload,
    IndexConfig,
    RankedHit,
    RetrievalPolicy,
    SearchHit,
)
from app.rag.graph import GroundedRagGraph

pytestmark = pytest.mark.anyio
PERF_CHUNK_ID = UUID("70000000-0000-4000-8000-000000000001")
PERF_CITATION = f"[CITE:C{PERF_CHUNK_ID.hex}]"


class FakeRedis:
    def __init__(self):
        self.store = {}

    async def get(self, key: str) -> bytes | None:
        return self.store.get(key)

    async def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value.encode("utf-8")


class ExactWordCounter:
    @property
    def exact(self) -> bool:
        return True

    @property
    def tokenizer_id(self) -> str:
        return "nvidia/nemotron-nano-9b-v2"

    @property
    def tokenizer_sha256(self) -> str:
        return "a" * 64

    def count_text(self, text: str) -> int:
        return len(text.split())

    def count_messages(self, messages: tuple[object, ...]) -> int:
        return sum(self.count_text(message.content) + 3 for message in messages)  # type: ignore


class FakePlanner:
    async def rewrite_followup(self, **_kwargs: object) -> str:
        return "Thời gian thử việc tiêu chuẩn là bao lâu?"

    async def decompose(self, **kwargs: object) -> tuple[str, ...]:
        return ("subquery one", "subquery two")


class FakeRetriever:
    async def retrieve(self, **kwargs: object) -> RetrievalResult:
        policy = kwargs["retrieval_policy"]
        assert isinstance(policy, RetrievalPolicy)
        scope = kwargs["scope"]
        owner_id = uuid4()
        chunk_id = PERF_CHUNK_ID
        document_id = scope.document_ids[0] if scope.document_ids else uuid4()  # type: ignore[attr-defined]
        version_id = uuid4()

        payload = ChunkPayload(
            tenant_id=scope.tenant_id,  # type: ignore[attr-defined]
            owner_id=owner_id,
            acl_principals=(*scope.acl_principals, f"user:{owner_id}"),  # type: ignore[attr-defined]
            document_id=document_id,
            version_id=version_id,
            chunk_id=chunk_id,
            parent_id=None,
            source_name="fixture.pdf",
            mime_type="application/pdf",
            language="vi",
            section_path=(),
            page=1,
            slide=None,
            text="Test fact",
            token_count=2,
            content_hash="a" * 64,
            index_version="phase6-candidate-test",
            created_at=datetime(2026, 7, 15, tzinfo=UTC),
        )
        hit = RankedHit(
            hit=SearchHit(point_id=chunk_id, score=0.9, payload=payload),
            dense_rank=1,
            final_rank=1,
            rerank_score=0.9,
        )
        return RetrievalResult(
            hits=(hit,),
            dense_candidates=1,
            embedding_model="fixture-embedding",
            embedding_model_version="1",
            retrieval_policy_fingerprint=policy.fingerprint,
        )


class FakeLlm:
    def __init__(self, answers: Sequence[str]) -> None:
        self.answers = list(answers)
        self.calls: list[ChatRequest] = []

    async def chat(self, request: ChatRequest) -> object:
        raise AssertionError(f"non-streaming chat must not be called: {request}")

    async def stream(self, request: ChatRequest) -> AsyncIterator[ChatStreamChunk]:
        self.calls.append(request)
        answer = self.answers.pop(0)
        yield ChatStreamChunk(
            content_delta=answer,
            model="fixture-llm",
            model_version="1",
            elapsed_seconds=0.1,
            finish_reason="stop",
            usage=TokenUsage(input_tokens=40, output_tokens=8, total_tokens=48),
        )

    async def aclose(self) -> None:
        return None


class ExactlyOnceTraceStore:
    def __init__(self) -> None:
        self.traces = []
        self.request_ids = set()

    async def save(self, trace) -> None:
        if trace.request_id in self.request_ids:
            raise RuntimeError("duplicate request trace")
        self.request_ids.add(trace.request_id)
        self.traces.append(trace)


def index_config() -> IndexConfig:
    return IndexConfig(
        collection_name="ntc_phase6_candidate_test",
        index_version="phase6-candidate-test",
        embedding_model="fixture-embedding",
        embedding_model_version="1",
        vector_dimension=2,
        chunk_size=256,
        overlap_percent=10,
    )


def retrieval_policy() -> RetrievalPolicy:
    return RetrievalPolicy(
        index_config_fingerprint=index_config().fingerprint,
        dense_candidate_limit=3,
        final_limit=2,
        dense_threshold=0.1,
        hnsw_ef=16,
        reranker_enabled=False,
    )


def build_perf_graph(
    *,
    answers: Sequence[str] = (f"Mock answer {PERF_CITATION}.",),
    redis=None,
    semaphore=None,
) -> tuple[GroundedRagGraph, FakeLlm]:
    llm = FakeLlm(answers)
    graph = GroundedRagGraph(
        llm=llm,  # type: ignore
        retriever=FakeRetriever(),
        planner=FakePlanner(),
        token_counter=ExactWordCounter(),
        trace_store=ExactlyOnceTraceStore(),
        index_config=index_config(),
        retrieval_policy=retrieval_policy(),
        redis=redis,
        semaphore=semaphore,
    )
    return graph, llm


def fake_request() -> RagRequest:
    uid = uuid4()
    document_id = uuid4()
    return RagRequest(
        request_id=uuid4(),
        user_id=uid,
        tenant_id=uuid4(),
        conversation_id=uuid4(),
        mode=RagMode.FAST,
        question="What is the weather?",
        language="en",
        acl_principals=(f"user:{uid}",),
        selected_document_ids=(document_id,),
    )


async def test_unsafe_query_only_final_answer_cache_is_not_used():
    redis = FakeRedis()
    request = fake_request()

    # Pre-populate cache
    scoped_hash = sha256_text(f"{request.user_id}\n{request.language}\n\n{request.question}")
    cache_key = f"rag_cache:{request.tenant_id}:{request.mode.value}:{scoped_hash}"
    await redis.set(
        cache_key,
        json.dumps(
            {
                "answer": "Cached answer",
                "citations": [
                    {
                        "citation_id": "C0123456789abcdef0123456789abcdef",
                        "chunk_id": str(uuid4()),
                        "document_id": str(uuid4()),
                        "page": 1,
                        "section_path": [],
                        "slide": None,
                        "source_name": "Test Source",
                    }
                ],
            }
        ),
    )

    graph, llm = build_perf_graph(redis=redis)
    events = [event async for event in graph.stream(request)]

    visible = "".join(
        str(event.data["text"]) for event in events if event.event_type is RagEventType.TOKEN
    )
    assert llm.calls
    assert visible == f"Mock answer {PERF_CITATION}."
    assert visible != "Cached answer"
    assert events[-1].event_type is RagEventType.DONE


async def test_semaphore_limits_concurrency():
    # Semaphore of 1
    semaphore = asyncio.Semaphore(1)
    graph, _ = build_perf_graph(semaphore=semaphore)
    request2 = fake_request()

    # Block the semaphore by acquiring it manually
    await semaphore.acquire()

    with pytest.raises(OverloadError, match="quá tải"):
        # This will time out in the stream method after 5s and raise OverloadError
        async for _ in graph.stream(request2):
            pass

    semaphore.release()
