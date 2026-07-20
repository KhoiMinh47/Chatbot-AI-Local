"""Unit tests for Phase 7 auth domain and application services.

These tests run CPU-only with no database or network access.
All ports are replaced by in-memory fakes.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from app.application.auth import (
    AuthService,
    ConversationNotFoundError,
    ConversationService,
    _AuditRow,
    _SessionRow,
)
from app.domain.auth import (
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
    UserRole,
    UserView,
)

_TENANT = UUID("10000000-0000-4000-8000-000000000001")
_USER_1 = uuid4()


# ================================================================ fakes


class _FakePasswordHasher:
    def hash(self, password: str) -> str:
        return f"hashed:{password}"

    def verify(self, password: str, hashed: str) -> bool:
        return hashed == f"hashed:{password}"


class _FakeTokenFactory:
    def __init__(self) -> None:
        self._store: dict[str, SessionClaims] = {}

    def create_access_token(self, claims: SessionClaims) -> str:
        token = f"access:{claims.user_id}:{claims.session_id}"
        self._store[token] = claims
        return token

    def decode_access_token(self, token: str) -> SessionClaims:
        claims = self._store.get(token)
        if claims is None:
            raise TokenInvalidError("Not found")
        return claims


class _FakeUserRepository:
    def __init__(self) -> None:
        self._by_id: dict[UUID, dict[str, Any]] = {}
        self._by_email: dict[tuple[UUID, str], UUID] = {}

    def find_by_email(self, tenant_id: UUID, email: str) -> UserView | None:
        uid = self._by_email.get((tenant_id, email))
        return self._to_view(self._by_id[uid]) if uid and uid in self._by_id else None

    def find_by_id(self, user_id: UUID) -> UserView | None:
        rec = self._by_id.get(user_id)
        return self._to_view(rec) if rec and not rec.get("deleted") else None

    def get_password_hash(self, user_id: UUID) -> str | None:
        rec = self._by_id.get(user_id)
        return rec["password_hash"] if rec else None

    def create(self, *, tenant_id, email, password_hash, display_name, role) -> UserView:
        uid = uuid4()
        now = datetime.now(UTC)
        rec = {
            "id": uid,
            "tenant_id": tenant_id,
            "email": email,
            "password_hash": password_hash,
            "display_name": display_name,
            "role": role,
            "is_verified": False,
            "created_at": now,
        }
        self._by_id[uid] = rec
        self._by_email[(tenant_id, email)] = uid
        return self._to_view(rec)

    def set_verified(self, user_id: UUID) -> None:
        self._by_id[user_id]["is_verified"] = True

    def update_password(self, user_id: UUID, password_hash: str) -> None:
        self._by_id[user_id]["password_hash"] = password_hash

    def update_role(self, user_id: UUID, role: UserRole) -> None:
        self._by_id[user_id]["role"] = role

    def soft_delete(self, user_id: UUID) -> None:
        self._by_id[user_id]["deleted"] = True

    def list_users(self, tenant_id: UUID, *, limit: int, offset: int) -> list[UserView]:
        return [
            self._to_view(r)
            for r in self._by_id.values()
            if r["tenant_id"] == tenant_id and not r.get("deleted")
        ][offset : offset + limit]

    def count_users(self, tenant_id: UUID) -> int:
        return sum(
            1 for r in self._by_id.values() if r["tenant_id"] == tenant_id and not r.get("deleted")
        )

    def _to_view(self, r: dict[str, Any]) -> UserView:
        return UserView(
            id=r["id"],
            tenant_id=r["tenant_id"],
            email=r["email"],
            display_name=r["display_name"],
            role=r["role"],
            is_verified=r["is_verified"],
            created_at=r["created_at"],
        )


class _FakeSessionRepository:
    def __init__(self) -> None:
        self._by_hash: dict[str, _SessionRow] = {}

    def create_session(self, *, user_id, token_hash, expires_at) -> UUID:
        sid = uuid4()
        self._by_hash[token_hash] = _SessionRow(
            session_id=sid,
            user_id=user_id,
            expires_at=expires_at,
            revoked_at=None,
        )
        return sid

    def find_session(self, token_hash: str) -> _SessionRow | None:
        return self._by_hash.get(token_hash)

    def revoke_session(self, session_id: UUID) -> None:
        for row in self._by_hash.values():
            if row.session_id == session_id:
                self._by_hash = {
                    k: (
                        _SessionRow(
                            session_id=v.session_id,
                            user_id=v.user_id,
                            expires_at=v.expires_at,
                            revoked_at=datetime.now(UTC),
                        )
                        if v.session_id == session_id
                        else v
                    )
                    for k, v in self._by_hash.items()
                }
                return

    def revoke_all_sessions(self, user_id: UUID) -> None:
        now = datetime.now(UTC)
        self._by_hash = {
            k: (
                _SessionRow(
                    session_id=v.session_id,
                    user_id=v.user_id,
                    expires_at=v.expires_at,
                    revoked_at=now,
                )
                if v.user_id == user_id and v.revoked_at is None
                else v
            )
            for k, v in self._by_hash.items()
        }


class _FakeVerifyRepo:
    def __init__(self) -> None:
        self._by_hash: dict[str, dict[str, Any]] = {}

    def create_token(self, *, user_id, token_hash, expires_at) -> UUID:
        tid = uuid4()
        self._by_hash[token_hash] = {
            "id": tid,
            "user_id": user_id,
            "expires_at": expires_at,
            "used_at": None,
        }
        return tid

    def consume_token(self, token_hash: str) -> UUID:
        rec = self._by_hash.get(token_hash)
        if rec is None:
            raise TokenInvalidError("Not found")
        if rec["used_at"] is not None:
            raise TokenAlreadyUsedError("Already used")
        if rec["expires_at"] <= datetime.now(UTC):
            raise TokenExpiredError("Expired")
        rec["used_at"] = datetime.now(UTC)
        return rec["user_id"]


class _FakeResetRepo(_FakeVerifyRepo):
    pass


class _FakeEmailService:
    def __init__(self) -> None:
        self.sent: list[dict[str, str]] = []

    async def send_verification(self, *, to_email: str, token: str) -> None:
        self.sent.append({"type": "verify", "to": to_email, "token": token})

    async def send_password_reset(self, *, to_email: str, token: str) -> None:
        self.sent.append({"type": "reset", "to": to_email, "token": token})


class _FakeAuditRepository:
    def __init__(self) -> None:
        self.events: list[AuditEvent] = []

    def append(self, event: AuditEvent) -> None:
        self.events.append(event)

    def list_events(self, tenant_id: UUID, *, limit: int, offset: int) -> list[_AuditRow]:
        return []


class _FakeConversationRepository:
    def __init__(self) -> None:
        self._store: dict[UUID, dict[str, Any]] = {}

    def create(self, *, tenant_id, user_id, title, mode) -> ConversationView:
        cid = uuid4()
        now = datetime.now(UTC)
        rec = {
            "id": cid,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "title": title,
            "mode": mode,
            "created_at": now,
            "updated_at": now,
            "deleted": False,
            "document_ids": [],
        }
        self._store[cid] = rec
        return self._to_view(rec)

    def find(self, conversation_id, user_id) -> ConversationView | None:
        rec = self._store.get(conversation_id)
        if rec is None or rec["deleted"] or rec["user_id"] != user_id:
            return None
        return self._to_view(rec)

    def list_by_user(self, user_id, *, limit, offset) -> list[ConversationView]:
        return [
            self._to_view(r)
            for r in self._store.values()
            if r["user_id"] == user_id and not r["deleted"]
        ][offset : offset + limit]

    def rename(self, conversation_id, user_id, title) -> ConversationView:
        self._store[conversation_id]["title"] = title
        return self._to_view(self._store[conversation_id])

    def soft_delete(self, conversation_id, user_id) -> None:
        self._store[conversation_id]["deleted"] = True

    def set_mode(self, conversation_id, user_id, mode) -> None:
        self._store[conversation_id]["mode"] = mode

    def add_document(self, conversation_id, document_id, user_id) -> None:
        del user_id
        self._store[conversation_id]["document_ids"].append(document_id)

    def remove_document(self, conversation_id, document_id) -> None:
        self._store[conversation_id]["document_ids"].remove(document_id)

    def list_document_ids(self, conversation_id) -> list[UUID]:
        return list(self._store[conversation_id]["document_ids"])

    def _to_view(self, r: dict[str, Any]) -> ConversationView:
        return ConversationView(
            id=r["id"],
            tenant_id=r["tenant_id"],
            user_id=r["user_id"],
            title=r["title"],
            mode=r["mode"],
            created_at=r["created_at"],
            updated_at=r["updated_at"],
        )


class _FakeMessageRepository:
    def __init__(self) -> None:
        self._msgs: list[MessageView] = []

    def append(
        self,
        *,
        conversation_id,
        user_id,
        role,
        content_sha256,
        generation_trace_id,
        content,
    ):
        view = MessageView(
            id=uuid4(),
            conversation_id=conversation_id,
            role=role,
            content_sha256=content_sha256,
            generation_trace_id=generation_trace_id,
            created_at=datetime.now(UTC),
            content=content,
        )
        self._msgs.append(view)
        return view

    def list_by_conversation(self, conversation_id, *, limit, offset) -> list[MessageView]:
        return [m for m in self._msgs if m.conversation_id == conversation_id][
            offset : offset + limit
        ]

    def list_recent_with_content(self, conversation_id, *, limit) -> list[MessageView]:
        return [m for m in self._msgs if m.conversation_id == conversation_id][-limit:]


class _FakeFeedbackRepository:
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def upsert(self, *, message_id, user_id, rating, reason) -> None:
        self.records.append(
            {"message_id": message_id, "user_id": user_id, "rating": rating, "reason": reason}
        )


# ================================================================ fixture


def _make_auth_service() -> tuple[AuthService, _FakeUserRepository, _FakeEmailService]:
    user_repo = _FakeUserRepository()
    email_svc = _FakeEmailService()

    import app.application.auth as auth_module

    svc = AuthService(
        password_hasher=_FakePasswordHasher(),
        token_factory=_FakeTokenFactory(),
        user_repo=user_repo,
        session_repo=_FakeSessionRepository(),
        verify_repo=_FakeVerifyRepo(),
        reset_repo=_FakeResetRepo(),
        email_svc=email_svc,
        audit_repo=_FakeAuditRepository(),
        default_tenant_id=_TENANT,
    )
    # Patch hash lookup for login
    auth_module._get_password_hash = lambda user: user_repo.get_password_hash(user.id)  # type: ignore[attr-defined]
    return svc, user_repo, email_svc


# ================================================================ tests


@pytest.mark.anyio
async def test_register_creates_user_and_sends_verify_email():
    svc, _repo, emails = _make_auth_service()
    user = await svc.register(email="alice@example.com", password="Secret123", display_name="Alice")

    assert user.email == "alice@example.com"
    assert user.display_name == "Alice"
    assert user.role == UserRole.USER
    assert not user.is_verified
    assert len(emails.sent) == 1
    assert emails.sent[0]["type"] == "verify"
    assert emails.sent[0]["to"] == "alice@example.com"


@pytest.mark.anyio
async def test_register_duplicate_email_raises():
    svc, _, _ = _make_auth_service()
    await svc.register(email="bob@example.com", password="Secret123", display_name="Bob")
    with pytest.raises(EmailAlreadyRegisteredError):
        await svc.register(email="BOB@example.com", password="Other123", display_name="Bob2")


@pytest.mark.anyio
async def test_verify_email_marks_user_verified():
    svc, _repo, emails = _make_auth_service()
    await svc.register(email="carol@example.com", password="Secret123", display_name="Carol")
    raw_token = emails.sent[0]["token"]
    user = svc.verify_email(raw_token=raw_token)
    assert user.is_verified


@pytest.mark.anyio
async def test_verify_email_second_use_raises():
    svc, _, emails = _make_auth_service()
    await svc.register(email="dave@example.com", password="Secret123", display_name="Dave")
    raw_token = emails.sent[0]["token"]
    svc.verify_email(raw_token=raw_token)
    with pytest.raises(TokenAlreadyUsedError):
        svc.verify_email(raw_token=raw_token)


@pytest.mark.anyio
async def test_login_requires_verified_account():
    svc, _, _emails = _make_auth_service()
    await svc.register(email="eve@example.com", password="Secret123", display_name="Eve")
    with pytest.raises(AccountNotVerifiedError):
        svc.login(email="eve@example.com", password="Secret123")


@pytest.mark.anyio
async def test_login_happy_path_returns_token_pair():
    svc, _, emails = _make_auth_service()
    await svc.register(email="frank@example.com", password="Secret123", display_name="Frank")
    svc.verify_email(raw_token=emails.sent[0]["token"])

    pair = svc.login(email="frank@example.com", password="Secret123")
    assert pair.access_token
    assert pair.refresh_token
    assert pair.token_type == "bearer"


@pytest.mark.anyio
async def test_login_wrong_password_raises():
    svc, _, emails = _make_auth_service()
    await svc.register(email="grace@example.com", password="Secret123", display_name="Grace")
    svc.verify_email(raw_token=emails.sent[0]["token"])

    with pytest.raises(InvalidCredentialsError):
        svc.login(email="grace@example.com", password="WrongPw!")


@pytest.mark.anyio
async def test_refresh_rotates_session():
    svc, _, emails = _make_auth_service()
    await svc.register(email="henry@example.com", password="Secret123", display_name="Henry")
    svc.verify_email(raw_token=emails.sent[0]["token"])

    pair1 = svc.login(email="henry@example.com", password="Secret123")
    pair2 = svc.refresh(raw_refresh_token=pair1.refresh_token)

    assert pair2.access_token != pair1.access_token
    assert pair2.refresh_token != pair1.refresh_token

    # Old refresh token must be revoked now
    with pytest.raises(SessionRevokedError):
        svc.refresh(raw_refresh_token=pair1.refresh_token)


@pytest.mark.anyio
async def test_forgot_password_sends_email():
    svc, _, emails = _make_auth_service()
    await svc.register(email="iris@example.com", password="Secret123", display_name="Iris")

    initial_sent = len(emails.sent)
    await svc.forgot_password(email="iris@example.com")
    assert len(emails.sent) == initial_sent + 1
    assert emails.sent[-1]["type"] == "reset"


@pytest.mark.anyio
async def test_forgot_password_unknown_email_silent():
    """Must not raise for unknown emails (anti-enumeration)."""
    svc, _, emails = _make_auth_service()
    await svc.forgot_password(email="nobody@example.com")
    assert len(emails.sent) == 0


@pytest.mark.anyio
async def test_reset_password_changes_password_and_revokes_sessions():
    svc, _repo, emails = _make_auth_service()
    await svc.register(email="jack@example.com", password="OldPass123", display_name="Jack")
    svc.verify_email(raw_token=emails.sent[0]["token"])
    pair = svc.login(email="jack@example.com", password="OldPass123")

    await svc.forgot_password(email="jack@example.com")
    reset_token = emails.sent[-1]["token"]
    svc.reset_password(raw_token=reset_token, new_password="NewPass456")

    # Old session should be revoked
    with pytest.raises(SessionRevokedError):
        svc.refresh(raw_refresh_token=pair.refresh_token)

    # New password should work
    pair2 = svc.login(email="jack@example.com", password="NewPass456")
    assert pair2.access_token


@pytest.mark.anyio
async def test_token_hash_is_sha256():
    from app.domain.auth import token_hash

    raw = "my-opaque-token"
    expected = hashlib.sha256(raw.encode()).hexdigest()
    assert token_hash(raw) == expected
    assert len(token_hash(raw)) == 64


# ================================================================ conversation tests


def _make_conv_service() -> ConversationService:
    return ConversationService(
        conv_repo=_FakeConversationRepository(),
        msg_repo=_FakeMessageRepository(),
        feedback_repo=_FakeFeedbackRepository(),
        audit_repo=_FakeAuditRepository(),
    )


def test_conversation_create_and_get():
    svc = _make_conv_service()
    uid = uuid4()
    conv = svc.create(tenant_id=_TENANT, user_id=uid, title="My Chat")
    fetched = svc.get(conversation_id=conv.id, user_id=uid)
    assert fetched.id == conv.id
    assert fetched.title == "My Chat"
    assert fetched.mode == "fast"


def test_conversation_messages_are_persisted_and_loaded_as_recent_turns():
    svc = _make_conv_service()
    uid = uuid4()
    conv = svc.create(tenant_id=_TENANT, user_id=uid, title="Memory")

    svc.append_message(
        conversation_id=conv.id,
        user_id=uid,
        role="user",
        content="Hãy dùng cấu hình A.",
    )
    svc.append_message(
        conversation_id=conv.id,
        user_id=uid,
        role="assistant",
        content="Đã ghi nhận cấu hình A.",
    )

    turns = svc.get_recent_turns(conversation_id=conv.id, user_id=uid)

    assert [turn.role for turn in turns] == ["user", "assistant"]
    assert turns[0].content == "Hãy dùng cấu hình A."


def test_conversation_rename():
    svc = _make_conv_service()
    uid = uuid4()
    conv = svc.create(tenant_id=_TENANT, user_id=uid, title="Old Title")
    renamed = svc.rename(conversation_id=conv.id, user_id=uid, title="New Title")
    assert renamed.title == "New Title"


def test_conversation_delete_removes_from_list():
    svc = _make_conv_service()
    uid = uuid4()
    conv = svc.create(tenant_id=_TENANT, user_id=uid, title="Delete Me")
    svc.delete(conversation_id=conv.id, user_id=uid, tenant_id=_TENANT)
    assert svc.list_conversations(user_id=uid) == []


def test_conversation_other_user_cannot_access():
    svc = _make_conv_service()
    uid1 = uuid4()
    uid2 = uuid4()
    conv = svc.create(tenant_id=_TENANT, user_id=uid1, title="Private")
    with pytest.raises(ConversationNotFoundError):
        svc.get(conversation_id=conv.id, user_id=uid2)


def test_conversation_invalid_mode_raises():
    svc = _make_conv_service()
    uid = uuid4()
    with pytest.raises(ValueError, match="mode"):
        svc.create(tenant_id=_TENANT, user_id=uid, title="Bad Mode", mode="turbo")


def test_feedback_upsert():
    svc = _make_conv_service()
    uid = uuid4()
    msg_id = uuid4()
    svc.add_feedback(message_id=msg_id, user_id=uid, rating="thumbs_up", reason=None)
    # Upsert again with thumbs_down
    svc.add_feedback(message_id=msg_id, user_id=uid, rating="thumbs_down", reason="Hallucinated")


def test_feedback_invalid_rating_raises():
    svc = _make_conv_service()
    with pytest.raises(ValueError, match="rating"):
        svc.add_feedback(message_id=uuid4(), user_id=uuid4(), rating="meh", reason=None)


# ================================================================ JWT tests


def test_jwt_factory_roundtrip():
    from app.infrastructure.auth import JwtTokenFactory

    factory = JwtTokenFactory(
        secret="test-secret-32-bytes-long-enough!",
        algorithm="HS256",
        expire_minutes=15,
    )
    claims = SessionClaims(
        user_id=uuid4(),
        tenant_id=_TENANT,
        email="test@example.com",
        role=UserRole.USER,
        session_id=uuid4(),
    )
    token = factory.create_access_token(claims)
    decoded = factory.decode_access_token(token)
    assert decoded.user_id == claims.user_id
    assert decoded.email == claims.email
    assert decoded.role == claims.role
    assert decoded.session_id == claims.session_id


def test_jwt_factory_invalid_token_raises():
    from app.infrastructure.auth import JwtTokenFactory

    factory = JwtTokenFactory(
        secret="test-secret-32-bytes-long-enough!",
        algorithm="HS256",
        expire_minutes=15,
    )
    with pytest.raises(TokenInvalidError):
        factory.decode_access_token("not-a-valid-token")


def test_argon2_hasher_roundtrip():
    from app.infrastructure.auth import ArgonPasswordHasher

    h = ArgonPasswordHasher()
    plain_pw = "SuperSecret123!"
    hashed = h.hash(plain_pw)
    assert h.verify(plain_pw, hashed)
    assert not h.verify("WrongInput!", hashed)


# ================================================================ security dependency tests


def test_claims_to_actor_maps_correctly():
    from app.security import claims_to_actor

    claims = SessionClaims(
        user_id=uuid4(),
        tenant_id=_TENANT,
        email="x@example.com",
        role=UserRole.USER,
        session_id=uuid4(),
    )
    actor = claims_to_actor(claims)
    assert actor.user_id == claims.user_id
    assert actor.tenant_id == claims.tenant_id
