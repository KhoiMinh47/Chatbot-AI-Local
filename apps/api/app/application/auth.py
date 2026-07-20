"""Phase 7 auth use cases and application ports.

Ports (Protocol classes) are implemented by infrastructure adapters.
Use cases enforce business rules and never import FastAPI or SQLAlchemy.

All domain types that the API layer needs are re-exported here so
the api layer never imports app.domain directly.
"""

from __future__ import annotations

import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import UUID

from app.domain.auth import (
    AccountDisabledError,
    AccountNotVerifiedError,
    AuditEvent,
    ConversationView,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    MessageView,
    SessionClaims,
    SessionRevokedError,
    TokenAlreadyUsedError,
    TokenExpiredError,
    TokenInvalidError,
    TokenPair,
    UserRole,
    UserView,
    token_hash,
)
from app.domain.rag import ConversationTurn

# Re-export domain types so that app.api.* can import from app.application.auth
# and remain within the architecture boundary (api → application only).
__all__ = [
    "AccountDisabledError",
    "AccountNotVerifiedError",
    "AuditEvent",
    "AuthService",
    "ConversationNotFoundError",
    "ConversationService",
    "ConversationView",
    "EmailAlreadyRegisteredError",
    "InvalidCredentialsError",
    "MessageView",
    "SessionClaims",
    "SessionRevokedError",
    "TokenAlreadyUsedError",
    "TokenExpiredError",
    "TokenInvalidError",
    "TokenPair",
    "UserRole",
    "UserView",
    "token_hash",
]

# ------------------------------------------------------------------ ports


class PasswordHasher(Protocol):
    def hash(self, password: str) -> str: ...
    def verify(self, password: str, hashed: str) -> bool: ...


class TokenFactory(Protocol):
    def create_access_token(self, claims: SessionClaims) -> str: ...
    def decode_access_token(self, token: str) -> SessionClaims: ...


class UserRepository(Protocol):
    def find_by_email(self, tenant_id: UUID, email: str) -> UserView | None: ...
    def find_by_id(self, user_id: UUID) -> UserView | None: ...
    def create(
        self,
        *,
        tenant_id: UUID,
        email: str,
        password_hash: str,
        display_name: str,
        role: UserRole,
    ) -> UserView: ...
    def set_verified(self, user_id: UUID) -> None: ...
    def update_password(self, user_id: UUID, password_hash: str) -> None: ...
    def update_role(self, user_id: UUID, role: UserRole) -> None: ...
    def soft_delete(self, user_id: UUID) -> None: ...
    def list_users(self, tenant_id: UUID, *, limit: int, offset: int) -> list[UserView]: ...
    def count_users(self, tenant_id: UUID) -> int: ...


class SessionRepository(Protocol):
    def create_session(self, *, user_id: UUID, token_hash: str, expires_at: datetime) -> UUID: ...
    def find_session(self, token_hash: str) -> _SessionRow | None: ...
    def revoke_session(self, session_id: UUID) -> None: ...
    def revoke_all_sessions(self, user_id: UUID) -> None: ...


class VerificationTokenRepository(Protocol):
    def create_token(self, *, user_id: UUID, token_hash: str, expires_at: datetime) -> UUID: ...
    def consume_token(self, token_hash: str) -> UUID: ...  # returns user_id


class PasswordResetTokenRepository(Protocol):
    def create_token(self, *, user_id: UUID, token_hash: str, expires_at: datetime) -> UUID: ...
    def consume_token(self, token_hash: str) -> UUID: ...  # returns user_id


class EmailService(Protocol):
    async def send_verification(self, *, to_email: str, token: str) -> None: ...
    async def send_password_reset(self, *, to_email: str, token: str) -> None: ...


class AuditRepository(Protocol):
    def append(self, event: AuditEvent) -> None: ...
    def list_events(self, tenant_id: UUID, *, limit: int, offset: int) -> list[_AuditRow]: ...


class ConversationRepository(Protocol):
    def create(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        title: str,
        mode: str,
    ) -> ConversationView: ...
    def find(self, conversation_id: UUID, user_id: UUID) -> ConversationView | None: ...
    def list_by_user(self, user_id: UUID, *, limit: int, offset: int) -> list[ConversationView]: ...
    def rename(self, conversation_id: UUID, user_id: UUID, title: str) -> ConversationView: ...
    def soft_delete(self, conversation_id: UUID, user_id: UUID) -> None: ...
    def set_mode(self, conversation_id: UUID, user_id: UUID, mode: str) -> None: ...
    def add_document(self, conversation_id: UUID, document_id: UUID, user_id: UUID) -> None: ...
    def remove_document(self, conversation_id: UUID, document_id: UUID) -> None: ...
    def list_document_ids(self, conversation_id: UUID) -> list[UUID]: ...


