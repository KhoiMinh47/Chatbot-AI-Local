"""Phase 7 Admin API endpoints (admin-only, backed by real data sources)."""

from __future__ import annotations

from typing import Annotated, Any, cast
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from app.application.auth import AuthService, SessionClaims, UserRole
from app.security import require_admin

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

# ----------------------------------------------------------------- helpers


def _auth_svc(request: Request) -> AuthService:
    bundle = getattr(request.app.state, "auth_bundle", None)
    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AUTH_UNAVAILABLE", "message": "Auth not configured."},
        )
    return cast(AuthService, getattr(bundle, "auth_service", None))


# ----------------------------------------------------------------- schemas


class UserAdminResponse(BaseModel):
    id: str
    tenant_id: str
    email: str
    display_name: str
    role: str
    is_verified: bool
    created_at: str


class PatchUserRequest(BaseModel):
    role: str | None = None  # "user" | "admin"
    display_name: str | None = None


class AuditLogResponse(BaseModel):
    id: str
    actor_id: str
    action: str
    target_type: str | None
    target_id: str | None
    created_at: str


# ------------------------------------------------------------------ users


@router.get("/users", response_model=list[UserAdminResponse])
def list_users(
    claims: Annotated[SessionClaims, Depends(require_admin)],
    request: Request,
    page: int = 1,
    page_size: int = 50,
) -> list[UserAdminResponse]:
    _auth_svc(request)
    bundle = request.app.state.auth_bundle
    repo = bundle.auth_service._users
    offset = (page - 1) * page_size
    users = repo.list_users(claims.tenant_id, limit=page_size, offset=offset)
    return [
        UserAdminResponse(
            id=str(u.id),
            tenant_id=str(u.tenant_id),
            email=u.email,
            display_name=u.display_name,
            role=u.role.value,
            is_verified=u.is_verified,
            created_at=u.created_at.isoformat(),
        )
        for u in users
    ]


@router.patch("/users/{user_id}", response_model=UserAdminResponse)
def patch_user(
    user_id: UUID,
    body: PatchUserRequest,
    claims: Annotated[SessionClaims, Depends(require_admin)],
    request: Request,
) -> UserAdminResponse:
    bundle = request.app.state.auth_bundle
    repo = bundle.auth_service._users
    audit_repo = bundle.auth_service._audit

    user = repo.find_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "USER_NOT_FOUND", "message": "User not found."},
        )

    if body.role is not None:
        try:
            new_role = UserRole(body.role)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"code": "INVALID_ROLE", "message": "Role must be user or admin."},
            ) from exc
        repo.update_role(user_id, new_role)
        from app.application.auth import AuditEvent

        audit_repo.append(
            AuditEvent(
                tenant_id=claims.tenant_id,
                actor_id=claims.user_id,
                action="admin.user.role_changed",
                target_type="user",
                target_id=user_id,
            )
        )

    updated = repo.find_by_id(user_id)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return UserAdminResponse(
        id=str(updated.id),
        tenant_id=str(updated.tenant_id),
        email=updated.email,
        display_name=updated.display_name,
        role=updated.role.value,
        is_verified=updated.is_verified,
        created_at=updated.created_at.isoformat(),
    )


# ----------------------------------------------------------------- services


@router.get("/services")
async def get_services(
    claims: Annotated[SessionClaims, Depends(require_admin)],
    request: Request,
) -> dict[str, Any]:
    """Return same data as /health/dependencies but admin-only."""
    from app.application.get_dependency_health import GetDependencyHealth

    use_case: GetDependencyHealth = request.app.state.get_dependency_health
    health = await use_case.execute()
    return {
        "ready": health.ready,
        "dependencies": [
            {
                "name": d.name,
                "status": d.status,
                "required_for_readiness": d.required_for_readiness,
            }
            for d in health.dependencies
        ],
    }


# ---------------------------------------------------------------- audit logs


