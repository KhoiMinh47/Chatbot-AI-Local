"""Phase 7 conversation CRUD and chat SSE streaming endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, cast
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from app.application.auth import ConversationNotFoundError, ConversationService, SessionClaims
from app.application.conversation_memory import (
    ConversationMemoryService,
    MemoryContext,
    SourceMessage,
)
from app.application.memory import WorkingMemorySelector
from app.application.rag import ConversationTurn, RagMode, RagRequest, ResponseDepth
from app.security import get_current_claims

router = APIRouter(tags=["conversations"])
_log = logging.getLogger(__name__)

# ----------------------------------------------------------------- helpers


def _conv_svc(request: Request) -> ConversationService:
    bundle = getattr(request.app.state, "auth_bundle", None)
    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AUTH_UNAVAILABLE", "message": "Auth not configured."},
        )
    return cast(ConversationService, getattr(bundle, "conversation_service", None))


def _not_found(conversation_id: UUID) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail={"code": "CONVERSATION_NOT_FOUND", "message": f"{conversation_id} not found."},
    )


def _memory_svc(request: Request) -> ConversationMemoryService | None:
    return cast(
        ConversationMemoryService | None,
        getattr(request.app.state, "conversation_memory_service", None),
    )


# ----------------------------------------------------------------- schemas


class ConversationCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=512)
    mode: str = Field(default="fast")


class ConversationPatchRequest(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=512)
    mode: str | None = Field(default=None)


class ConversationResponse(BaseModel):
    id: str
    tenant_id: str
    user_id: str
    title: str
    mode: str
    created_at: str
    updated_at: str


class ChatStreamRequest(BaseModel):
    conversation_id: UUID
    question: str = Field(min_length=1, max_length=8000)
    language: str = Field(default="vi")
    selected_document_ids: list[UUID] = Field(default_factory=list)
    response_depth: ResponseDepth = ResponseDepth.DETAILED


class FeedbackRequest(BaseModel):
    rating: str  # thumbs_up | thumbs_down
    reason: str | None = None


class MemoryToggleRequest(BaseModel):
    enabled: bool


class MemoryItemResponse(BaseModel):
    id: str
    conversation_id: str | None
    type: str
    content: str
    confidence: float
    created_at: str
    updated_at: str


class MemoryToggleResponse(BaseModel):
    conversation_id: str
    enabled: bool


# ----------------------------------------------------------------- conversations


@router.post(
    "/api/v1/conversations",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_conversation(
    body: ConversationCreateRequest,
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    request: Request,
) -> ConversationResponse:
    svc = _conv_svc(request)
    try:
        conv = svc.create(
            tenant_id=claims.tenant_id,
            user_id=claims.user_id,
            title=body.title,
            mode=body.mode,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": str(exc)},
        ) from exc
    return ConversationResponse(
        id=str(conv.id),
        tenant_id=str(conv.tenant_id),
        user_id=str(conv.user_id),
        title=conv.title,
        mode=conv.mode,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
    )


@router.get("/api/v1/conversations", response_model=list[ConversationResponse])
def list_conversations(
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    request: Request,
    page: int = 1,
    page_size: int = 50,
) -> list[ConversationResponse]:
    svc = _conv_svc(request)
    offset = (page - 1) * page_size
    convs = svc.list_conversations(user_id=claims.user_id, limit=page_size, offset=offset)
    return [
        ConversationResponse(
            id=str(c.id),
            tenant_id=str(c.tenant_id),
            user_id=str(c.user_id),
            title=c.title,
            mode=c.mode,
            created_at=c.created_at.isoformat(),
            updated_at=c.updated_at.isoformat(),
        )
        for c in convs
    ]


@router.get("/api/v1/conversations/{conversation_id}", response_model=ConversationResponse)
def get_conversation(
    conversation_id: UUID,
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    request: Request,
) -> ConversationResponse:
    svc = _conv_svc(request)
    try:
        conv = svc.get(conversation_id=conversation_id, user_id=claims.user_id)
    except ConversationNotFoundError as _nf:
        raise _not_found(conversation_id) from _nf
    return ConversationResponse(
        id=str(conv.id),
        tenant_id=str(conv.tenant_id),
        user_id=str(conv.user_id),
        title=conv.title,
        mode=conv.mode,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
    )


@router.patch("/api/v1/conversations/{conversation_id}", response_model=ConversationResponse)
def patch_conversation(
    conversation_id: UUID,
    body: ConversationPatchRequest,
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    request: Request,
) -> ConversationResponse:
    svc = _conv_svc(request)
    try:
        if body.title is not None:
            conv = svc.rename(
                conversation_id=conversation_id,
                user_id=claims.user_id,
                title=body.title,
            )
        else:
            conv = svc.get(conversation_id=conversation_id, user_id=claims.user_id)
        if body.mode is not None:
            svc.set_mode(
                conversation_id=conversation_id,
                user_id=claims.user_id,
                mode=body.mode,
            )
            conv = svc.get(conversation_id=conversation_id, user_id=claims.user_id)
    except ConversationNotFoundError as _nf:
        raise _not_found(conversation_id) from _nf
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": str(exc)},
        ) from exc
    return ConversationResponse(
        id=str(conv.id),
        tenant_id=str(conv.tenant_id),
        user_id=str(conv.user_id),
        title=conv.title,
        mode=conv.mode,
        created_at=conv.created_at.isoformat(),
        updated_at=conv.updated_at.isoformat(),
    )


@router.delete(
    "/api/v1/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_conversation(
    conversation_id: UUID,
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    request: Request,
) -> None:
    svc = _conv_svc(request)
    try:
        svc.delete(
            conversation_id=conversation_id,
            user_id=claims.user_id,
            tenant_id=claims.tenant_id,
        )
    except ConversationNotFoundError as _nf:
        raise _not_found(conversation_id) from _nf


# ----------------------------------------------------------------- chat SSE


@router.post("/api/v1/chat/stream")
async def chat_stream(
    body: ChatStreamRequest,
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    request: Request,
) -> StreamingResponse:
    """Stream grounded RAG events as Server-Sent Events."""

    # Validate the conversation belongs to the caller
    conv_svc = _conv_svc(request)
    try:
        conv = conv_svc.get(
            conversation_id=body.conversation_id,
            user_id=claims.user_id,
        )
    except ConversationNotFoundError as _nf:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "CONVERSATION_NOT_FOUND", "message": "Conversation not found."},
        ) from _nf

    # RAG graph is optional (not available without NIM clients)
    rag_graph = getattr(request.app.state, "rag_graph", None)
    if rag_graph is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "RAG_UNAVAILABLE", "message": "RAG service is not configured."},
        )

    lang = body.language if body.language in {"vi", "en"} else "vi"
    mode = RagMode(conv.mode)

    settings = request.app.state.settings
    recent_turns: tuple[ConversationTurn, ...] = ()
    conversation_summary: str | None = None
    long_term_memories: tuple[MemoryContext, ...] = ()
    if body.selected_document_ids:
        try:
            # Persist attachments for conversation history, but use *only* the
            # documents explicitly attached to this turn for retrieval. Returning
            # every historical attachment here caused a newly attached file to be
            # mixed with old files in the same conversation.
            conv_svc.attach_documents(
                conversation_id=body.conversation_id,
                user_id=claims.user_id,
                document_ids=tuple(body.selected_document_ids),
            )
            active_document_ids = tuple(body.selected_document_ids)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={
                    "code": "DOCUMENT_NOT_FOUND",
                    "message": "One or more selected documents are unavailable.",
                },
            ) from exc
    else:
        active_document_ids = tuple(
            conv_svc.get_document_ids(
                conversation_id=body.conversation_id,
                user_id=claims.user_id,
            )
        )

    try:
        # PostgreSQL is the source of truth even when rolling/semantic memory is
        # disabled. The feature flag controls enrichment, never basic history
        # persistence or exact recent-turn loading.
        message_candidates = conv_svc.list_messages(
            conversation_id=body.conversation_id,
            user_id=claims.user_id,
            limit=settings.memory_summary_source_limit,
        )
        source_history = tuple(
            SourceMessage(id=message.id, role=message.role, content=message.content)
            for message in message_candidates
            if message.content and message.role in {"user", "assistant"}
        )
        candidates = tuple(
            ConversationTurn(
                role=message.role,  # type: ignore[arg-type]
                content=message.content,
            )
            for message in source_history
        )
        selection = WorkingMemorySelector(
            token_counter=rag_graph.token_counter,
            max_tokens=settings.memory_recent_token_limit,
            max_turns=settings.memory_recent_max_turns,
        ).select(candidates)
        recent_turns = selection.turns
        selected_message_ids = (
            frozenset(message.id for message in source_history[-len(recent_turns) :])
            if recent_turns
            else frozenset()
        )
        current_message = conv_svc.append_message(
            conversation_id=body.conversation_id,
            user_id=claims.user_id,
            role="user",
            content=body.question,
        )
        if settings.enable_new_memory:
            memory_svc = _memory_svc(request)
            if memory_svc is not None:
                try:
                    prepared = await memory_svc.prepare(
                        tenant_id=claims.tenant_id,
                        user_id=claims.user_id,
                        conversation_id=body.conversation_id,
                        history=source_history,
                        selected_message_ids=selected_message_ids,
                        current_user_message_id=current_message.id,
                        question=body.question,
                        active_document_ids=active_document_ids,
                        response_depth=body.response_depth.value,
                    )
                    conversation_summary = (
                        None if prepared.summary is None else prepared.summary.summary_text
                    )
                    long_term_memories = prepared.long_term
                except Exception:
                    _log.exception(
                        "Optional rolling/semantic memory failed; using exact recent turns"
                    )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "MEMORY_UNAVAILABLE",
                "message": "Conversation memory is temporarily unavailable.",
            },
        ) from exc

    rag_request = RagRequest(
        request_id=uuid4(),
        user_id=claims.user_id,
        tenant_id=claims.tenant_id,
        conversation_id=body.conversation_id,
        mode=mode,
        question=body.question,
        language=lang,  # type: ignore[arg-type]  # Literal["vi","en"] gated above
        acl_principals=(f"user:{claims.user_id}",),
        selected_document_ids=active_document_ids,
        recent_messages=recent_turns,
        conversation_summary=conversation_summary,
        long_term_memories=long_term_memories,
        response_depth=body.response_depth,
    )

    async def _event_stream() -> AsyncIterator[str]:
        answer_buffer = ""
        trace_request_id = rag_request.request_id
        try:
            async for event in rag_graph.stream(rag_request):
                data = {
                    "event_type": event.event_type.value,
                    "request_id": str(event.request_id),
                    "sequence": event.sequence,
                    "data": dict(event.data),
                }
                # Capture answer tokens for persistence
                if event.event_type.value == "token":
                    answer_buffer += event.data.get("text", "")
                if event.event_type.value == "done" and answer_buffer.strip():
                    try:
                        conv_svc.append_message(
                            conversation_id=body.conversation_id,
                            user_id=claims.user_id,
                            role="assistant",
                            content=answer_buffer,
                            generation_trace_id=trace_request_id,
                        )
                    except Exception:
                        error = {
                            "event_type": "error",
                            "request_id": str(trace_request_id),
                            "sequence": event.sequence,
                            "data": {
                                "code": "MEMORY_PERSIST_FAILED",
                                "message": "The answer was generated but could not be saved.",
                            },
                        }
                        yield f"data: {json.dumps(error, ensure_ascii=False)}\n\n"
                        return
                # Persist the assistant answer before the terminal event becomes
                # visible. Clients commonly close the SSE reader immediately on done.
                yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
        except asyncio.CancelledError:
            yield f"data: {json.dumps({'event_type': 'error', 'data': {'code': 'cancelled'}})}\n\n"
        except Exception as exc:
            from app.application.rag import OverloadError

            if isinstance(exc, OverloadError):
                payload = {
                    "event_type": "error",
                    "data": {"code": "overloaded", "message": str(exc)},
                }
                yield f"data: {json.dumps(payload)}\n\n"
            else:
                import logging

                logging.getLogger(__name__).exception("RAG execution failed")
                payload = {
                    "event_type": "error",
                    "data": {"code": "rag_execution_failed"},
                }
                yield f"data: {json.dumps(payload)}\n\n"

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


# ----------------------------------------------------------------- messages


class MessageResponse(BaseModel):
    id: str
    conversation_id: str
    role: str
    content: str | None
    created_at: str


@router.get(
    "/api/v1/conversations/{conversation_id}/messages",
    response_model=list[MessageResponse],
)
def list_messages(
    conversation_id: UUID,
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    request: Request,
    limit: int = 50,
) -> list[MessageResponse]:
    """Return conversation messages with content for frontend display."""
    svc = _conv_svc(request)
    try:
        messages = svc.list_messages(
            conversation_id=conversation_id,
            user_id=claims.user_id,
            limit=min(limit, 100),
        )
    except ConversationNotFoundError as _nf:
        raise _not_found(conversation_id) from _nf
    return [
        MessageResponse(
            id=str(msg.id),
            conversation_id=str(msg.conversation_id),
            role=msg.role,
            content=msg.content,
            created_at=msg.created_at.isoformat(),
        )
        for msg in messages
    ]


# --------------------------------------------------------------- memory admin


@router.get("/api/v1/memory", response_model=list[MemoryItemResponse])
def list_persistent_memory(
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    request: Request,
    limit: int = 100,
) -> list[MemoryItemResponse]:
    service = _memory_svc(request)
    if service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "MEMORY_UNAVAILABLE", "message": "Memory is not configured."},
        )
    items = service.list_items(
        tenant_id=claims.tenant_id,
        user_id=claims.user_id,
        limit=min(max(limit, 1), 500),
    )
    return [
        MemoryItemResponse(
            id=str(item.id),
            conversation_id=None if item.conversation_id is None else str(item.conversation_id),
            type=item.type.value,
            content=item.content,
            confidence=item.confidence,
            created_at=item.created_at.isoformat(),
            updated_at=item.updated_at.isoformat(),
        )
        for item in items
    ]


@router.delete("/api/v1/memory/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_persistent_memory(
    item_id: UUID,
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    request: Request,
) -> None:
    service = _memory_svc(request)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    if not service.delete_item(
        item_id=item_id,
        tenant_id=claims.tenant_id,
        user_id=claims.user_id,
    ):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)


@router.delete("/api/v1/memory", response_model=dict[str, int])
def clear_persistent_memory(
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    request: Request,
) -> dict[str, int]:
    service = _memory_svc(request)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    return {
        "deleted": service.clear_items(
            tenant_id=claims.tenant_id,
            user_id=claims.user_id,
        )
    }


@router.put(
    "/api/v1/conversations/{conversation_id}/memory",
    response_model=MemoryToggleResponse,
)
def toggle_conversation_memory(
    conversation_id: UUID,
    body: MemoryToggleRequest,
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    request: Request,
) -> MemoryToggleResponse:
    _conv_svc(request).get(conversation_id=conversation_id, user_id=claims.user_id)
    service = _memory_svc(request)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    state = service.set_enabled(conversation_id=conversation_id, enabled=body.enabled)
    return MemoryToggleResponse(
        conversation_id=str(conversation_id),
        enabled=state.persistent_memory_enabled,
    )


@router.delete(
    "/api/v1/conversations/{conversation_id}/memory",
    status_code=status.HTTP_204_NO_CONTENT,
)
def reset_conversation_memory(
    conversation_id: UUID,
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    request: Request,
) -> None:
    _conv_svc(request).get(conversation_id=conversation_id, user_id=claims.user_id)
    service = _memory_svc(request)
    if service is None:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE)
    service.reset_conversation(conversation_id=conversation_id, user_id=claims.user_id)


# ----------------------------------------------------------------- feedback


@router.post(
    "/api/v1/messages/{message_id}/feedback",
    status_code=status.HTTP_204_NO_CONTENT,
)
def submit_feedback(
    message_id: UUID,
    body: FeedbackRequest,
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    request: Request,
) -> None:
    svc = _conv_svc(request)
    try:
        svc.add_feedback(
            message_id=message_id,
            user_id=claims.user_id,
            rating=body.rating,
            reason=body.reason,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "VALIDATION_ERROR", "message": str(exc)},
        ) from exc
