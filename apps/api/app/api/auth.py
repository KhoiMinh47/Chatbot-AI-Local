"""Phase 7 authentication endpoints."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field, field_validator

from app.application.auth import (
    AccountDisabledError,
    AccountNotVerifiedError,
    AuthService,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    SessionClaims,
    SessionRevokedError,
    TokenAlreadyUsedError,
    TokenExpiredError,
    TokenInvalidError,
    TokenPair,
    UserView,
)
from app.security import get_current_claims
from app.security.limiter import limiter

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# Minimum password length enforced at HTTP boundary only
_MIN_PASSWORD = 8

# Base type for auth error mapping
_AuthError = (
    AccountDisabledError,
    AccountNotVerifiedError,
    EmailAlreadyRegisteredError,
    InvalidCredentialsError,
    SessionRevokedError,
    TokenAlreadyUsedError,
    TokenExpiredError,
    TokenInvalidError,
)


def _auth_svc(request: Request) -> AuthService:
    bundle = getattr(request.app.state, "auth_bundle", None)
    if bundle is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "AUTH_UNAVAILABLE", "message": "Auth is not configured."},
        )
    return cast(AuthService, getattr(bundle, "auth_service", None))


def _map_auth_error(exc: Exception) -> HTTPException:
    code = getattr(exc, "code", "AUTH_ERROR")
    mapping = {
        "EMAIL_ALREADY_REGISTERED": status.HTTP_409_CONFLICT,
        "INVALID_CREDENTIALS": status.HTTP_401_UNAUTHORIZED,
        "ACCOUNT_NOT_VERIFIED": status.HTTP_403_FORBIDDEN,
        "ACCOUNT_DISABLED": status.HTTP_403_FORBIDDEN,
        "TOKEN_EXPIRED": status.HTTP_401_UNAUTHORIZED,
        "TOKEN_ALREADY_USED": status.HTTP_410_GONE,
        "TOKEN_INVALID": status.HTTP_400_BAD_REQUEST,
        "SESSION_REVOKED": status.HTTP_401_UNAUTHORIZED,
    }
    http_status = mapping.get(code, status.HTTP_400_BAD_REQUEST)
    return HTTPException(
        status_code=http_status,
        detail={"code": code, "message": str(exc)},
    )


# ----------------------------------------------------------------- schemas


class RegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=_MIN_PASSWORD, max_length=128)
    display_name: str = Field(min_length=1, max_length=128)

    @field_validator("email")
    @classmethod
    def email_has_at(cls, v: str) -> str:
        if "@" not in v:
            raise ValueError("Invalid email address")
        return v.strip().lower()


class VerifyEmailRequest(BaseModel):
    token: str = Field(min_length=8, max_length=512)


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=8, max_length=512)


class ForgotPasswordRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)


class ResetPasswordRequest(BaseModel):
    token: str = Field(min_length=8, max_length=512)
    new_password: str = Field(min_length=_MIN_PASSWORD, max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str
    expires_in: int


class UserResponse(BaseModel):
    id: str
    tenant_id: str
    email: str
    display_name: str
    role: str
    is_verified: bool


def _user_response(u: UserView) -> UserResponse:
    return UserResponse(
        id=str(u.id),
        tenant_id=str(u.tenant_id),
        email=u.email,
        display_name=u.display_name,
        role=u.role.value,
        is_verified=u.is_verified,
    )


def _token_response(pair: TokenPair) -> TokenResponse:
    return TokenResponse(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        token_type=pair.token_type,
        expires_in=pair.expires_in,
    )


# ------------------------------------------------------------------ endpoints


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
@limiter.limit("5/minute")
async def register(body: RegisterRequest, request: Request) -> UserResponse:
    svc = _auth_svc(request)
    try:
        user = await svc.register(
            email=body.email,
            password=body.password,
            display_name=body.display_name,
        )
    except Exception as exc:
        raise _map_auth_error(exc) from exc
    return _user_response(user)


@router.post("/verify-email", response_model=UserResponse)
def verify_email(body: VerifyEmailRequest, request: Request) -> UserResponse:
    svc = _auth_svc(request)
    try:
        user = svc.verify_email(raw_token=body.token)
    except Exception as exc:
        raise _map_auth_error(exc) from exc
    return _user_response(user)


@router.post("/login", response_model=TokenResponse)
@limiter.limit("5/minute")
def login(body: LoginRequest, request: Request) -> TokenResponse:
    svc = _auth_svc(request)
    try:
        pair = svc.login(email=body.email, password=body.password)
    except Exception as exc:
        raise _map_auth_error(exc) from exc
    return _token_response(pair)


@router.post("/refresh", response_model=TokenResponse)
def refresh(body: RefreshRequest, request: Request) -> TokenResponse:
    svc = _auth_svc(request)
    try:
        pair = svc.refresh(raw_refresh_token=body.refresh_token)
    except Exception as exc:
        raise _map_auth_error(exc) from exc
    return _token_response(pair)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
def logout(
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    request: Request,
) -> None:
    svc = _auth_svc(request)
    svc.logout(session_id=claims.session_id)


@router.post("/forgot-password", status_code=status.HTTP_204_NO_CONTENT)
async def forgot_password(body: ForgotPasswordRequest, request: Request) -> None:
    svc = _auth_svc(request)
    await svc.forgot_password(email=body.email)
    # Always returns 204 to prevent email enumeration


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
def reset_password(body: ResetPasswordRequest, request: Request) -> None:
    svc = _auth_svc(request)
    try:
        svc.reset_password(raw_token=body.token, new_password=body.new_password)
    except Exception as exc:
        raise _map_auth_error(exc) from exc


@router.get("/me", response_model=UserResponse)
def get_me(
    claims: Annotated[SessionClaims, Depends(get_current_claims)],
    request: Request,
) -> UserResponse:
    svc = _auth_svc(request)
    try:
        user = svc.get_me(user_id=claims.user_id)
    except Exception as exc:
        raise _map_auth_error(exc) from exc
    return _user_response(user)