class MessageRepository(Protocol):
    def append(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        role: str,
        content_sha256: str,
        generation_trace_id: UUID | None,
        content: str,
    ) -> MessageView: ...
    def list_by_conversation(
        self, conversation_id: UUID, *, limit: int, offset: int
    ) -> list[MessageView]: ...
    def list_recent_with_content(self, conversation_id: UUID, *, limit: int) -> list[MessageView]:
        """Return the most recent messages with content for RAG memory."""
        ...


class FeedbackRepository(Protocol):
    def upsert(
        self, *, message_id: UUID, user_id: UUID, rating: str, reason: str | None
    ) -> None: ...


# -------------------------------------------------------------- internal


@dataclass(frozen=True, slots=True)
class _SessionRow:
    session_id: UUID
    user_id: UUID
    expires_at: datetime
    revoked_at: datetime | None


@dataclass(frozen=True, slots=True)
class _AuditRow:
    id: UUID
    tenant_id: UUID
    actor_id: UUID
    action: str
    target_type: str | None
    target_id: UUID | None
    request_id: UUID | None
    created_at: datetime


# -------------------------------------------------------------- constants

_ACCESS_TOKEN_TTL = timedelta(minutes=15)
_REFRESH_TOKEN_TTL = timedelta(days=30)
_VERIFY_TOKEN_TTL = timedelta(hours=24)
_RESET_TOKEN_TTL = timedelta(minutes=30)
_TOKEN_BYTES = 32  # 256-bit entropy for opaque tokens


def _opaque_token() -> str:
    """Return a URL-safe 256-bit random token."""
    return secrets.token_urlsafe(_TOKEN_BYTES)


# ================================================================= services


