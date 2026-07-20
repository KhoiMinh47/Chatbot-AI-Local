"""Conversation-summary and long-term-memory value objects."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Any
from uuid import UUID


class MemoryType(StrEnum):
    PREFERENCE = "preference"
    FACT = "fact"
    DECISION = "decision"
    PROJECT_STATE = "project_state"
    TODO = "todo"


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


@dataclass(frozen=True, slots=True)
class ConversationSummary:
    id: UUID
    conversation_id: UUID
    summary_version: int
    covered_message_ids: tuple[UUID, ...]
    summary: Mapping[str, Any]
    summary_text: str
    created_at: datetime

    def __post_init__(self) -> None:
        if self.summary_version <= 0:
            raise ValueError("summary_version must be positive")
        if not self.covered_message_ids:
            raise ValueError("covered_message_ids must not be empty")
        if len(self.covered_message_ids) != len(set(self.covered_message_ids)):
            raise ValueError("covered_message_ids must be unique")
        if not self.summary_text.strip():
            raise ValueError("summary_text must not be blank")
        object.__setattr__(self, "summary", MappingProxyType(dict(self.summary)))


@dataclass(frozen=True, slots=True)
class MemoryItem:
    id: UUID
    tenant_id: UUID
    user_id: UUID
    conversation_id: UUID | None
    type: MemoryType
    content: str
    source_message_ids: tuple[UUID, ...]
    confidence: float
    status: MemoryStatus
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None = None
    embedding: tuple[float, ...] | None = None
    embedding_model: str | None = None

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("memory content must not be blank")
        if not self.source_message_ids:
            raise ValueError("memory source_message_ids must not be empty")
        if len(self.source_message_ids) != len(set(self.source_message_ids)):
            raise ValueError("memory source_message_ids must be unique")
        if not math.isfinite(self.confidence) or not 0 <= self.confidence <= 1:
            raise ValueError("memory confidence must be between zero and one")
        if self.embedding is not None and any(not math.isfinite(value) for value in self.embedding):
            raise ValueError("memory embedding must contain finite values")
        if (self.embedding is None) != (self.embedding_model is None):
            raise ValueError("memory embedding and model must be present together")


@dataclass(frozen=True, slots=True)
class ConversationState:
    conversation_id: UUID
    active_document_ids: tuple[UUID, ...]
    current_task: str | None
    last_referenced_entities: tuple[str, ...]
    response_depth: str
    reasoning_policy: str
    persistent_memory_enabled: bool
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MemoryContext:
    """Small, server-selected memory record safe to add to an untrusted prompt section."""

    id: UUID
    type: MemoryType
    content: str
    score: float

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError("memory context content must not be blank")
        if not math.isfinite(self.score):
            raise ValueError("memory context score must be finite")