@router.get("/audit-logs", response_model=list[AuditLogResponse])
def get_audit_logs(
    claims: Annotated[SessionClaims, Depends(require_admin)],
    request: Request,
    page: int = 1,
    page_size: int = 100,
) -> list[AuditLogResponse]:
    bundle = request.app.state.auth_bundle
    audit_repo = bundle.auth_service._audit
    offset = (page - 1) * page_size
    rows = audit_repo.list_events(claims.tenant_id, limit=page_size, offset=offset)
    return [
        AuditLogResponse(
            id=str(r.id),
            actor_id=str(r.actor_id),
            action=r.action,
            target_type=r.target_type,
            target_id=str(r.target_id) if r.target_id else None,
            created_at=r.created_at.isoformat(),
        )
        for r in rows
    ]


# ----------------------------------------------------------------- documents overview


@router.get("/documents")
def get_documents_overview(
    claims: Annotated[SessionClaims, Depends(require_admin)],
    request: Request,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    """Admin-scoped document list; uses ingestion service if available."""
    ingestion_svc = getattr(request.app.state, "ingestion_service", None)
    if ingestion_svc is None:
        return {"documents": [], "total": 0, "note": "Ingestion service not configured."}
    from app.application.ingestion import ActorContext

    actor = ActorContext(tenant_id=claims.tenant_id, user_id=claims.user_id)
    offset = (page - 1) * page_size
    docs, total = ingestion_svc.list_documents(actor, limit=page_size, offset=offset)
    return {
        "documents": [
            {
                "id": str(d.id),
                "source_name": d.source_name,
                "mime_type": d.mime_type,
                "state": d.state,
                "error_code": d.error_code,
                "created_at": d.created_at.isoformat(),
            }
            for d in docs
        ],
        "total": total,
    }


# ----------------------------------------------------------------- dashboard stats


class AdminStatsResponse(BaseModel):
    users_count: int
    documents_count: int


@router.get("/stats", response_model=AdminStatsResponse)
def get_admin_stats(
    claims: Annotated[SessionClaims, Depends(require_admin)],
    request: Request,
) -> AdminStatsResponse:
    bundle = request.app.state.auth_bundle
    user_repo = bundle.auth_service._users
    users_count = user_repo.count_users(claims.tenant_id)

    ingestion_svc = getattr(request.app.state, "ingestion_service", None)
    documents_count = 0
    if ingestion_svc is not None:
        from app.application.ingestion import ActorContext

        actor = ActorContext(tenant_id=claims.tenant_id, user_id=claims.user_id)
        import contextlib

        with contextlib.suppress(Exception):
            _, documents_count = ingestion_svc.list_documents(actor, limit=1, offset=0)

    return AdminStatsResponse(users_count=users_count, documents_count=documents_count)


# ----------------------------------------------------------------- active config


class AdminConfigResponse(BaseModel):
    nim_clients_enabled: bool
    llm_model: str | None
    llm_model_version: str | None
    embed_model: str | None
    embed_model_version: str | None
    rerank_model: str | None
    rerank_model_version: str | None
    prompt_version: str
    prompt_sha256: str
    graph_version: str


@router.get("/config", response_model=AdminConfigResponse)
def get_admin_config(
    claims: Annotated[SessionClaims, Depends(require_admin)],
    request: Request,
) -> AdminConfigResponse:
    settings = request.app.state.settings
    from app.application.rag import GRAPH_VERSION, PROMPT_SHA256, PROMPT_VERSION

    return AdminConfigResponse(
        nim_clients_enabled=settings.nim_clients_enabled,
        llm_model=settings.nim_llm_model,
        llm_model_version=settings.nim_llm_model_version,
        embed_model=settings.nim_embed_model,
        embed_model_version=settings.nim_embed_model_version,
        rerank_model=settings.nim_rerank_model,
        rerank_model_version=settings.nim_rerank_model_version,
        prompt_version=PROMPT_VERSION,
        prompt_sha256=PROMPT_SHA256,
        graph_version=GRAPH_VERSION,
    )