class AuthService:
    """Orchestrates all auth use cases; stateless between calls."""

    def __init__(
        self,
        *,
        password_hasher: PasswordHasher,
        token_factory: TokenFactory,
        user_repo: UserRepository,
        session_repo: SessionRepository,
        verify_repo: VerificationTokenRepository,
        reset_repo: PasswordResetTokenRepository,
        email_svc: EmailService,
        audit_repo: AuditRepository,
        default_tenant_id: UUID,
    ) -> None:
        self._hash = password_hasher
        self._tokens = token_factory
        self._users = user_repo
        self._sessions = session_repo
        self._verify = verify_repo
        self._reset = reset_repo
        self._email = email_svc
        self._audit = audit_repo
        self._tenant = default_tenant_id

    # ---------------------------------------------------------------- register

    async def register(
        self,
        *,
        email: str,
        password: str,
        display_name: str,
    ) -> UserView:
        """Create account and enqueue verification email."""

        norm_email = email.strip().lower()
        if self._users.find_by_email(self._tenant, norm_email) is not None:
            raise EmailAlreadyRegisteredError("Email is already registered.")

        pw_hash = self._hash.hash(password)
        user = self._users.create(
            tenant_id=self._tenant,
            email=norm_email,
            password_hash=pw_hash,
            display_name=display_name.strip(),
            role=UserRole.USER,
        )

        raw_token = _opaque_token()
        self._verify.create_token(
            user_id=user.id,
            token_hash=token_hash(raw_token),
            expires_at=datetime.now(UTC) + _VERIFY_TOKEN_TTL,
        )
        await self._email.send_verification(to_email=norm_email, token=raw_token)
        self._audit.append(
            AuditEvent(
                tenant_id=self._tenant,
                actor_id=user.id,
                action="user.registered",
                target_type="user",
                target_id=user.id,
            )
        )
        return user

    # -------------------------------------------------------------- verify_email

    def verify_email(self, *, raw_token: str) -> UserView:
        """Consume the one-time token and mark the account as verified."""

        try:
            user_id = self._verify.consume_token(token_hash(raw_token))
        except TokenExpiredError:
            raise
        except TokenAlreadyUsedError:
            raise
        except Exception:
            raise TokenInvalidError("Verification token is invalid.") from None

        self._users.set_verified(user_id)
        user = self._users.find_by_id(user_id)
        if user is None:
            raise TokenInvalidError("User no longer exists.")
        self._audit.append(
            AuditEvent(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                action="user.email_verified",
                target_type="user",
                target_id=user.id,
            )
        )
        return user

    # ------------------------------------------------------------------ login

    def login(self, *, email: str, password: str) -> TokenPair:
        """Verify credentials, create a rotating refresh session, return token pair."""

        norm_email = email.strip().lower()
        user = self._users.find_by_email(self._tenant, norm_email)
        if user is None or not self._hash.verify(password, _get_password_hash(user)):
            raise InvalidCredentialsError("Email or password is incorrect.")
        if not user.is_verified:
            raise AccountNotVerifiedError("Please verify your email address first.")

        raw_refresh = _opaque_token()
        session_id = self._sessions.create_session(
            user_id=user.id,
            token_hash=token_hash(raw_refresh),
            expires_at=datetime.now(UTC) + _REFRESH_TOKEN_TTL,
        )
        claims = SessionClaims(
            user_id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            role=user.role,
            session_id=session_id,
        )
        access = self._tokens.create_access_token(claims)
        self._audit.append(
            AuditEvent(
                tenant_id=user.tenant_id,
                actor_id=user.id,
                action="user.login",
                target_type="user",
                target_id=user.id,
            )
        )
        return TokenPair(
            access_token=access,
            refresh_token=raw_refresh,
            expires_in=int(_ACCESS_TOKEN_TTL.total_seconds()),
        )

    # --------------------------------------------------------------- refresh

    def refresh(self, *, raw_refresh_token: str) -> TokenPair:
        """Rotate the refresh token and issue a new access token."""

        row = self._sessions.find_session(token_hash(raw_refresh_token))
        if row is None:
            raise TokenInvalidError("Refresh token not found.")
        if row.revoked_at is not None:
            raise SessionRevokedError("Session has been revoked.")
        if row.expires_at <= datetime.now(UTC):
            raise TokenExpiredError("Refresh token has expired.")

        user = self._users.find_by_id(row.user_id)
        if user is None:
            raise TokenInvalidError("User no longer exists.")

        # Revoke old session and issue new one (rotation)
        self._sessions.revoke_session(row.session_id)
        raw_new = _opaque_token()
        new_session_id = self._sessions.create_session(
            user_id=user.id,
            token_hash=token_hash(raw_new),
            expires_at=datetime.now(UTC) + _REFRESH_TOKEN_TTL,
        )
        claims = SessionClaims(
            user_id=user.id,
            tenant_id=user.tenant_id,
            email=user.email,
            role=user.role,
            session_id=new_session_id,
        )
        return TokenPair(
            access_token=self._tokens.create_access_token(claims),
            refresh_token=raw_new,
            expires_in=int(_ACCESS_TOKEN_TTL.total_seconds()),
        )

    # ---------------------------------------------------------------- logout

    def logout(self, *, session_id: UUID) -> None:
        """Revoke the specific refresh session."""
        self._sessions.revoke_session(session_id)

    # --------------------------------------------------------- forgot_password

    async def forgot_password(self, *, email: str) -> None:
        """Send a reset email; silently succeed if the email is unknown (anti-enum)."""

        norm_email = email.strip().lower()
        user = self._users.find_by_email(self._tenant, norm_email)
        if user is None:
            return  # do not leak whether email exists

        raw_token = _opaque_token()
        self._reset.create_token(
            user_id=user.id,
            token_hash=token_hash(raw_token),
            expires_at=datetime.now(UTC) + _RESET_TOKEN_TTL,
        )
        await self._email.send_password_reset(to_email=norm_email, token=raw_token)

    # --------------------------------------------------------- reset_password

    def reset_password(self, *, raw_token: str, new_password: str) -> None:
        """Consume the one-time token, hash and store new password, revoke sessions."""

        try:
            user_id = self._reset.consume_token(token_hash(raw_token))
        except (TokenExpiredError, TokenAlreadyUsedError):
            raise
        except Exception:
            raise TokenInvalidError("Password reset token is invalid.") from None

        pw_hash = self._hash.hash(new_password)
        self._users.update_password(user_id, pw_hash)
        self._sessions.revoke_all_sessions(user_id)

    # --------------------------------------------------------------- me

    def get_me(self, *, user_id: UUID) -> UserView:
        user = self._users.find_by_id(user_id)
        if user is None:
            raise TokenInvalidError("User not found.")
        return user


# ============================================================ conversation service


