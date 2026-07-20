"""Phase 7 FastAPI security dependencies: JWT bearer, role gates."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.domain.auth import SessionClaims, TokenExpiredError, TokenInvalidError, UserRole
from app.domain.ingestion import ActorContext
from app.infrastructure.auth import JwtTokenFactory

_bearer = HTTPBearer(auto_error=False)


def _token_factory(request: Request) -> JwtTokenFactory | None:
    bundle = getattr(request.app.state, "auth_bundle", None)
    if bundle is None:
        return None
    svc = getattr(bundle, "auth_service", None)
    if svc is None:
        return None
    return getattr(svc, "_tokens", None)


async def get_current_claims(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)] = None,
) -> SessionClaims:
    """Extract and validate the Bearer JWT; raise 401 on failure."""

    factory = _token_factory(request)
    if factory is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AUTH_UNAVAILABLE", "message": "Auth is not configured."},
        )
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
            detail={"code": "MISSING_TOKEN", "message": "Authorization header required."},
        )
    try:
        return factory.decode_access_token(credentials.credentials)
    except TokenExpiredError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
            detail={"code": "TOKEN_EXPIRED", "message": "Access token has expired."},
        ) from exc
    except TokenInvalidError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            headers={"WWW-Authenticate": "Bearer"},
            detail={"code": "TOKEN_INVALID", "message": "Access token is invalid."},
        ) from exc


async def require_admin(
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
) -> SessionClaims:
    """Raise 403 unless caller holds the admin role."""
    if claims.role is not UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": "Admin access required."},
        )
    return claims


def claims_to_actor(claims: SessionClaims) -> ActorContext:
    """Map validated JWT claims to the domain ActorContext used by ingestion."""
    return ActorContext(tenant_id=claims.tenant_id, user_id=claims.user_id)
