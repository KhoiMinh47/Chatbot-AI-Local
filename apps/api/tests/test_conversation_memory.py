"""Regression tests for summary provenance and tenant-scoped semantic memory."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from app.application.ai_clients import EmbeddingResponse
from app.application.conversation_memory import (
    ConversationMemoryService,
    SourceMessage,
)
from app.domain.memory import (
    ConversationState,
    ConversationSummary,
    MemoryItem,
    MemoryStatus,
    MemoryType,
)


class FakeEmbedding:
    async def embed(self, request):
        vectors = tuple((1.0, 0.0) if "Nemotron" in text else (0.8, 0.2) for text in request.texts)
        return EmbeddingResponse(
            vectors=vectors,
            dimension=2,
            model="embed-test",
            model_version="1",
            latency_seconds=0.001,
        )


class FakeSummarizer:
    def __init__(self) -> None:
        self.calls: list[tuple[object, tuple[SourceMessage, ...]]] = []

    async def summarize(self, *, previous, messages):
        self.calls.append((previous, messages))
        facts = [] if previous is None else list(previous["known_facts"])
        facts.extend(message.content for message in messages)
        return {
            "user_goal": "Optimize the local chatbot",
            "known_facts": facts,
            "decisions": [],
            "open_questions": [],
            "constraints": [],
            "referenced_documents": [],
            "current_working_state": "Continuing",
        }


class FakeRepository:
    def __init__(self) -> None:
        self.summaries: list[ConversationSummary] = []
        self.items: list[MemoryItem] = []
        self.states: dict[UUID, ConversationState] = {}

    def get_latest_summary(self, conversation_id):
        matches = [s for s in self.summaries if s.conversation_id == conversation_id]
        return matches[-1] if matches else None

    def save_summary(
        self,
        *,
        conversation_id,
        summary_version,
        covered_message_ids,
        summary,
        summary_text,
    ):
        result = ConversationSummary(
            id=uuid4(),
            conversation_id=conversation_id,
            summary_version=summary_version,
            covered_message_ids=covered_message_ids,
            summary=summary,
            summary_text=summary_text,
            created_at=datetime.now(UTC),
        )
        self.summaries.append(result)
        return result

    def get_state(self, conversation_id):
        return self.states.get(conversation_id)

    def upsert_state(
        self,
        *,
        conversation_id,
        active_document_ids,
        current_task,
        response_depth,
    ):
        existing = self.states.get(conversation_id)
        result = ConversationState(
            conversation_id=conversation_id,
            active_document_ids=active_document_ids,
            current_task=current_task,
            last_referenced_entities=(),
            response_depth=response_depth,
            reasoning_policy="adaptive",
            persistent_memory_enabled=(
                True if existing is None else existing.persistent_memory_enabled
            ),
            updated_at=datetime.now(UTC),
        )
        self.states[conversation_id] = result
        return result

    def set_persistent_memory_enabled(self, conversation_id, enabled):
        current = self.states[conversation_id]
        result = ConversationState(
            conversation_id=conversation_id,
            active_document_ids=current.active_document_ids,
            current_task=current.current_task,
            last_referenced_entities=current.last_referenced_entities,
            response_depth=current.response_depth,
            reasoning_policy=current.reasoning_policy,
            persistent_memory_enabled=enabled,
            updated_at=datetime.now(UTC),
        )
        self.states[conversation_id] = result
        return result

    def find_by_source_message(self, message_id):
        return next(
            (item for item in self.items if message_id in item.source_message_ids),
            None,
        )

    def create_memory_item(
        self,
        *,
        tenant_id,
        user_id,
        conversation_id,
        memory_type,
        content,
        source_message_id,
        confidence,
        embedding,
        embedding_model,
    ):
        now = datetime.now(UTC)
        item = MemoryItem(
            id=uuid4(),
            tenant_id=tenant_id,
            user_id=user_id,
            conversation_id=conversation_id,
            type=memory_type,
            content=content,
            source_message_ids=(source_message_id,),
            confidence=confidence,
            status=MemoryStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            embedding=embedding,
            embedding_model=embedding_model,
        )
        self.items.append(item)
        return item

    def list_active_candidates(self, *, tenant_id, user_id, limit):
        return tuple(
            item
            for item in reversed(self.items)
            if item.tenant_id == tenant_id
            and item.user_id == user_id
            and item.status is MemoryStatus.ACTIVE
        )[:limit]

    def list_items(self, *, tenant_id, user_id, limit):
        return self.list_active_candidates(tenant_id=tenant_id, user_id=user_id, limit=limit)

    def set_item_status(self, *, item_id, tenant_id, user_id, status):
        del item_id, tenant_id, user_id, status
        return False

    def clear_items(self, *, tenant_id, user_id):
        del tenant_id, user_id
        return 0

    def reset_conversation(self, *, conversation_id, user_id):
        del conversation_id, user_id


def service(repo: FakeRepository, summarizer: FakeSummarizer) -> ConversationMemoryService:
    return ConversationMemoryService(
        repository=repo,
        summarizer=summarizer,  # type: ignore[arg-type]
        embedding=FakeEmbedding(),  # type: ignore[arg-type]
        embedding_model="embed-test@1",
    )


@pytest.mark.anyio
async def test_summary_versions_cover_only_dropped_messages_without_drift() -> None:
    repo = FakeRepository()
    summarizer = FakeSummarizer()
    memory = service(repo, summarizer)
    conversation_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()
    first = SourceMessage(uuid4(), "user", "Model là Nemotron Nano 9B v2")
    second = SourceMessage(uuid4(), "assistant", "Đã xác nhận model")

    prepared = await memory.prepare(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        history=(first, second),
        selected_message_ids=frozenset({second.id}),
        current_user_message_id=uuid4(),
        question="Tiếp tục tối ưu",
        active_document_ids=(),
        response_depth="detailed",
    )

    assert prepared.summary is not None
    assert prepared.summary.summary_version == 1
    assert prepared.summary.covered_message_ids == (first.id,)
    assert prepared.summary.summary["known_facts"] == [first.content]

    third = SourceMessage(uuid4(), "user", "Embedding là 300M v2")
    prepared = await memory.prepare(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        history=(first, second, third),
        selected_message_ids=frozenset({third.id}),
        current_user_message_id=uuid4(),
        question="Tiếp tục",
        active_document_ids=(),
        response_depth="detailed",
    )

    assert prepared.summary is not None
    assert prepared.summary.summary_version == 2
    assert prepared.summary.covered_message_ids == (first.id, second.id)
    assert prepared.summary.summary["known_facts"][0] == first.content


@pytest.mark.anyio
async def test_explicit_memory_is_embedded_and_retrieved_without_cross_user_leak() -> None:
    repo = FakeRepository()
    memory = service(repo, FakeSummarizer())
    tenant_id = uuid4()
    user_id = uuid4()
    conversation_id = uuid4()
    source_id = uuid4()

    await memory.prepare(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        history=(),
        selected_message_ids=frozenset(),
        current_user_message_id=source_id,
        question="Tôi muốn luôn dùng Nemotron cho project này",
        active_document_ids=(),
        response_depth="detailed",
    )
    assert len(repo.items) == 1
    assert repo.items[0].type is MemoryType.PREFERENCE
    assert repo.items[0].embedding is not None

    prepared = await memory.prepare(
        tenant_id=tenant_id,
        user_id=user_id,
        conversation_id=conversation_id,
        history=(),
        selected_message_ids=frozenset(),
        current_user_message_id=uuid4(),
        question="Model nào được ưu tiên cho project?",
        active_document_ids=(),
        response_depth="detailed",
    )
    assert [item.content for item in prepared.long_term] == [repo.items[0].content]

    other_user = await memory.prepare(
        tenant_id=tenant_id,
        user_id=uuid4(),
        conversation_id=uuid4(),
        history=(),
        selected_message_ids=frozenset(),
        current_user_message_id=uuid4(),
        question="Model nào được ưu tiên?",
        active_document_ids=(),
        response_depth="detailed",
    )
    assert other_user.long_term == ()
