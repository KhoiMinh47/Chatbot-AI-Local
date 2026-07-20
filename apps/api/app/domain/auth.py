"""Framework-independent domain types for Phase 7 auth, RBAC, and conversations."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

_TENANT_SENTINEL = UUID("00000000-0000-4000-8000-000000000001")


class UserRole(StrEnum):
    USER = "user"
    ADMIN = "admin"


# ------------------------------------------------------------------ errors


class AuthError(RuntimeError):
    """Base application-level auth error; never expose raw detail to the client."""

    code: str = "AUTH_ERROR"


class EmailAlreadyRegisteredError(AuthError):
    code = "EMAIL_ALREADY_REGISTERED"


class InvalidCredentialsError(AuthError):
    code = "INVALID_CREDENTIALS"


class AccountNotVerifiedError(AuthError):
    code = "ACCOUNT_NOT_VERIFIED"


class AccountDisabledError(AuthError):
    code = "ACCOUNT_DISABLED"


class TokenExpiredError(AuthError):
    code = "TOKEN_EXPIRED"


class TokenAlreadyUsedError(AuthError):
    code = "TOKEN_ALREADY_USED"


class TokenInvalidError(AuthError):
    code = "TOKEN_INVALID"


class SessionRevokedError(AuthError):
    code = "SESSION_REVOKED"


# -------------------------------------------------------------- value objects


def token_hash(raw_token: str) -> str:
    """Return the lowercase SHA-256 hex digest of a raw opaque token."""
    return hashlib.sha256(raw_token.encode()).hexdigest()


# ------------------------------------------------------------------ views


@dataclass(frozen=True, slots=True)
class UserView:
    id: UUID
    tenant_id: UUID
    email: str
    display_name: str
    role: UserRole
    is_verified: bool
    created_at: datetime


@dataclass(frozen=True, slots=True)
class SessionClaims:
    """Trusted claims extracted from a validated access JWT."""

    user_id: UUID
    tenant_id: UUID
    email: str
    role: UserRole
    session_id: UUID


@dataclass(frozen=True, slots=True)
class TokenPair:
    """Newly issued access + refresh tokens returned to the caller."""

    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int = 900  # seconds


# -------------------------------------------------------------- conversation


@dataclass(frozen=True, slots=True)
class ConversationView:
    id: UUID
    tenant_id: UUID
    user_id: UUID
    title: str
    mode: str
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class MessageView:
    id: UUID
    conversation_id: UUID
    role: str
    content_sha256: str
    generation_trace_id: UUID | None
    created_at: datetime
    content: str | None = None


# ------------------------------------------------------------------ audit


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """Append-only record; never contains raw content or secrets."""

    tenant_id: UUID
    actor_id: UUID
    action: str
    target_type: str | None = None
    target_id: UUID | None = None
    request_id: UUID | None = None