class ConversationService:
    """CRUD operations on conversations; always tenant + user scoped."""

    def __init__(
        self,
        *,
        conv_repo: ConversationRepository,
        msg_repo: MessageRepository,
        feedback_repo: FeedbackRepository,
        audit_repo: AuditRepository,
    ) -> None:
        self._convs = conv_repo
        self._msgs = msg_repo
        self._feedback = feedback_repo
        self._audit = audit_repo

    def create(
        self,
        *,
        tenant_id: UUID,
        user_id: UUID,
        title: str,
        mode: str = "fast",
    ) -> ConversationView:
        if mode not in {"fast", "reasoning"}:
            raise ValueError("mode must be fast or reasoning")
        stripped = title.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        conv = self._convs.create(tenant_id=tenant_id, user_id=user_id, title=stripped, mode=mode)
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                actor_id=user_id,
                action="conversation.created",
                target_type="conversation",
                target_id=conv.id,
            )
        )
        return conv

    def list_conversations(
        self, *, user_id: UUID, limit: int = 50, offset: int = 0
    ) -> list[ConversationView]:
        return self._convs.list_by_user(user_id, limit=limit, offset=offset)

    def get(self, *, conversation_id: UUID, user_id: UUID) -> ConversationView:
        conv = self._convs.find(conversation_id, user_id)
        if conv is None:
            raise ConversationNotFoundError(f"Conversation {conversation_id} not found.")
        return conv

    def rename(self, *, conversation_id: UUID, user_id: UUID, title: str) -> ConversationView:
        stripped = title.strip()
        if not stripped:
            raise ValueError("title must not be blank")
        self.get(conversation_id=conversation_id, user_id=user_id)
        return self._convs.rename(conversation_id, user_id, stripped)

    def delete(self, *, conversation_id: UUID, user_id: UUID, tenant_id: UUID) -> None:
        self.get(conversation_id=conversation_id, user_id=user_id)
        self._convs.soft_delete(conversation_id, user_id)
        self._audit.append(
            AuditEvent(
                tenant_id=tenant_id,
                actor_id=user_id,
                action="conversation.deleted",
                target_type="conversation",
                target_id=conversation_id,
            )
        )

    def set_mode(self, *, conversation_id: UUID, user_id: UUID, mode: str) -> None:
        if mode not in {"fast", "reasoning"}:
            raise ValueError("mode must be fast or reasoning")
        self.get(conversation_id=conversation_id, user_id=user_id)
        self._convs.set_mode(conversation_id, user_id, mode)

    def get_document_ids(self, *, conversation_id: UUID, user_id: UUID) -> list[UUID]:
        self.get(conversation_id=conversation_id, user_id=user_id)
        return self._convs.list_document_ids(conversation_id)

    def attach_documents(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        document_ids: tuple[UUID, ...],
    ) -> tuple[UUID, ...]:
        """Persist request-selected documents as conversation state for later follow-ups."""

        self.get(conversation_id=conversation_id, user_id=user_id)
        for document_id in dict.fromkeys(document_ids):
            self._convs.add_document(conversation_id, document_id, user_id)
        return tuple(self._convs.list_document_ids(conversation_id))

    def add_feedback(
        self,
        *,
        message_id: UUID,
        user_id: UUID,
        rating: str,
        reason: str | None,
    ) -> None:
        if rating not in {"thumbs_up", "thumbs_down"}:
            raise ValueError("rating must be thumbs_up or thumbs_down")
        self._feedback.upsert(message_id=message_id, user_id=user_id, rating=rating, reason=reason)

    # --------------------------------------------------- conversation memory

    def append_message(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        role: str,
        content: str,
        generation_trace_id: UUID | None = None,
    ) -> MessageView:
        """Persist a message with readable content for conversation memory."""
        import hashlib

        if role not in {"user", "assistant"}:
            raise ValueError("role must be user or assistant")
        if not content.strip():
            raise ValueError("message content must not be blank")
        self.get(conversation_id=conversation_id, user_id=user_id)
        content_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        return self._msgs.append(
            conversation_id=conversation_id,
            user_id=user_id,
            role=role,
            content_sha256=content_sha256,
            generation_trace_id=generation_trace_id,
            content=content,
        )

    def list_messages(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MessageView]:
        """Return messages with content for the conversation."""
        self.get(conversation_id=conversation_id, user_id=user_id)
        return self._msgs.list_recent_with_content(conversation_id, limit=limit)

    def get_recent_turns(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        limit: int = 64,
    ) -> tuple[ConversationTurn, ...]:
        """Return recent turns as domain objects for RAG memory injection."""
        self.get(conversation_id=conversation_id, user_id=user_id)
        messages = self._msgs.list_recent_with_content(conversation_id, limit=limit)
        turns: list[ConversationTurn] = []
        for msg in messages:
            if msg.content and msg.role in {"user", "assistant"}:
                turns.append(
                    ConversationTurn(role=msg.role, content=msg.content)  # type: ignore[arg-type]
                )
        return tuple(turns)


class ConversationNotFoundError(RuntimeError):
    code = "CONVERSATION_NOT_FOUND"


# ============================================================ helpers (internal)


def _get_password_hash(user: UserView) -> str:
    """Stub - real implementation returns the hash from the repository row.

    The UserView intentionally omits the hash (never in API responses).
    AuthService calls this via the repository's internal row, not UserView.
    This function is replaced by a direct repo call in the real infrastructure.
    """
    raise NotImplementedError
