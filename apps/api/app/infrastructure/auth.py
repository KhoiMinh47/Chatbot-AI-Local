"""Phase 7 auth infrastructure: Argon2id hasher, JWT factory, PostgreSQL repos, SMTP."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast
from uuid import UUID, uuid4

import jwt
from argon2 import PasswordHasher as Argon2Hasher
from argon2.exceptions import VerifyMismatchError
from sqlalchemy import URL, Engine, create_engine, text

from app.application.auth import (
    AuthService,
    ConversationService,
    _AuditRow,
    _SessionRow,
)
from app.domain.auth import (
    AuditEvent,
    ConversationView,
    MessageView,
    SessionClaims,
    TokenAlreadyUsedError,
    TokenExpiredError,
    TokenInvalidError,
    UserRole,
    UserView,
)
from app.infrastructure.auth_settings import AuthSettings

_log = logging.getLogger(__name__)


# ============================================================ password hasher


class ArgonPasswordHasher:
    """Argon2id hasher with OWASP-recommended parameters."""

    def __init__(self) -> None:
        self._hasher = Argon2Hasher(
            time_cost=3,
            memory_cost=65536,
            parallelism=4,
        )

    def hash(self, password: str) -> str:
        return self._hasher.hash(password)

    def verify(self, password: str, hashed: str) -> bool:
        try:
            self._hasher.verify(hashed, password)
            return True
        except VerifyMismatchError:
            return False
        except Exception:
            return False


# ============================================================= JWT factory


class JwtTokenFactory:
    """HS256 JWT factory; never stores secrets beyond the call boundary."""

    def __init__(self, *, secret: str, algorithm: str, expire_minutes: int) -> None:
        if not secret.strip():
            raise ValueError("JWT secret must not be blank")
        self._secret = secret
        self._algorithm = algorithm
        self._expire_minutes = expire_minutes

    def create_access_token(self, claims: SessionClaims) -> str:
        from datetime import timedelta

        now = datetime.now(UTC)
        payload = {
            "sub": str(claims.user_id),
            "tid": str(claims.tenant_id),
            "email": claims.email,
            "role": claims.role.value,
            "sid": str(claims.session_id),
            "iat": now,
            "exp": now + timedelta(minutes=self._expire_minutes),
        }
        return jwt.encode(payload, self._secret, algorithm=self._algorithm)

    def decode_access_token(self, token: str) -> SessionClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[self._algorithm],
                options={"require": ["sub", "tid", "email", "role", "sid", "exp"]},
            )
        except jwt.ExpiredSignatureError as e:
            raise TokenExpiredError("Access token has expired.") from e
        except jwt.InvalidTokenError as e:
            raise TokenInvalidError("Access token is invalid.") from e
        return SessionClaims(
            user_id=UUID(payload["sub"]),
            tenant_id=UUID(payload["tid"]),
            email=payload["email"],
            role=UserRole(payload["role"]),
            session_id=UUID(payload["sid"]),
        )


# ============================================================ PostgreSQL repos


def _build_engine(settings: AuthSettings) -> Engine:
    if settings.database_host is None:
        raise ValueError("AUTH_DATABASE_HOST is required when auth is enabled")
    pw = settings.database_password.get_secret_value() if settings.database_password else ""
    url = URL.create(
        "postgresql+psycopg",
        username=settings.database_user,
        password=pw,
        host=settings.database_host,
        port=settings.database_port,
        database=settings.database_name,
    )
    return create_engine(
        url,
        pool_size=5,
        max_overflow=10,
        pool_pre_ping=True,
        connect_args={"options": "-csearch_path=app,public"},
    )


def _row(r: Any) -> Mapping[str, Any]:
    return cast(Mapping[str, Any], r)


class PostgresUserRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def _to_view(self, r: Mapping[str, Any]) -> UserView:
        return UserView(
            id=cast(UUID, r["id"]),
            tenant_id=cast(UUID, r["tenant_id"]),
            email=cast(str, r["email"]),
            display_name=cast(str, r["display_name"]),
            role=UserRole(cast(str, r["role"])),
            is_verified=cast(bool, r["is_verified"]),
            created_at=cast(datetime, r["created_at"]),
        )

    def find_by_email(self, tenant_id: UUID, email: str) -> UserView | None:
        with self._engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT id,tenant_id,email,display_name,role,is_verified,created_at"
                        " FROM users WHERE tenant_id=:tid AND email=:email AND deleted_at IS NULL"
                    ),
                    {"tid": tenant_id, "email": email},
                )
                .mappings()
                .first()
            )
        return self._to_view(_row(row)) if row else None

    def find_by_id(self, user_id: UUID) -> UserView | None:
        with self._engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT id,tenant_id,email,display_name,role,is_verified,created_at"
                        " FROM users WHERE id=:uid AND deleted_at IS NULL"
                    ),
                    {"uid": user_id},
                )
                .mappings()
                .first()
            )
        return self._to_view(_row(row)) if row else None

    def get_password_hash(self, user_id: UUID) -> str | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT password_hash FROM users WHERE id=:uid AND deleted_at IS NULL"),
                {"uid": user_id},
            ).first()
        return cast(str, row[0]) if row else None

    def create(
        self,
        *,
        tenant_id: UUID,
        email: str,
        password_hash: str,
        display_name: str,
        role: UserRole,
    ) -> UserView:
        uid = uuid4()
        now = datetime.now(UTC)
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO users(id,tenant_id,email,password_hash,display_name,role,"
                    "is_verified,created_at,updated_at)"
                    " VALUES(:id,:tid,:email,:pw,:name,:role,false,:now,:now)"
                ),
                {
                    "id": uid,
                    "tid": tenant_id,
                    "email": email,
                    "pw": password_hash,
                    "name": display_name,
                    "role": role.value,
                    "now": now,
                },
            )
        return UserView(
            id=uid,
            tenant_id=tenant_id,
            email=email,
            display_name=display_name,
            role=role,
            is_verified=False,
            created_at=now,
        )

    def set_verified(self, user_id: UUID) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("UPDATE users SET is_verified=true, updated_at=:now WHERE id=:uid"),
                {"uid": user_id, "now": datetime.now(UTC)},
            )

    def update_password(self, user_id: UUID, password_hash: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("UPDATE users SET password_hash=:pw, updated_at=:now WHERE id=:uid"),
                {"uid": user_id, "pw": password_hash, "now": datetime.now(UTC)},
            )

    def update_role(self, user_id: UUID, role: UserRole) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text("UPDATE users SET role=:role, updated_at=:now WHERE id=:uid"),
                {"uid": user_id, "role": role.value, "now": datetime.now(UTC)},
            )

    def soft_delete(self, user_id: UUID) -> None:
        now = datetime.now(UTC)
        with self._engine.begin() as conn:
            conn.execute(
                text("UPDATE users SET deleted_at=:now, updated_at=:now WHERE id=:uid"),
                {"uid": user_id, "now": now},
            )

    def list_users(self, tenant_id: UUID, *, limit: int, offset: int) -> list[UserView]:
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT id,tenant_id,email,display_name,role,is_verified,created_at"
                        " FROM users WHERE tenant_id=:tid AND deleted_at IS NULL"
                        " ORDER BY created_at DESC LIMIT :lim OFFSET :off"
                    ),
                    {"tid": tenant_id, "lim": limit, "off": offset},
                )
                .mappings()
                .all()
            )
        return [self._to_view(_row(r)) for r in rows]

    def count_users(self, tenant_id: UUID) -> int:
        with self._engine.connect() as conn:
            row = conn.execute(
                text("SELECT COUNT(*) FROM users WHERE tenant_id=:tid AND deleted_at IS NULL"),
                {"tid": tenant_id},
            ).first()
        return cast(int, row[0]) if row else 0


class PostgresSessionRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_session(self, *, user_id: UUID, token_hash: str, expires_at: datetime) -> UUID:
        sid = uuid4()
        now = datetime.now(UTC)
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO refresh_sessions(id,user_id,token_hash,created_at,expires_at)"
                    " VALUES(:id,:uid,:hash,:now,:exp)"
                ),
                {"id": sid, "uid": user_id, "hash": token_hash, "now": now, "exp": expires_at},
            )
        return sid

    def find_session(self, token_hash: str) -> _SessionRow | None:
        with self._engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT id,user_id,expires_at,revoked_at"
                        " FROM refresh_sessions WHERE token_hash=:hash"
                    ),
                    {"hash": token_hash},
                )
                .mappings()
                .first()
            )
        if row is None:
            return None
        return _SessionRow(
            session_id=cast(UUID, row["id"]),
            user_id=cast(UUID, row["user_id"]),
            expires_at=cast(datetime, row["expires_at"]),
            revoked_at=cast(datetime | None, row["revoked_at"]),
        )

    def revoke_session(self, session_id: UUID) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE refresh_sessions SET revoked_at=:now"
                    " WHERE id=:sid AND revoked_at IS NULL"
                ),
                {"sid": session_id, "now": datetime.now(UTC)},
            )

    def revoke_all_sessions(self, user_id: UUID) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE refresh_sessions SET revoked_at=:now"
                    " WHERE user_id=:uid AND revoked_at IS NULL"
                ),
                {"uid": user_id, "now": datetime.now(UTC)},
            )


class PostgresVerificationTokenRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_token(self, *, user_id: UUID, token_hash: str, expires_at: datetime) -> UUID:
        tid = uuid4()
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO email_verification_tokens(id,user_id,token_hash,"
                    "created_at,expires_at)"
                    " VALUES(:id,:uid,:hash,:now,:exp)"
                ),
                {
                    "id": tid,
                    "uid": user_id,
                    "hash": token_hash,
                    "now": datetime.now(UTC),
                    "exp": expires_at,
                },
            )
        return tid

    def consume_token(self, token_hash: str) -> UUID:
        with self._engine.begin() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT id,user_id,expires_at,used_at"
                        " FROM email_verification_tokens WHERE token_hash=:hash"
                    ),
                    {"hash": token_hash},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise TokenInvalidError("Token not found.")
            if row["used_at"] is not None:
                raise TokenAlreadyUsedError("Token already used.")
            if cast(datetime, row["expires_at"]) <= datetime.now(UTC):
                raise TokenExpiredError("Token has expired.")
            conn.execute(
                text("UPDATE email_verification_tokens SET used_at=:now WHERE id=:tid"),
                {"tid": row["id"], "now": datetime.now(UTC)},
            )
        return cast(UUID, row["user_id"])


class PostgresPasswordResetTokenRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def create_token(self, *, user_id: UUID, token_hash: str, expires_at: datetime) -> UUID:
        tid = uuid4()
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO password_reset_tokens(id,user_id,token_hash,created_at,expires_at)"
                    " VALUES(:id,:uid,:hash,:now,:exp)"
                ),
                {
                    "id": tid,
                    "uid": user_id,
                    "hash": token_hash,
                    "now": datetime.now(UTC),
                    "exp": expires_at,
                },
            )
        return tid

    def consume_token(self, token_hash: str) -> UUID:
        with self._engine.begin() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT id,user_id,expires_at,used_at"
                        " FROM password_reset_tokens WHERE token_hash=:hash"
                    ),
                    {"hash": token_hash},
                )
                .mappings()
                .first()
            )
            if row is None:
                raise TokenInvalidError("Token not found.")
            if row["used_at"] is not None:
                raise TokenAlreadyUsedError("Token already used.")
            if cast(datetime, row["expires_at"]) <= datetime.now(UTC):
                raise TokenExpiredError("Token has expired.")
            conn.execute(
                text("UPDATE password_reset_tokens SET used_at=:now WHERE id=:tid"),
                {"tid": row["id"], "now": datetime.now(UTC)},
            )
        return cast(UUID, row["user_id"])


class PostgresAuditRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append(self, event: AuditEvent) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO audit_logs(id,tenant_id,actor_id,action,target_type,"
                    "target_id,request_id,created_at)"
                    " VALUES(:id,:tid,:aid,:action,:ttype,:tid2,:rid,:now)"
                ),
                {
                    "id": uuid4(),
                    "tid": event.tenant_id,
                    "aid": event.actor_id,
                    "action": event.action,
                    "ttype": event.target_type,
                    "tid2": event.target_id,
                    "rid": event.request_id,
                    "now": datetime.now(UTC),
                },
            )

    def list_events(self, tenant_id: UUID, *, limit: int, offset: int) -> list[_AuditRow]:
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT id,tenant_id,actor_id,action,"
                        "target_type,target_id,request_id,created_at"
                        " FROM audit_logs WHERE tenant_id=:tid"
                        " ORDER BY created_at DESC LIMIT :lim OFFSET :off"
                    ),
                    {"tid": tenant_id, "lim": limit, "off": offset},
                )
                .mappings()
                .all()
            )
        return [
            _AuditRow(
                id=cast(UUID, r["id"]),
                tenant_id=cast(UUID, r["tenant_id"]),
                actor_id=cast(UUID, r["actor_id"]),
                action=cast(str, r["action"]),
                target_type=cast(str | None, r["target_type"]),
                target_id=cast(UUID | None, r["target_id"]),
                request_id=cast(UUID | None, r["request_id"]),
                created_at=cast(datetime, r["created_at"]),
            )
            for r in rows
        ]


class PostgresConversationRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def _to_view(self, r: Mapping[str, Any]) -> ConversationView:
        return ConversationView(
            id=cast(UUID, r["id"]),
            tenant_id=cast(UUID, r["tenant_id"]),
            user_id=cast(UUID, r["user_id"]),
            title=cast(str, r["title"]),
            mode=cast(str, r["mode"]),
            created_at=cast(datetime, r["created_at"]),
            updated_at=cast(datetime, r["updated_at"]),
        )

    def create(self, *, tenant_id: UUID, user_id: UUID, title: str, mode: str) -> ConversationView:
        cid = uuid4()
        now = datetime.now(UTC)
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO conversations(id,tenant_id,user_id,"
                    "title,mode,created_at,updated_at)"
                    " VALUES(:id,:tid,:uid,:title,:mode,:now,:now)"
                ),
                {
                    "id": cid,
                    "tid": tenant_id,
                    "uid": user_id,
                    "title": title,
                    "mode": mode,
                    "now": now,
                },
            )
        return ConversationView(
            id=cid,
            tenant_id=tenant_id,
            user_id=user_id,
            title=title,
            mode=mode,
            created_at=now,
            updated_at=now,
        )

    def find(self, conversation_id: UUID, user_id: UUID) -> ConversationView | None:
        with self._engine.connect() as conn:
            row = (
                conn.execute(
                    text(
                        "SELECT id,tenant_id,user_id,title,mode,created_at,updated_at"
                        " FROM conversations"
                        " WHERE id=:cid AND user_id=:uid AND deleted_at IS NULL"
                    ),
                    {"cid": conversation_id, "uid": user_id},
                )
                .mappings()
                .first()
            )
        return self._to_view(_row(row)) if row else None

    def list_by_user(self, user_id: UUID, *, limit: int, offset: int) -> list[ConversationView]:
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT id,tenant_id,user_id,title,mode,created_at,updated_at"
                        " FROM conversations"
                        " WHERE user_id=:uid AND deleted_at IS NULL"
                        " ORDER BY updated_at DESC LIMIT :lim OFFSET :off"
                    ),
                    {"uid": user_id, "lim": limit, "off": offset},
                )
                .mappings()
                .all()
            )
        return [self._to_view(_row(r)) for r in rows]

    def rename(self, conversation_id: UUID, user_id: UUID, title: str) -> ConversationView:
        now = datetime.now(UTC)
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE conversations SET title=:title, updated_at=:now"
                    " WHERE id=:cid AND user_id=:uid AND deleted_at IS NULL"
                ),
                {"cid": conversation_id, "uid": user_id, "title": title, "now": now},
            )
        result = self.find(conversation_id, user_id)
        if result is None:
            from app.application.auth import ConversationNotFoundError

            raise ConversationNotFoundError(str(conversation_id))
        return result

    def soft_delete(self, conversation_id: UUID, user_id: UUID) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE conversations SET deleted_at=:now, updated_at=:now"
                    " WHERE id=:cid AND user_id=:uid AND deleted_at IS NULL"
                ),
                {"cid": conversation_id, "uid": user_id, "now": datetime.now(UTC)},
            )

    def set_mode(self, conversation_id: UUID, user_id: UUID, mode: str) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE conversations SET mode=:mode, updated_at=:now"
                    " WHERE id=:cid AND user_id=:uid AND deleted_at IS NULL"
                ),
                {"cid": conversation_id, "uid": user_id, "mode": mode, "now": datetime.now(UTC)},
            )

    def add_document(self, conversation_id: UUID, document_id: UUID, user_id: UUID) -> None:
        with self._engine.begin() as conn:
            result = conn.execute(
                text(
                    "INSERT INTO conversation_documents(conversation_id,document_id)"
                    " SELECT c.id,d.id FROM conversations AS c JOIN documents AS d"
                    " ON d.id=:did AND d.tenant_id=c.tenant_id AND d.deleted_at IS NULL"
                    " WHERE c.id=:cid AND c.user_id=:uid AND c.deleted_at IS NULL"
                    " AND (d.owner_id=:uid OR EXISTS (SELECT 1 FROM document_acls AS a"
                    " WHERE a.document_id=d.id AND a.principal_id=:uid"
                    " AND a.principal_type='user' AND a.permission IN ('read','write','admin')))"
                    " ON CONFLICT DO NOTHING"
                ),
                {"cid": conversation_id, "did": document_id, "uid": user_id},
            )
        if result.rowcount == 0:
            # A duplicate is valid; an inaccessible/non-existent document is not.
            existing = self.list_document_ids(conversation_id)
            if document_id not in existing:
                raise ValueError("document is not accessible to this conversation")

    def remove_document(self, conversation_id: UUID, document_id: UUID) -> None:
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "DELETE FROM conversation_documents"
                    " WHERE conversation_id=:cid AND document_id=:did"
                ),
                {"cid": conversation_id, "did": document_id},
            )

    def list_document_ids(self, conversation_id: UUID) -> list[UUID]:
        with self._engine.connect() as conn:
            rows = conn.execute(
                text("SELECT document_id FROM conversation_documents WHERE conversation_id=:cid"),
                {"cid": conversation_id},
            ).all()
        return [cast(UUID, r[0]) for r in rows]


class PostgresMessageRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def append(
        self,
        *,
        conversation_id: UUID,
        user_id: UUID,
        role: str,
        content_sha256: str,
        generation_trace_id: UUID | None,
        content: str,
    ) -> MessageView:
        mid = uuid4()
        now = datetime.now(UTC)
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO messages(id,conversation_id,user_id,role,"
                    "content_sha256,generation_trace_id,content,created_at)"
                    " VALUES(:id,:cid,:uid,:role,:hash,:gtid,:content,:now)"
                ),
                {
                    "id": mid,
                    "cid": conversation_id,
                    "uid": user_id,
                    "role": role,
                    "hash": content_sha256,
                    "gtid": generation_trace_id,
                    "content": content,
                    "now": now,
                },
            )
        return MessageView(
            id=mid,
            conversation_id=conversation_id,
            role=role,
            content_sha256=content_sha256,
            generation_trace_id=generation_trace_id,
            created_at=now,
            content=content,
        )

    def list_by_conversation(
        self, conversation_id: UUID, *, limit: int, offset: int
    ) -> list[MessageView]:
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT id,conversation_id,role,"
                        "content_sha256,generation_trace_id,content,created_at"
                        " FROM messages WHERE conversation_id=:cid"
                        " ORDER BY created_at ASC LIMIT :lim OFFSET :off"
                    ),
                    {"cid": conversation_id, "lim": limit, "off": offset},
                )
                .mappings()
                .all()
            )
        return [
            MessageView(
                id=cast(UUID, r["id"]),
                conversation_id=cast(UUID, r["conversation_id"]),
                role=cast(str, r["role"]),
                content_sha256=cast(str, r["content_sha256"]),
                generation_trace_id=cast(UUID | None, r["generation_trace_id"]),
                created_at=cast(datetime, r["created_at"]),
                content=cast(str | None, r.get("content")),
            )
            for r in rows
        ]

    def list_recent_with_content(self, conversation_id: UUID, *, limit: int) -> list[MessageView]:
        """Return the most recent messages with content, in chronological order."""
        with self._engine.connect() as conn:
            rows = (
                conn.execute(
                    text(
                        "SELECT id,conversation_id,role,"
                        "content_sha256,generation_trace_id,content,created_at"
                        " FROM messages WHERE conversation_id=:cid"
                        " AND content IS NOT NULL"
                        " ORDER BY created_at DESC LIMIT :lim"
                    ),
                    {"cid": conversation_id, "lim": limit},
                )
                .mappings()
                .all()
            )
        # Reverse to chronological order (oldest first)
        return [
            MessageView(
                id=cast(UUID, r["id"]),
                conversation_id=cast(UUID, r["conversation_id"]),
                role=cast(str, r["role"]),
                content_sha256=cast(str, r["content_sha256"]),
                generation_trace_id=cast(UUID | None, r["generation_trace_id"]),
                created_at=cast(datetime, r["created_at"]),
                content=cast(str | None, r.get("content")),
            )
            for r in reversed(rows)
        ]


class PostgresFeedbackRepository:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def upsert(self, *, message_id: UUID, user_id: UUID, rating: str, reason: str | None) -> None:
        uid = uuid4()
        now = datetime.now(UTC)
        with self._engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO feedback(id,message_id,user_id,rating,reason,created_at)"
                    " VALUES(:id,:mid,:uid,:rating,:reason,:now)"
                    " ON CONFLICT (message_id,user_id)"
                    " DO UPDATE SET rating=EXCLUDED.rating, reason=EXCLUDED.reason"
                ),
                {
                    "id": uid,
                    "mid": message_id,
                    "uid": user_id,
                    "rating": rating,
                    "reason": reason,
                    "now": now,
                },
            )


# ============================================================= SMTP email service


class SmtpEmailService:
    """Send HTML verification and password-reset emails via SMTP."""

    def __init__(self, settings: AuthSettings) -> None:
        self._settings = settings

    async def send_verification(self, *, to_email: str, token: str) -> None:
        url = f"{self._settings.frontend_base_url}/verify-email?token={token}"
        subject = "Verify your NTC RAG account"
        body = f"Click to verify your email:\n\n{url}\n\nThis link expires in 24 hours."
        await self._send(to=to_email, subject=subject, body=body)

    async def send_password_reset(self, *, to_email: str, token: str) -> None:
        url = f"{self._settings.frontend_base_url}/reset-password?token={token}"
        subject = "Reset your NTC RAG password"
        body = f"Click to reset your password:\n\n{url}\n\nThis link expires in 30 minutes."
        await self._send(to=to_email, subject=subject, body=body)

    async def _send(self, *, to: str, subject: str, body: str) -> None:
        try:
            from email.message import EmailMessage

            import aiosmtplib

            msg = EmailMessage()
            msg["From"] = f"{self._settings.smtp_from_name} <{self._settings.smtp_from_email}>"
            msg["To"] = to
            msg["Subject"] = subject
            msg.set_content(body)

            await aiosmtplib.send(
                msg,
                hostname=self._settings.smtp_host,
                port=self._settings.smtp_port,
                use_tls=self._settings.smtp_use_tls,
                username=self._settings.smtp_username,
                password=(
                    self._settings.smtp_password.get_secret_value()
                    if self._settings.smtp_password
                    else None
                ),
            )
        except Exception:
            _log.warning("Failed to send email to %s", to, exc_info=True)


# ============================================================= factory


@dataclass(frozen=True, slots=True)
class AuthBundle:
    """Process-lifetime auth infrastructure. Close via close()."""

    auth_service: AuthService
    conversation_service: ConversationService
    engine: Engine

    def close(self) -> None:
        self.engine.dispose()


def build_auth_bundle(settings: AuthSettings) -> AuthBundle:
    """Construct and wire all auth infrastructure from typed settings."""

    from app.application.auth import AuthService, ConversationService

    engine = _build_engine(settings)
    user_repo = PostgresUserRepository(engine)
    session_repo = PostgresSessionRepository(engine)
    verify_repo = PostgresVerificationTokenRepository(engine)
    reset_repo = PostgresPasswordResetTokenRepository(engine)
    audit_repo = PostgresAuditRepository(engine)
    conv_repo = PostgresConversationRepository(engine)
    msg_repo = PostgresMessageRepository(engine)
    feedback_repo = PostgresFeedbackRepository(engine)

    hasher = ArgonPasswordHasher()
    token_factory = JwtTokenFactory(
        secret=settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
        expire_minutes=settings.access_token_expire_minutes,
    )
    email_svc = SmtpEmailService(settings)

    auth_svc = AuthService(
        password_hasher=hasher,
        token_factory=token_factory,
        user_repo=user_repo,
        session_repo=session_repo,
        verify_repo=verify_repo,
        reset_repo=reset_repo,
        email_svc=email_svc,
        audit_repo=audit_repo,
        default_tenant_id=settings.default_tenant_id,
    )

    # Patch the _get_password_hash helper to use the real repo
    import app.application.auth as auth_module

    def _real_hash_lookup(user: UserView) -> str:
        result = user_repo.get_password_hash(user.id)
        if result is None:
            from app.domain.auth import InvalidCredentialsError

            raise InvalidCredentialsError("User not found.")
        return result

    auth_module._get_password_hash = _real_hash_lookup

    conv_svc = ConversationService(
        conv_repo=conv_repo,
        msg_repo=msg_repo,
        feedback_repo=feedback_repo,
        audit_repo=audit_repo,
    )

    return AuthBundle(
        auth_service=auth_svc,
        conversation_service=conv_svc,
        engine=engine,
    )
