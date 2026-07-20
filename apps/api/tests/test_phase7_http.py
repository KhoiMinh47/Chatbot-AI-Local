"""Phase 7 HTTP-level tests: auth endpoints, conversation CRUD, security gates."""

from __future__ import annotations

from unittest.mock import MagicMock
from uuid import UUID, uuid4

from app.domain.auth import SessionClaims, UserRole, UserView
from app.main import create_app
from fastapi.testclient import TestClient


def _fake_auth_bundle(user_view: UserView | None = None) -> MagicMock:
    """Return a mock auth bundle with a working token factory and auth service."""
    from datetime import UTC, datetime

    from app.infrastructure.auth import JwtTokenFactory

    uid = uuid4()
    tenant_id = UUID("10000000-0000-4000-8000-000000000001")
    if user_view is None:
        user_view = UserView(
            id=uid,
            tenant_id=tenant_id,
            email="alice@example.com",
            display_name="Alice",
            role=UserRole.USER,
            is_verified=True,
            created_at=datetime.now(UTC),
        )

    factory = JwtTokenFactory(
        secret="test-secret-that-is-at-least-32-chars!",
        algorithm="HS256",
        expire_minutes=15,
    )
    claims = SessionClaims(
        user_id=user_view.id,
        tenant_id=user_view.tenant_id,
        email=user_view.email,
        role=user_view.role,
        session_id=uuid4(),
    )
    token = factory.create_access_token(claims)

    mock_svc = MagicMock()
    mock_svc._tokens = factory
    mock_svc.get_me.return_value = user_view

    # Use a plain class so .close() exists without MagicMock noise
    class _Bundle:
        auth_service = mock_svc
        conversation_service = MagicMock()

        def close(self) -> None:
            pass

    return _Bundle(), token, claims


def _app_with_auth(user_view=None):
    bundle, token, claims = _fake_auth_bundle(user_view)
    application = create_app(_override_auth_bundle=bundle)
    return application, token, claims


# ================================================================ auth endpoint tests


def test_health_live_returns_200_without_auth():
    app = create_app()
    with TestClient(app) as client:
        resp = client.get("/health/live")
    assert resp.status_code == 200


def test_get_me_requires_bearer_token():
    app = create_app()
    with TestClient(app) as client:
        # Auth not configured → 503
        resp = client.get("/api/v1/auth/me")
    assert resp.status_code in {401, 503}


def test_get_me_with_valid_token():
    app, token, _claims = _app_with_auth()
    with TestClient(app) as client:
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == "alice@example.com"
    assert data["role"] == "user"


def test_get_me_with_invalid_token_returns_401():
    app, _token, _ = _app_with_auth()
    with TestClient(app) as client:
        resp = client.get(
            "/api/v1/auth/me",
            headers={"Authorization": "Bearer not-a-valid-jwt"},
        )
    assert resp.status_code == 401


def test_admin_endpoint_blocked_for_regular_user():
    app, token, _ = _app_with_auth()
    with TestClient(app) as client:
        resp = client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 403


def test_admin_endpoint_accessible_for_admin():
    from datetime import UTC, datetime

    uid = uuid4()
    admin_view = UserView(
        id=uid,
        tenant_id=UUID("10000000-0000-4000-8000-000000000001"),
        email="admin@example.com",
        display_name="Admin",
        role=UserRole.ADMIN,
        is_verified=True,
        created_at=datetime.now(UTC),
    )
    app, token, _ = _app_with_auth(admin_view)

    # Stub list_users on the pre-built mock bundle
    # We need to get the bundle from the factory, so re-fetch after entering TestClient:
    with TestClient(app) as client:
        # After lifespan, app.state.auth_bundle is the _override
        app.state.auth_bundle.auth_service._users.list_users.return_value = []
        resp = client.get(
            "/api/v1/admin/users",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    assert resp.json() == []


def test_login_endpoint_delegates_to_auth_service():
    from app.domain.auth import TokenPair

    bundle, _token, _claims = _fake_auth_bundle()
    bundle.auth_service.login.return_value = TokenPair(
        access_token="access-tok",
        refresh_token="refresh-tok",
        token_type="bearer",
        expires_in=900,
    )
    app = create_app(_override_auth_bundle=bundle)
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/auth/login",
            json={"email": "alice@example.com", "password": "Secret123"},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] == "access-tok"
    assert body["token_type"] == "bearer"


def test_conversation_create_requires_auth():
    app = create_app()
    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/conversations",
            json={"title": "My Conversation"},
        )
    assert resp.status_code in {401, 503}


def test_conversation_crud_with_auth():
    from datetime import UTC, datetime

    from app.domain.auth import ConversationView

    # Build the bundle before creating the app so mock is configured at lifespan start
    bundle, token, claims = _fake_auth_bundle()
    now = datetime.now(UTC)
    conv_view = ConversationView(
        id=uuid4(),
        tenant_id=claims.tenant_id,
        user_id=claims.user_id,
        title="Test Chat",
        mode="fast",
        created_at=now,
        updated_at=now,
    )
    bundle.conversation_service.create.return_value = conv_view
    app = create_app(_override_auth_bundle=bundle)

    with TestClient(app) as client:
        resp = client.post(
            "/api/v1/conversations",
            json={"title": "Test Chat"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 201
    data = resp.json()
    assert data["title"] == "Test Chat"
    assert data["mode"] == "fast"


def test_logout_requires_auth():
    app = create_app()
    with TestClient(app) as client:
        resp = client.post("/api/v1/auth/logout")
    assert resp.status_code in {401, 503}


def test_admin_stats_endpoint_requires_admin():
    app, token, _ = _app_with_auth()
    with TestClient(app) as client:
        resp = client.get(
            "/api/v1/admin/stats",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 403


def test_admin_stats_endpoint_for_admin():
    from datetime import UTC, datetime

    uid = uuid4()
    admin_view = UserView(
        id=uid,
        tenant_id=UUID("10000000-0000-4000-8000-000000000001"),
        email="admin@example.com",
        display_name="Admin",
        role=UserRole.ADMIN,
        is_verified=True,
        created_at=datetime.now(UTC),
    )
    app, token, _ = _app_with_auth(admin_view)

    with TestClient(app) as client:
        # Mock the repository calls
        app.state.auth_bundle.auth_service._users.count_users.return_value = 5
        resp = client.get(
            "/api/v1/admin/stats",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert data["users_count"] == 5
    assert "documents_count" in data


def test_admin_config_endpoint_for_admin():
    from datetime import UTC, datetime

    uid = uuid4()
    admin_view = UserView(
        id=uid,
        tenant_id=UUID("10000000-0000-4000-8000-000000000001"),
        email="admin@example.com",
        display_name="Admin",
        role=UserRole.ADMIN,
        is_verified=True,
        created_at=datetime.now(UTC),
    )
    app, token, _ = _app_with_auth(admin_view)

    with TestClient(app) as client:
        resp = client.get(
            "/api/v1/admin/config",
            headers={"Authorization": f"Bearer {token}"},
        )
    assert resp.status_code == 200
    data = resp.json()
    assert "nim_clients_enabled" in data
    assert "llm_model" in data
    assert "prompt_sha256" in data
