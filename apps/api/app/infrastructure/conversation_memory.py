"""PostgreSQL persistence for versioned summaries and local semantic memory."""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

from sqlalchemy import Engine, text
from sqlalchemy.engine import RowMapping

from app.domain.memory import (
    ConversationState,
    ConversationSummary,
    MemoryItem,
    MemoryStatus,
    MemoryType,
)


class PostgresConversationMemoryRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _summary(row: RowMapping) -> ConversationSummary:
        return ConversationSummary(
            id=cast(UUID, row["id"]),
            conversation_id=cast(UUID, row["conversation_id"]),
            summary_version=cast(int, row["summary_version"]),
            covered_message_ids=tuple(cast(list[UUID], row["covered_message_ids"])),
            summary=cast(Mapping[str, Any], row["summary"]),
            summary_text=cast(str, row["summary_text"]),
            created_at=cast(datetime, row["created_at"]),
        )

    @staticmethod
    def _state(row: RowMapping) -> ConversationState:
        entities = row["last_referenced_entities"]
        return ConversationState(
            conversation_id=cast(UUID, row["conversation_id"]),
            active_document_ids=tuple(cast(list[UUID], row["active_document_ids"])),
            current_task=cast(str | None, row["current_task"]),
            last_referenced_entities=tuple(str(item) for item in entities if isinstance(item, str)),
            response_depth=cast(str, row["response_depth"]),
            reasoning_policy=cast(str, row["reasoning_policy"]),
            persistent_memory_enabled=cast(bool, row["persistent_memory_enabled"]),
            updated_at=cast(datetime, row["updated_at"]),
        )

    @staticmethod
    def _memory(row: RowMapping) -> MemoryItem:
        raw_embedding = cast(list[float] | None, row["embedding"])
        return MemoryItem(
            id=cast(UUID, row["id"]),
            tenant_id=cast(UUID, row["tenant_id"]),
            user_id=cast(UUID, row["user_id"]),
            conversation_id=cast(UUID | None, row["conversation_id"]),
            type=MemoryType(cast(str, row["type"])),
            content=cast(str, row["content"]),
            source_message_ids=tuple(cast(list[UUID], row["source_message_ids"])),
            confidence=cast(float, row["confidence"]),
            status=MemoryStatus(cast(str, row["status"])),
            created_at=cast(datetime, row["created_at"]),
            updated_at=cast(datetime, row["updated_at"]),
            expires_at=cast(datetime | None, row["expires_at"]),
            embedding=None if raw_embedding is None else tuple(float(v) for v in raw_embedding),
            embedding_model=cast(str | None, row["embedding_model"]),
        )

    def get_latest_summary(self, conversation_id: UUID) -> ConversationSummary | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT id,conversation_id,summary_version,covered_message_ids,"
                        "summary,summary_text,created_at FROM app.conversation_summaries "
                        "WHERE conversation_id=:conversation_id "
                        "ORDER BY summary_version DESC LIMIT 1"
                    ),
                    {"conversation_id": conversation_id},
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._summary(row)

    def save_summary(
        self,
        *,
        conversation_id: UUID,
        summary_version: int,
        covered_message_ids: tuple[UUID, ...],
        summary: Mapping[str, Any],
        summary_text: str,
    ) -> ConversationSummary:
        summary_id = uuid4()
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        "INSERT INTO app.conversation_summaries("
                        "id,conversation_id,summary_version,covered_message_ids,summary,"
                        "summary_text,created_at) VALUES("
                        ":id,:conversation_id,:summary_version,:covered_message_ids,"
                        "CAST(:summary AS jsonb),:summary_text,:created_at) "
                        "RETURNING id,conversation_id,summary_version,covered_message_ids,"
                        "summary,summary_text,created_at"
                    ),
                    {
                        "id": summary_id,
                        "conversation_id": conversation_id,
                        "summary_version": summary_version,
                        "covered_message_ids": list(covered_message_ids),
                        "summary": json.dumps(summary, ensure_ascii=False),
                        "summary_text": summary_text,
                        "created_at": now,
                    },
                )
                .mappings()
                .one()
            )
        return self._summary(row)

    def get_state(self, conversation_id: UUID) -> ConversationState | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT conversation_id,active_document_ids,current_task,"
                        "last_referenced_entities,response_depth,reasoning_policy,"
                        "persistent_memory_enabled,updated_at FROM app.conversation_state "
                        "WHERE conversation_id=:conversation_id"
                    ),
                    {"conversation_id": conversation_id},
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._state(row)

    def upsert_state(
        self,
        *,
        conversation_id: UUID,
        active_document_ids: tuple[UUID, ...],
        current_task: str | None,
        response_depth: str,
    ) -> ConversationState:
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        "INSERT INTO app.conversation_state("
                        "conversation_id,active_document_ids,current_task,"
                        "last_referenced_entities,response_depth,reasoning_policy,"
                        "persistent_memory_enabled,updated_at) VALUES("
                        ":conversation_id,:active_document_ids,:current_task,CAST('[]' AS jsonb),"
                        ":response_depth,'adaptive',true,:updated_at) "
                        "ON CONFLICT(conversation_id) DO UPDATE SET "
                        "active_document_ids=EXCLUDED.active_document_ids,"
                        "current_task=EXCLUDED.current_task,"
                        "response_depth=EXCLUDED.response_depth,updated_at=EXCLUDED.updated_at "
                        "RETURNING conversation_id,active_document_ids,current_task,"
                        "last_referenced_entities,response_depth,reasoning_policy,"
                        "persistent_memory_enabled,updated_at"
                    ),
                    {
                        "conversation_id": conversation_id,
                        "active_document_ids": list(active_document_ids),
                        "current_task": current_task,
                        "response_depth": response_depth,
                        "updated_at": now,
                    },
                )
                .mappings()
                .one()
            )
        return self._state(row)

    def set_persistent_memory_enabled(
        self, conversation_id: UUID, enabled: bool
    ) -> ConversationState:
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        "UPDATE app.conversation_state SET persistent_memory_enabled=:enabled,"
                        "updated_at=:updated_at WHERE conversation_id=:conversation_id "
                        "RETURNING conversation_id,active_document_ids,current_task,"
                        "last_referenced_entities,response_depth,reasoning_policy,"
                        "persistent_memory_enabled,updated_at"
                    ),
                    {
                        "conversation_id": conversation_id,
                        "enabled": enabled,
                        "updated_at": datetime.now(UTC),
                    },
                )
                .mappings()
                .one_or_none()
            )
        if row is None:
            self.upsert_state(
                conversation_id=conversation_id,
                active_document_ids=(),
                current_task=None,
                response_depth="detailed",
            )
            return self.set_persistent_memory_enabled(conversation_id, enabled)
        return self._state(row)

    def find_by_source_message(self, message_id: UUID) -> MemoryItem | None:
        with self._engine.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT id,tenant_id,user_id,conversation_id,type,content,"
                        "source_message_ids,confidence,embedding,embedding_model,status,"
                        "expires_at,created_at,updated_at FROM app.memory_items "
                        "WHERE :message_id=ANY(source_message_ids) AND status='active' LIMIT 1"
                    ),
                    {"message_id": message_id},
                )
                .mappings()
                .one_or_none()
            )
        return None if row is None else self._memory(row)

    def create_memory_item(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        conversation_id: UUID,
        memory_type: MemoryType,
        content: str,
        source_message_id: UUID,
        confidence: float,
        embedding: tuple[float, ...] | None,
        embedding_model: str | None,
    ) -> MemoryItem:
        item_id = uuid4()
        now = datetime.now(UTC)
        with self._engine.begin() as connection:
            row = (
                connection.execute(
                    text(
                        "INSERT INTO app.memory_items("
                        "id,tenant_id,user_id,conversation_id,type,content,source_message_ids,"
                        "confidence,embedding,embedding_model,status,created_at,updated_at) VALUES("
                        ":id,:tenant_id,:user_id,:conversation_id,:type,:content,"
                        ":source_message_ids,:confidence,:embedding,:embedding_model,'active',"
                        ":created_at,:updated_at) RETURNING id,tenant_id,user_id,conversation_id,"
                        "type,content,source_message_ids,confidence,embedding,embedding_model,"
                        "status,expires_at,created_at,updated_at"
                    ),
                    {
                        "id": item_id,
                        "tenant_id": tenant_id,
                        "user_id": user_id,
                        "conversation_id": conversation_id,
                        "type": memory_type.value,
                        "content": content,
                        "source_message_ids": [source_message_id],
                        "confidence": confidence,
                        "embedding": None if embedding is None else list(embedding),
                        "embedding_model": embedding_model,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
                .mappings()
                .one()
            )
        return self._memory(row)

    def list_active_candidates(
        self, *, tenant_id: UUID, user_id: UUID, limit: int
    ) -> tuple[MemoryItem, ...]:
        with self._engine.connect() as connection:
            rows = (
                connection.execute(
                    text(
                        "SELECT id,tenant_id,user_id,conversation_id,type,content,"
                        "source_message_ids,confidence,embedding,embedding_model,status,"
                        "expires_at,created_at,updated_at FROM app.memory_items "
                        "WHERE tenant_id=:tenant_id AND user_id=:user_id AND status='active' "
                        "AND (expires_at IS NULL OR expires_at>NOW()) "
                        "ORDER BY updated_at DESC LIMIT :limit"
                    ),
                    {"tenant_id": tenant_id, "user_id": user_id, "limit": limit},
                )
                .mappings()
                .all()
            )
        return tuple(self._memory(row) for row in rows)

    def list_items(self, *, tenant_id: UUID, user_id: UUID, limit: int) -> tuple[MemoryItem, ...]:
        return self.list_active_candidates(tenant_id=tenant_id, user_id=user_id, limit=limit)

    def set_item_status(
        self,
        *,
        item_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
        status: MemoryStatus,
    ) -> bool:
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE app.memory_items SET status=:status,updated_at=:updated_at "
                    "WHERE id=:item_id AND tenant_id=:tenant_id AND user_id=:user_id"
                ),
                {
                    "item_id": item_id,
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "status": status.value,
                    "updated_at": datetime.now(UTC),
                },
            )
        return result.rowcount == 1

    def clear_items(self, *, tenant_id: UUID, user_id: UUID) -> int:
        with self._engine.begin() as connection:
            result = connection.execute(
                text(
                    "UPDATE app.memory_items SET status='deleted',updated_at=:updated_at "
                    "WHERE tenant_id=:tenant_id AND user_id=:user_id AND status='active'"
                ),
                {
                    "tenant_id": tenant_id,
                    "user_id": user_id,
                    "updated_at": datetime.now(UTC),
                },
            )
        return result.rowcount

    def reset_conversation(self, *, conversation_id: UUID, user_id: UUID) -> None:
        with self._engine.begin() as connection:
            owns = connection.execute(
                text(
                    "SELECT 1 FROM app.conversations WHERE id=:conversation_id "
                    "AND user_id=:user_id AND deleted_at IS NULL"
                ),
                {"conversation_id": conversation_id, "user_id": user_id},
            ).one_or_none()
            if owns is None:
                raise ValueError("conversation does not belong to the user")
            connection.execute(
                text("DELETE FROM app.conversation_summaries WHERE conversation_id=:id"),
                {"id": conversation_id},
            )
            connection.execute(
                text("DELETE FROM app.conversation_state WHERE conversation_id=:id"),
                {"id": conversation_id},
            )
            connection.execute(
                text(
                    "UPDATE app.memory_items SET status='deleted',updated_at=:updated_at "
                    "WHERE conversation_id=:conversation_id AND user_id=:user_id"
                ),
                {
                    "conversation_id": conversation_id,
                    "user_id": user_id,
                    "updated_at": datetime.now(UTC),
                },
            )
            connection.execute(
                text(
                    "DELETE FROM app.messages WHERE conversation_id=:conversation_id "
                    "AND user_id=:user_id"
                ),
                {"conversation_id": conversation_id, "user_id": user_id},
            )
