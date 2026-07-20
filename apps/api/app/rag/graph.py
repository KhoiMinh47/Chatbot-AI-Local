"""Bounded LangGraph orchestration for the Phase 6 grounded RAG baseline."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import AsyncGenerator, AsyncIterator, Callable, Mapping
from contextlib import contextmanager, suppress
from dataclasses import dataclass, field, replace
from time import perf_counter
from typing import Any, TypedDict
from uuid import UUID

from langgraph.graph import END, START, StateGraph

from app.application.ai_clients import ChatMessage, ChatRequest, LlmClient, TokenUsage
from app.application.rag import (
    GRAPH_VERSION,
    PROMPT_SHA256,
    PROMPT_VERSION,
    CitationValidator,
    GenerationTraceStore,
    PromptRenderer,
    QueryPlanner,
    RagRetriever,
    TokenBudgetService,
    TokenCounter,
    assert_retrieval_scope,
    insufficient_evidence_answer,
    invalid_generation_answer,
    normalize_standalone_citations,
)
from app.application.reasoning_policy import ReasoningPolicy
from app.application.retrieval import RetrievalResult
from app.domain.rag import (
    Citation,
    ContextBlock,
    GenerationTrace,
    ModePolicy,
    RagEvent,
    RagEventType,
    RagMode,
    RagRequest,
    TokenBudget,
    TraceContextRef,
    TraceOutcome,
    policy_for,
    sha256_text,
)
from app.domain.retrieval import AccessScope, IndexConfig, RankedHit, RetrievalPolicy

_log = logging.getLogger(__name__)


class _GraphState(TypedDict, total=False):
    request: RagRequest
    policy: ModePolicy
    retrieval_policy: RetrievalPolicy
    emitter: _EventEmitter
    recorder: _RunRecorder
    is_followup: bool
    rewritten_query: str
    subqueries: tuple[str, ...]
    retrieval_results: tuple[RetrievalResult, ...]
    ranked_hits: tuple[RankedHit, ...]
    dense_candidates: int
    retrieval_rounds: int
    context_blocks: tuple[ContextBlock, ...]
    generation_messages: tuple[ChatMessage, ...]
    token_budget: TokenBudget
    answer: str
    citations: tuple[Citation, ...]
    outcome: TraceOutcome
    error_codes: tuple[str, ...]
    model: str | None
    model_version: str | None
    usage: TokenUsage | None
    input_tokens: int
    output_tokens: int
    intent: str
    summary_request: bool
    is_citation_valid: bool
    retry_count: int
    tokens_emitted: bool
    safe_stream_prefix: str
    reasoning_complexity: str
    thinking_budget_tokens: int


_FOLLOWUP = re.compile(
    r"\b(?:nó|đó|này|trên|trước|vậy|họ|chúng|it|that|this|they|them|above|previous)\b",
    re.IGNORECASE,
)

_DOCUMENT_REFERENCE = re.compile(
    r"\b(?:file|tệp|tài liệu|document|nguồn|source|mse(?:\.docx)?|"
    r"[\w.-]+\.(?:pdf|docx|doc|pptx|xlsx|csv|txt|md|json|yaml|yml|py|js|ts))\b",
    re.IGNORECASE,
)
_SUMMARY_REQUEST = re.compile(
    r"\b(?:tóm tắt|tom tat|tổng quan|overview|summari[sz]e|toàn bộ|nội dung chính)\b",
    re.IGNORECASE,
)


@dataclass(slots=True)
class _RunRecorder:
    clock: Callable[[], float]
    node_path: list[str] = field(default_factory=list)
    timings_ms: dict[str, float] = field(default_factory=dict)
    persisted: bool = False

    @contextmanager
    def node(self, name: str) -> Any:
        self.node_path.append(name)
        started = self.clock()
        try:
            yield
        finally:
            elapsed = max(0.0, (self.clock() - started) * 1000)
            self.timings_ms[name] = self.timings_ms.get(name, 0.0) + elapsed


@dataclass(slots=True)
class _EventEmitter:
    request_id: Any
    queue: asyncio.Queue[RagEvent | None]
    sequence: int = 0

    def emit(self, event_type: RagEventType, data: Mapping[str, Any]) -> None:
        self.sequence += 1
        self.queue.put_nowait(
            RagEvent(
                event_type=event_type,
                request_id=self.request_id,
                sequence=self.sequence,
                data=data,
            )
        )


class GroundedRagGraph:
    """One reusable compiled graph with per-invocation state and no global counters."""

    _GENERATION_DEADLINE_SECONDS = 90.0

    def __init__(
        self,
        *,
        llm: LlmClient,
        retriever: RagRetriever,
        planner: QueryPlanner,
        token_counter: TokenCounter,
        trace_store: GenerationTraceStore,
        index_config: IndexConfig,
        retrieval_policy: RetrievalPolicy,
        clock: Callable[[], float] = perf_counter,
        redis: Any | None = None,
        semaphore: asyncio.Semaphore | None = None,
        adaptive_reasoning_enabled: bool = True,
    ) -> None:
        if retrieval_policy.index_config_fingerprint != index_config.fingerprint:
            raise ValueError("retrieval_policy is not bound to the supplied index_config")
        self._llm = llm
        self._retriever = retriever
        self._planner = planner
        self._trace_store = trace_store
        self._index_config = index_config
        self._retrieval_policy = retrieval_policy
        self._clock = clock
        self._redis = redis
        self._semaphore = semaphore
        self._adaptive_reasoning_enabled = adaptive_reasoning_enabled
        self._token_counter = token_counter
        self._renderer = PromptRenderer()
        self._budget_service = TokenBudgetService(
            counter=token_counter,
            renderer=self._renderer,
        )
        self._citation_validator = CitationValidator()
        self.compiled = self._compile()

    @property
    def token_counter(self) -> TokenCounter:
        """Expose the exact counter for server-owned conversation memory packing."""

        return self._token_counter

    def _compile(self) -> Any:
        builder = StateGraph(_GraphState)
        builder.add_node("validate_request", self._validate_request)
        builder.add_node("load_conversation_memory", self._load_conversation_memory)
        builder.add_node("classify_query", self._classify_query)
        builder.add_node("rewrite_followup", self._rewrite_followup)
        builder.add_node("build_retrieval_plan", self._build_retrieval_plan)
        builder.add_node("retrieve", self._retrieve)
        builder.add_node("rerank", self._rerank)
        builder.add_node("assemble_context", self._assemble_context)
        builder.add_node("generate", self._generate)
        builder.add_node("insufficient_evidence", self._insufficient_evidence)
        builder.add_node("validate_citations", self._validate_citations)
        builder.add_node("persist_message_and_trace", self._persist_message_and_trace)
        builder.add_node("emit_done", self._emit_done)

        builder.add_edge(START, "validate_request")
        builder.add_edge("validate_request", "load_conversation_memory")
        builder.add_edge("load_conversation_memory", "classify_query")
        builder.add_edge("classify_query", "rewrite_followup")
        builder.add_edge("rewrite_followup", "build_retrieval_plan")
        builder.add_edge("build_retrieval_plan", "retrieve")
        builder.add_edge("retrieve", "rerank")
        builder.add_edge("rerank", "assemble_context")
        builder.add_conditional_edges(
            "assemble_context",
            self._evidence_route,
            {"generate": "generate", "insufficient": "insufficient_evidence"},
        )
        builder.add_edge("generate", "validate_citations")
        builder.add_edge("insufficient_evidence", "validate_citations")
        builder.add_conditional_edges(
            "validate_citations",
            self._citation_route,
            {"generate": "generate", "persist": "persist_message_and_trace"},
        )
        builder.add_edge("persist_message_and_trace", "emit_done")
        builder.add_edge("emit_done", END)
        return builder.compile()

    async def stream(self, request: RagRequest) -> AsyncIterator[RagEvent]:
        """Yield only whitelisted events; raw graph state and raw LLM deltas stay private."""

        # Final-answer caching is deliberately disabled. A safe key must include
        # conversation summary, exact turns, semantic memory, active document
        # versions, prompt/retrieval versions, and response policy. The former
        # query-only key returned stale answers across different conversation state.

        if self._semaphore is not None:
            try:
                async with asyncio.timeout(5.0):
                    await self._semaphore.acquire()
            except TimeoutError:
                from app.application.rag import OverloadError

                raise OverloadError("Hệ thống đang quá tải, vui lòng thử lại sau.") from None

        from contextlib import aclosing

        try:
            async with aclosing(self._stream_internal(request)) as stream_iter:
                async for event in stream_iter:
                    yield event
        finally:
            if self._semaphore is not None:
                self._semaphore.release()

    async def _stream_internal(self, request: RagRequest) -> AsyncGenerator[RagEvent]:
        queue: asyncio.Queue[RagEvent | None] = asyncio.Queue()
        emitter = _EventEmitter(request_id=request.request_id, queue=queue)
        recorder = _RunRecorder(clock=self._clock)
        reasoning = ReasoningPolicy().select(request)
        if not self._adaptive_reasoning_enabled:
            reasoning = replace(reasoning, policy=policy_for(request.mode))
        initial: _GraphState = {
            "request": request,
            "policy": reasoning.policy,
            "reasoning_complexity": reasoning.complexity,
            "thinking_budget_tokens": reasoning.thinking_budget_tokens,
            # An explicitly attached document is already a strong user scope.
            # Do not discard it merely because a short/generic or cross-language
            # question falls below the corpus-wide semantic score threshold.
            "retrieval_policy": (
                replace(self._retrieval_policy, dense_threshold=None)
                if request.selected_document_ids
                else self._retrieval_policy
            ),
            "emitter": emitter,
            "recorder": recorder,
        }
        task = asyncio.create_task(self.compiled.ainvoke(initial))
        task.add_done_callback(lambda _: queue.put_nowait(None))
        try:
            while True:
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=180.0)
                except TimeoutError as exc:
                    task.cancel()
                    raise TimeoutError(
                        "RAG graph exceeded the 180-second request deadline"
                    ) from exc
                if event is None:
                    break
                yield event
            await task
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            import logging as _logging

            _logging.getLogger(__name__).exception("RAG graph execution failed")
            error_code = (
                "generation_timeout" if isinstance(exc, TimeoutError) else "rag_execution_failed"
            )
            error_message = (
                "Reasoning took too long and was stopped safely. Please try again."
                if error_code == "generation_timeout"
                else "The grounded answer could not be completed safely."
            )
            await self._persist_terminal_error(
                request=request,
                recorder=recorder,
                outcome=TraceOutcome.ERROR,
                error_code=error_code,
            )
            emitter.emit(
                RagEventType.ERROR,
                {
                    "code": error_code,
                    "message": error_message,
                },
            )
            while not queue.empty():
                pending = queue.get_nowait()
                if pending is not None:
                    yield pending
        finally:
            if not task.done():
                task.cancel()
                with suppress(asyncio.CancelledError, Exception):
                    await task
                await self._persist_terminal_error(
                    request=request,
                    recorder=recorder,
                    outcome=TraceOutcome.CANCELLED,
                    error_code="cancelled",
                )

    async def _validate_request(self, state: _GraphState) -> dict[str, Any]:
        request = state["request"]
        policy = state["policy"]
        recorder = state["recorder"]
        with recorder.node("validate_request"):
            if policy.mode is not request.mode:
                raise ValueError("request mode and policy differ")
            state["emitter"].emit(
                RagEventType.STATUS,
                {"phase": "validated", "mode": request.mode.value},
            )
            return {"error_codes": ()}

    async def _load_conversation_memory(self, state: _GraphState) -> dict[str, Any]:
        with state["recorder"].node("load_conversation_memory"):
            # Memory is loaded server-side at the endpoint level and injected into
            # RagRequest.recent_messages. The graph never accepts memory from HTTP.
            request = state["request"]
            turn_count = len(request.recent_messages)
            if turn_count > 0:
                state["emitter"].emit(
                    RagEventType.STATUS,
                    {"phase": "memory_loaded", "mode": f"{turn_count}_turns"},
                )
            return {}

    async def _classify_query(self, state: _GraphState) -> dict[str, Any]:
        request = state["request"]
        with state["recorder"].node("classify_query"):
            is_followup = bool(request.recent_messages) and bool(_FOLLOWUP.search(request.question))

            # Active documents are restored into this trusted field. A prompt-only
            # request normally skips retrieval, but an explicit file/document reference
            # (for example "còn file mse thì sao") is a corpus-wide RAG request.
            references_document = bool(_DOCUMENT_REFERENCE.search(request.question))
            summary_request = bool(_SUMMARY_REQUEST.search(request.question))
            intent = (
                "rag" if request.selected_document_ids or references_document else "general_chat"
            )
            state["emitter"].emit(
                RagEventType.STATUS,
                {"phase": "query_classified", "mode": intent},
            )
            return {
                "is_followup": is_followup,
                "intent": intent,
                "summary_request": summary_request,
            }

    async def _rewrite_followup(self, state: _GraphState) -> dict[str, Any]:
        request = state["request"]
        with state["recorder"].node("rewrite_followup"):
            rewritten = request.question.strip()
            if state["is_followup"]:
                rewritten = (
                    await self._planner.rewrite_followup(
                        question=request.question,
                        recent_messages=request.recent_messages,
                        language=request.language,
                    )
                ).strip()
                if not rewritten or len(rewritten) > 8_000:
                    raise ValueError("follow-up rewriter returned an invalid query")
            return {"rewritten_query": rewritten}

    async def _build_retrieval_plan(self, state: _GraphState) -> dict[str, Any]:
        policy = state["policy"]
        query = state["rewritten_query"]
        request = state["request"]
        with state["recorder"].node("build_retrieval_plan"):
            if state.get("intent") == "general_chat":
                return {"subqueries": (query,)}
            if request.mode is RagMode.REASONING and len(request.selected_document_ids) > 1:
                per_document_query = (
                    f"{query}. Phân tích riêng tài liệu này: mục đích, cấu trúc, "
                    "nội dung chính, đặc điểm và kết luận."
                    if request.language == "vi"
                    else (
                        f"{query}. Analyze this document independently: purpose, structure, "
                        "main content, characteristics, and conclusions."
                    )
                )
                return {
                    "subqueries": tuple(
                        per_document_query
                        for _document_id in request.selected_document_ids[: policy.max_subqueries]
                    )
                }
            if state.get("summary_request"):
                return {
                    "subqueries": tuple(
                        dict.fromkeys(
                            (
                                query,
                                f"{query} mục lục phần chương chủ đề chính",
                                f"{query} kết luận kết quả thông tin quan trọng",
                            )
                        )
                    )[: policy.max_subqueries]
                }
            if request.mode is RagMode.FAST:
                return {"subqueries": (query,)}
            proposed = await self._planner.decompose(
                query=query,
                language=request.language,
                max_subqueries=policy.max_subqueries,
            )
            cleaned = tuple(
                dict.fromkeys((query, *(value.strip() for value in proposed if value.strip())))
            )[: policy.max_subqueries]
            return {"subqueries": cleaned}

    async def _retrieve(self, state: _GraphState) -> dict[str, Any]:
        request = state["request"]
        policy = state["policy"]
        retrieval_policy = state["retrieval_policy"]
        with state["recorder"].node("retrieve"):
            if state.get("intent") == "general_chat":
                return {
                    "retrieval_results": (),
                    "dense_candidates": 0,
                    "retrieval_rounds": 0,
                }
            state["emitter"].emit(
                RagEventType.STATUS,
                {"phase": "searching", "mode": f"{len(state['subqueries'])}_subqueries"},
            )
            results: list[RetrievalResult] = []
            multi_document = (
                request.mode is RagMode.REASONING and len(request.selected_document_ids) > 1
            )
            document_ids: tuple[UUID | None, ...] = (
                tuple(request.selected_document_ids[: policy.max_subqueries])
                if multi_document
                else (None,) * len(state["subqueries"][: policy.max_subqueries])
            )
            for query, document_id in zip(
                state["subqueries"][: policy.max_subqueries],
                document_ids,
                strict=True,
            ):
                retrieval_scope = (
                    AccessScope(
                        tenant_id=request.tenant_id,
                        acl_principals=request.acl_principals,
                        document_ids=(document_id,),
                    )
                    if document_id is not None
                    else request.access_scope
                )
                result = await self._retriever.retrieve(
                    query=query,
                    scope=retrieval_scope,
                    config=self._index_config,
                    retrieval_policy=retrieval_policy,
                    candidate_limit_cap=policy.candidate_limit_per_query,
                )
                if result.retrieval_policy_fingerprint != retrieval_policy.fingerprint:
                    raise RuntimeError(
                        "retriever result is not bound to the selected retrieval policy"
                    )
                if (
                    isinstance(result.dense_candidates, bool)
                    or not 0 <= result.dense_candidates <= policy.candidate_limit_per_query
                    or len(result.hits) > policy.candidate_limit_per_query
                    or len(result.hits) > result.dense_candidates
                ):
                    raise RuntimeError("retriever result exceeds the selected mode candidate cap")
                results.append(result)
            result_tuple = tuple(results)
            # An explicit filename in the question is a document scope. This
            # prevents a previous conversation attachment from winning merely
            # because it has a higher dense score.
            filename_text = " ".join(
                [
                    request.question,
                    *(turn.content for turn in request.recent_messages if turn.role == "user"),
                ]
            )
            filename_matches = list(
                re.finditer(
                    r"([\w .-]+\.(?:pdf|docx|doc|pptx|xlsx|csv|txt|md|json|yaml|yml))",
                    filename_text,
                    re.IGNORECASE,
                )
            )
            if not filename_matches:
                stem_match = re.search(r"\b(syllabus[ _-]*ppr501)\b", filename_text, re.IGNORECASE)
                if stem_match:
                    filename_matches = [stem_match]
            if filename_matches:
                requested_name = filename_matches[-1].group(1).strip().casefold()
                scoped = tuple(
                    RetrievalResult(
                        hits=tuple(
                            hit
                            for hit in result.hits
                            if (
                                hit.hit.payload.source_name.casefold() == requested_name
                                or requested_name.replace(" ", "_")
                                in hit.hit.payload.source_name.casefold().replace(" ", "_")
                            )
                        ),
                        dense_candidates=result.dense_candidates,
                        embedding_model=result.embedding_model,
                        embedding_model_version=result.embedding_model_version,
                        reranking_model=result.reranking_model,
                        reranking_model_version=result.reranking_model_version,
                        retrieval_policy_fingerprint=result.retrieval_policy_fingerprint,
                        lexical_candidates=result.lexical_candidates,
                        hybrid=result.hybrid,
                    )
                    for result in result_tuple
                )
                if any(result.hits for result in scoped):
                    result_tuple = scoped
            assert_retrieval_scope(request=request, results=result_tuple)
            dense_candidates = sum(result.dense_candidates for result in result_tuple)
            if dense_candidates > policy.max_dense_candidates:
                raise RuntimeError("aggregate retrieval candidates exceed the selected mode cap")
            return {
                "retrieval_results": result_tuple,
                "dense_candidates": dense_candidates,
                "retrieval_rounds": 1 if result_tuple else 0,
            }

    async def _rerank(self, state: _GraphState) -> dict[str, Any]:
        policy = state["policy"]
        retrieval_policy = state["retrieval_policy"]
        with state["recorder"].node("rerank"):
            if state.get("intent") == "general_chat":
                return {"ranked_hits": ()}
            all_hits = [hit for result in state["retrieval_results"] for hit in result.hits]
            all_hits.sort(
                key=lambda ranked: (
                    -(ranked.rerank_score if ranked.rerank_score is not None else ranked.hit.score),
                    str(ranked.hit.point_id),
                )
            )
            selected: list[RankedHit] = []
            seen: set[Any] = set()
            for ranked in all_hits:
                if (
                    not retrieval_policy.hybrid_enabled
                    and retrieval_policy.dense_threshold is not None
                    and ranked.hit.score < retrieval_policy.dense_threshold
                ):
                    continue
                if (
                    retrieval_policy.rerank_threshold is not None
                    and ranked.rerank_score is not None
                    and ranked.rerank_score < retrieval_policy.rerank_threshold
                ):
                    continue
                if ranked.hit.point_id in seen:
                    continue
                seen.add(ranked.hit.point_id)
                selected.append(
                    RankedHit(
                        hit=ranked.hit,
                        dense_rank=ranked.dense_rank,
                        final_rank=len(selected) + 1,
                        rerank_score=ranked.rerank_score,
                    )
                )
                if len(selected) >= policy.rerank_limit:
                    break
            return {"ranked_hits": tuple(selected)}

    async def _assemble_context(self, state: _GraphState) -> dict[str, Any]:
        request = state["request"]
        with state["recorder"].node("assemble_context"):
            packed = self._budget_service.pack(
                request=request,
                policy=state["policy"],
                hits=state["ranked_hits"],
            )
            state["emitter"].emit(
                RagEventType.RETRIEVAL_SUMMARY,
                {
                    "query_count": len(state["subqueries"]),
                    "candidate_count": state["dense_candidates"],
                    "context_count": len(packed.blocks),
                },
            )
            return {
                "generation_messages": packed.messages,
                "context_blocks": packed.blocks,
                "token_budget": packed.budget,
                "input_tokens": packed.budget.prompt_tokens,
            }

    @staticmethod
    def _evidence_route(state: _GraphState) -> str:
        if state.get("intent") == "general_chat":
            return "generate"
        return "generate" if state["context_blocks"] else "insufficient"

    @staticmethod
    def _citation_route(state: _GraphState) -> str:
        if not state.get("is_citation_valid", True) and state.get("retry_count", 0) <= 1:
            return "generate"
        return "persist"

    async def _generate(self, state: _GraphState) -> dict[str, Any]:
        policy = state["policy"]
        with state["recorder"].node("generate"):
            _log.info(
                "Nemotron generation policy mode=%s complexity=%s "
                "thinking_budget_tokens=%d max_output_tokens=%d",
                policy.mode.value,
                state["reasoning_complexity"],
                state["thinking_budget_tokens"],
                policy.max_output_tokens,
            )
            state["emitter"].emit(
                RagEventType.STATUS,
                {"phase": "generating", "mode": policy.mode.value},
            )
            pieces: list[str] = []
            safe_prefix = ""
            emitted_length = 0
            defer_streaming = len(state["request"].selected_document_ids) > 1
            model: str | None = None
            model_version: str | None = None
            usage: TokenUsage | None = None
            messages = state["generation_messages"]
            expected_signal = policy.reasoning_control.system_signal
            if (
                not messages
                or messages[0].role != "system"
                or not messages[0].content.startswith(f"{expected_signal}\n\n")
            ):
                raise ValueError("generation prompt is missing its trusted reasoning control")
            request = ChatRequest(
                messages=messages,
                max_tokens=policy.max_output_tokens,
                temperature=policy.temperature,
                top_p=policy.top_p,
            )
            try:
                async with asyncio.timeout(self._GENERATION_DEADLINE_SECONDS):
                    async for chunk in self._llm.stream(request):
                        if chunk.content_delta:
                            pieces.append(chunk.content_delta)
                            candidate = "".join(pieces)
                            # A claim is released only after a complete, allow-listed
                            # citation marker arrives. Text before an unverified marker
                            # remains buffered and never reaches the browser.
                            for marker in re.finditer(r"\[CITE:C[0-9a-f]{32}\]", candidate):
                                end = marker.end()
                                terminal_punctuation = ".!?\u3002\uff01\uff1f"
                                while (
                                    end < len(candidate)
                                    and candidate[end] in terminal_punctuation
                                ):
                                    end += 1
                                prefix = candidate[:end]
                                validation = self._citation_validator.validate(
                                    answer=prefix,
                                    blocks=state.get("context_blocks", ()),
                                    require_citations=True,
                                )
                                if validation.valid and len(prefix) > len(safe_prefix):
                                    safe_prefix = prefix
                            if not defer_streaming and len(safe_prefix) > emitted_length:
                                state["emitter"].emit(
                                    RagEventType.TOKEN,
                                    {"text": safe_prefix[emitted_length:]},
                                )
                                emitted_length = len(safe_prefix)
                        model = chunk.model
                        model_version = chunk.model_version
                        if chunk.usage is not None:
                            usage = chunk.usage
            except TimeoutError as exc:
                raise TimeoutError(
                    "Reasoning generation exceeded the 90-second deadline."
                ) from exc

            answer = "".join(pieces).strip()
            output_tokens = self._token_counter.count_text(answer) if answer else 0
            if output_tokens > policy.max_output_tokens:
                answer = ""
            return {
                "answer": answer,
                "model": model,
                "model_version": model_version,
                "usage": usage,
                "output_tokens": output_tokens,
                "outcome": TraceOutcome.ANSWERED,
                # Buffer until the common output validator has removed hidden
                # reasoning and invalid citation markers. True safe streaming needs
                # an incremental validator and remains a separately measured item.
                "tokens_emitted": bool(safe_prefix) and not defer_streaming,
                "safe_stream_prefix": safe_prefix if not defer_streaming else "",
            }

    async def _insufficient_evidence(self, state: _GraphState) -> dict[str, Any]:
        with state["recorder"].node("insufficient_evidence"):
            answer = insufficient_evidence_answer(state["request"].language)
            return {
                "answer": answer,
                "citations": (),
                "model": None,
                "model_version": None,
                "usage": None,
                "output_tokens": self._token_counter.count_text(answer),
                "outcome": TraceOutcome.INSUFFICIENT_EVIDENCE,
            }

    async def _validate_citations(self, state: _GraphState) -> dict[str, Any]:
        with state["recorder"].node("validate_citations"):
            state["emitter"].emit(
                RagEventType.STATUS,
                {"phase": "validating", "mode": ""},
            )
            require_citations = (
                state["outcome"] is TraceOutcome.ANSWERED and state.get("intent") != "general_chat"
            )
            answer_for_validation = normalize_standalone_citations(state["answer"])
            if answer_for_validation != state["answer"]:
                state["answer"] = answer_for_validation
            validation = self._citation_validator.validate(
                answer=answer_for_validation,
                blocks=state["context_blocks"],
                require_citations=require_citations,
            )
            requires_separate_sections = self._requires_separate_document_sections(state)
            has_separate_sections = self._has_separate_document_sections(
                answer_for_validation,
                state["context_blocks"],
            )
            answer = state["answer"]
            outcome = state["outcome"]
            citations = validation.citations
            errors = state.get("error_codes", ())
            retry_count = state.get("retry_count", 0)

            if not validation.valid or (requires_separate_sections and not has_separate_sections):
                errors = tuple(dict.fromkeys((*errors, *validation.error_codes)))
                if requires_separate_sections and not has_separate_sections:
                    errors = tuple(dict.fromkeys((*errors, "mixed_document_structure")))
                safe_prefix = state.get("safe_stream_prefix", "")
                if safe_prefix:
                    # The browser may already have received only this verified
                    # prefix. Persist exactly that prefix and discard the unsafe
                    # tail instead of retrying and producing duplicate output.
                    prefix_validation = self._citation_validator.validate(
                        answer=safe_prefix,
                        blocks=state["context_blocks"],
                        require_citations=True,
                    )
                    if prefix_validation.valid:
                        answer = safe_prefix
                        citations = prefix_validation.citations
                        outcome = TraceOutcome.ANSWERED
                        errors = ()
                        validation = prefix_validation
                        state["answer"] = answer
                        state["outcome"] = outcome
                        state["error_codes"] = errors
                        return {
                            "answer": answer,
                            "citations": citations,
                            "outcome": outcome,
                            "error_codes": errors,
                            "is_citation_valid": True,
                            "tokens_emitted": True,
                        }
                if retry_count < 1:
                    if state.get("intent") == "general_chat":
                        feedback = (
                            "Rewrite the answer without any citation or source marker. "
                            "Do not claim that a document was provided. Return only the answer."
                        )
                        if state["request"].language == "vi":
                            feedback = (
                                "Hãy viết lại câu trả lời và xóa toàn bộ citation hoặc marker "
                                "nguồn. Không được nói rằng có tài liệu đính kèm. Chỉ trả về "
                                "câu trả lời đã sửa."
                            )
                    elif (
                        "mixed_document_structure" in errors
                        and state["request"].language == "vi"
                    ):
                        feedback = (
                            "Câu trả lời đang trộn hoặc thiếu mục riêng cho từng file. Hãy viết "
                            "lại với đúng một tiêu đề `## <source_name>` cho mỗi file; trong mỗi "
                            "mục chỉ dùng dữ liệu và citation của file đó. Phải xử lý đủ từng file "
                            "trước khi so sánh. Mỗi đoạn có thông tin thực tế phải có marker "
                            "[CITE:<source-id>] hợp lệ. Chỉ trả về câu trả lời đã sửa."
                        )
                    elif "mixed_document_structure" in errors:
                        feedback = (
                            "The answer mixes files or lacks a separate section for each one. "
                            "Rewrite it with exactly one `## <source_name>` heading per file. "
                            "Use only that file's records and citations inside its section, cover "
                            "every file before comparing them, and cite every factual paragraph. "
                            "Return only the repaired answer."
                        )
                    elif state["request"].language == "vi":
                        feedback = (
                            "Câu trả lời có claim thiếu hoặc sai citation. Hãy viết lại chỉ "
                            "bằng các source record đã cung cấp; sao chép nguyên marker "
                            "[CITE:<source-id>] ở cuối từng câu có fact được hỗ trợ. Không "
                            "thêm fact hay marker mới; trả lời đầy đủ các ý của câu hỏi. Chỉ "
                            "trả về câu trả lời đã sửa."
                        )
                    else:
                        feedback = (
                            "Error: The generated response contains invalid or missing citations. "
                            "Rewrite it using only the supplied source records. Attach only "
                            "valid markers copied exactly from the source IDs at the end of every "
                            "factual sentence. Do not invent markers or add facts. Cover every "
                            "part of the question with enough detail. Return only the repaired "
                            "answer."
                        )
                    current_messages = list(state["generation_messages"])
                    current_messages.append(ChatMessage(role="assistant", content=state["answer"]))
                    current_messages.append(ChatMessage(role="user", content=feedback))

                    return {
                        "is_citation_valid": False,
                        "retry_count": retry_count + 1,
                        "generation_messages": tuple(current_messages),
                        "error_codes": errors,
                    }
                # Never discard useful retrieved evidence just because the model
                # emitted an invalid/fabricated citation. Return a deterministic,
                # fully cited extractive answer as a safe fallback.
                blocks = state.get("context_blocks", ())
                if (
                    blocks
                    and state.get("intent") != "general_chat"
                    and (
                        {"uncited_claim", "missing_citation", "mixed_document_structure"}
                        & set(errors)
                    )
                    and "hidden_reasoning" not in errors
                ):
                    available = tuple(
                        block
                        for block in blocks
                        if block.text.strip()
                    )
                    if requires_separate_sections:
                        blocks_by_document: dict[UUID, list[ContextBlock]] = {}
                        for block in available:
                            blocks_by_document.setdefault(block.document_id, []).append(block)
                        per_document_limit = max(
                            1,
                            6 // len(state["request"].selected_document_ids),
                        )
                        selected = tuple(
                            block
                            for document_id in state["request"].selected_document_ids
                            for block in blocks_by_document.get(document_id, ())[
                                :per_document_limit
                            ]
                        )[:6]
                        grouped: dict[str, list[ContextBlock]] = {}
                        for block in selected:
                            grouped.setdefault(block.source_name, []).append(block)
                        answer = "\n\n".join(
                            "\n\n".join(
                                (
                                    f"## {source_name}",
                                    *(
                                        f"{block.text.strip()} [CITE:{block.citation_id}]"
                                        for block in source_blocks
                                    ),
                                )
                            )
                            for source_name, source_blocks in grouped.items()
                        )
                    else:
                        selected = available[:6]
                        answer = "\n\n".join(
                            f"{block.text.strip()} [CITE:{block.citation_id}]"
                            for block in selected
                        )
                    citations = tuple(Citation.from_block(block) for block in selected)
                    outcome = TraceOutcome.ANSWERED
                else:
                    answer = invalid_generation_answer(state["request"].language)
                    outcome = TraceOutcome.INVALID_GENERATION
                    citations = ()

            blocks_by_citation = {block.citation_id: block for block in state["context_blocks"]}
            if not state.get("tokens_emitted", False):
                for piece in self._visible_chunks(answer):
                    state["emitter"].emit(RagEventType.TOKEN, {"text": piece})
            for citation in citations:
                state["emitter"].emit(
                    RagEventType.CITATION,
                    {
                        "citation_id": citation.citation_id,
                        "document_id": str(citation.document_id),
                        "version_id": str(citation.version_id),
                        "chunk_id": str(citation.chunk_id),
                        "source_name": citation.source_name,
                        "page": citation.page,
                        "slide": citation.slide,
                        "section_path": list(citation.section_path),
                        "sheet": citation.sheet,
                        "cell_range": citation.cell_range,
                        "line_start": citation.line_start,
                        "line_end": citation.line_end,
                        "excerpt": blocks_by_citation[citation.citation_id].text[:1_000],
                        "score": citation.score,
                        "verified": citation.verified,
                    },
                )

            actual_usage = state.get("usage")
            input_tokens = (
                actual_usage.input_tokens if actual_usage is not None else state["input_tokens"]
            )
            output_tokens = (
                actual_usage.output_tokens
                if actual_usage is not None and outcome is TraceOutcome.ANSWERED
                else self._token_counter.count_text(answer)
            )
            state["emitter"].emit(
                RagEventType.USAGE,
                {
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                    "total_tokens": input_tokens + output_tokens,
                },
            )
            return {
                "is_citation_valid": True,
                "answer": answer,
                "citations": citations,
                "outcome": outcome,
                "error_codes": errors,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
            }

    @staticmethod
    def _requires_separate_document_sections(state: _GraphState) -> bool:
        request = state["request"]
        source_names = {block.source_name for block in state.get("context_blocks", ())}
        return (
            request.mode is RagMode.REASONING
            and len(request.selected_document_ids) > 1
            and len(source_names) > 1
        )

    @staticmethod
    def _has_separate_document_sections(
        answer: str,
        blocks: tuple[ContextBlock, ...],
    ) -> bool:
        source_names = tuple(dict.fromkeys(block.source_name for block in blocks))
        if len(source_names) <= 1:
            return True
        headings = tuple(
            line.casefold()
            for line in answer.splitlines()
            if re.match(r"^\s*#{1,6}\s+\S", line)
        )
        return all(
            any(source_name.casefold() in heading for heading in headings)
            for source_name in source_names
        )

    async def _persist_message_and_trace(self, state: _GraphState) -> dict[str, Any]:
        recorder = state["recorder"]
        with recorder.node("persist_message_and_trace"):
            trace = self._trace_from_state(state)
            await self._trace_store.save(trace)
            recorder.persisted = True
            return {}

    async def _emit_done(self, state: _GraphState) -> dict[str, Any]:
        with state["recorder"].node("emit_done"):
            state["emitter"].emit(
                RagEventType.DONE,
                {"outcome": state["outcome"].value},
            )
            return {}

    def _trace_from_state(self, state: _GraphState) -> GenerationTrace:
        request = state["request"]
        blocks = state["context_blocks"]
        return GenerationTrace(
            request_id=request.request_id,
            user_id=request.user_id,
            tenant_id=request.tenant_id,
            conversation_id=request.conversation_id,
            mode=request.mode,
            outcome=state["outcome"],
            prompt_version=PROMPT_VERSION,
            prompt_sha256=PROMPT_SHA256,
            graph_version=GRAPH_VERSION,
            question_sha256=sha256_text(request.question),
            answer_sha256=sha256_text(state["answer"]),
            model=state.get("model"),
            model_version=state.get("model_version"),
            index_fingerprint=self._index_config.fingerprint,
            retrieval_policy_fingerprint=state["retrieval_policy"].fingerprint,
            rewritten_query_sha256=sha256_text(state["rewritten_query"]),
            subquery_count=len(state["subqueries"]),
            retrieval_rounds=state["retrieval_rounds"],
            context_refs=tuple(
                TraceContextRef(
                    citation_id=block.citation_id,
                    document_id=block.document_id,
                    chunk_id=block.chunk_id,
                    dense_rank=block.dense_rank,
                    final_rank=block.final_rank,
                    score=block.score,
                    content_hash=block.content_hash,
                )
                for block in blocks
            ),
            citations=state["citations"],
            token_budget=state["token_budget"],
            input_tokens=state["input_tokens"],
            output_tokens=state["output_tokens"],
            node_path=tuple(state["recorder"].node_path),
            timings_ms=dict(state["recorder"].timings_ms),
            error_codes=state["error_codes"],
        )

    async def _persist_terminal_error(
        self,
        *,
        request: RagRequest,
        recorder: _RunRecorder,
        outcome: TraceOutcome,
        error_code: str,
    ) -> None:
        if recorder.persisted:
            return
        trace = GenerationTrace(
            request_id=request.request_id,
            user_id=request.user_id,
            tenant_id=request.tenant_id,
            conversation_id=request.conversation_id,
            mode=request.mode,
            outcome=outcome,
            prompt_version=PROMPT_VERSION,
            prompt_sha256=PROMPT_SHA256,
            graph_version=GRAPH_VERSION,
            question_sha256=sha256_text(request.question),
            answer_sha256=sha256_text(""),
            model=None,
            model_version=None,
            index_fingerprint=self._index_config.fingerprint,
            retrieval_policy_fingerprint=self._retrieval_policy.fingerprint,
            rewritten_query_sha256=sha256_text(request.question),
            subquery_count=0,
            retrieval_rounds=0,
            context_refs=(),
            citations=(),
            token_budget=None,
            input_tokens=None,
            output_tokens=None,
            node_path=tuple(recorder.node_path),
            timings_ms=dict(recorder.timings_ms),
            error_codes=(error_code,),
        )
        try:
            await self._trace_store.save(trace)
            recorder.persisted = True
        except Exception:
            # The client still receives a sanitized terminal error; storage errors are
            # deliberately not reflected with raw exception text.
            return

    @staticmethod
    def _visible_chunks(answer: str, size: int = 96) -> tuple[str, ...]:
        if not answer:
            return ()
        return tuple(answer[offset : offset + size] for offset in range(0, len(answer), size))
