"""
Controller xử lý các API endpoint liên quan đến Authentication.

Bao gồm các chức năng:
    - Đăng ký, đăng nhập, xác thực email, quên mật khẩu.
    - CRUD accounts (root only).
    - Cập nhật profile và avatar.

Tất cả token được trả về qua httponly cookie (secure, samesite=lax).
"""

import logging
import os
from urllib.parse import quote

from fastapi import APIRouter, Depends, UploadFile, File, Response, Request
from fastapi.responses import HTMLResponse, StreamingResponse, RedirectResponse
from sqlalchemy.orm import Session

from auth.auth_middleware import get_current_user, require_roles
from database.setup_postgres import get_db
from database.table.table_postgres import Account
from request.auth_request import (
    RegisterRequest,
    LoginRequest,
    ForgotPasswordRequest,
    VerifyEmailConfirmRequest,
    UpdateRolesRequest,
    AddRoleRequest,
    UpdateProfileRequest,
    HeartbeatCheckRequest,
    CreateRoleRequest,
    UpdateRoleRequest,
)
from service.auth_service import (
    register_service,
    login_service,
    logout_service,
    verify_email_confirm_service,
    forgot_password_service,
    list_accounts_service,
    update_roles_service,
    add_role_to_account_service,
    remove_role_from_account_service,
    activate_account_service,
    deactivate_account_service,
    delete_account_service,
    get_me_service,
    update_profile_service,
    upload_avatar_service,
    get_avatar_service,
    heartbeat_ping_service,
    heartbeat_check_service,
    list_notifications_service,
    mark_notification_read_service,
    notifications_sse_generator,
    delete_notification_service,
    delete_all_read_notifications_service,
    list_login_history_service,
    delete_login_history_entry_service,
    delete_login_history_service,
    list_roles_service,
    create_role_service,
    update_role_service,
    delete_role_service,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Cookie config
COOKIE_MAX_AGE = int(os.getenv("JWT_EXPIRE_DAYS", "30")) * 86400
COOKIE_HTTPONLY = True
COOKIE_SAMESITE = os.getenv("COOKIE_SAMESITE", "lax")  # "none" khi cross-origin (tunnel/HTTPS)
COOKIE_SECURE = os.getenv("COOKIE_SECURE", "false").lower() == "true"  # True khi deploy HTTPS
FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")


def _set_token_cookie(response: Response, token: str):
    """Set JWT token vào httponly cookie."""

    response.set_cookie(
        key="access_token",
        value=token,
        max_age=COOKIE_MAX_AGE,
        httponly=COOKIE_HTTPONLY,
        samesite=COOKIE_SAMESITE,
        secure=COOKIE_SECURE,
        path="/",
    )


# =============================================================================
# PUBLIC ENDPOINTS (không cần auth)
# =============================================================================


@router.post("/register")
async def register(
    request: RegisterRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    """
    Đăng ký tài khoản mới.

    Tạo account (chưa verify, chưa active), gửi email xác thực,
    trả token qua cookie.
    """

    result = await register_service(request.email, request.password, request.name, db)

    _set_token_cookie(response, result.pop("token"))

    return result


@router.post("/login")
async def login(
    request: LoginRequest,
    response: Response,
    raw_request: Request,
    db: Session = Depends(get_db),
):
    """
    Đăng nhập.

    Check password, lockout nếu sai >= 5 lần.
    Trả token qua cookie. Lưu LoginHistory (IP, Geo, Device).
    """

    result = await login_service(request.email, request.password, db, raw_request)

    _set_token_cookie(response, result.pop("token"))

    return result


@router.post("/verify-email/confirm")
async def verify_email_confirm(
    request: VerifyEmailConfirmRequest,
    db: Session = Depends(get_db),
):
    """
    Xác thực email qua one-time token do frontend gửi ngầm.
    """
    return await verify_email_confirm_service(request.verification_token, db)


@router.get("/verify-email", response_class=HTMLResponse, include_in_schema=False)
async def verify_email_legacy_redirect(token: str | None = None):
    """
    Legacy endpoint cho các email cũ.
    Redirect sang frontend /verify-email#vt=... để frontend gọi API POST ngầm.
    """
    if not token:
        return HTMLResponse(
            "<h3>Link xác thực không hợp lệ.</h3><p>Vui lòng mở lại email xác thực mới nhất.</p>",
            status_code=400,
        )

    if FRONTEND_URL:
        redirect_url = f"{FRONTEND_URL}/verify-email#vt={quote(token, safe='')}"
        return RedirectResponse(url=redirect_url, status_code=307)

    return HTMLResponse(
        "<h3>Thiếu cấu hình FRONTEND_URL.</h3>"
        "<p>Vui lòng cấu hình FRONTEND_URL để chuyển luồng xác thực qua frontend.</p>",
        status_code=500,
    )


@router.post("/forgot-password")
async def forgot_password(
    request: ForgotPasswordRequest,
    db: Session = Depends(get_db),
):
    """Gửi mật khẩu mới qua email."""

    return await forgot_password_service(request.email, db)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    current_user: Account = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Xóa cookie token (đăng xuất) và lưu lịch sử truy cập."""

    await logout_service(current_user.id, request, db)
    response.delete_cookie("access_token", path="/")

    return {"status": 200, "message": "Đã đăng xuất"}


# =============================================================================
# AUTHENTICATED ENDPOINTS (cần đăng nhập)
# =============================================================================


@router.get("/me")
async def get_me(
    current_user: Account = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Lấy thông tin account đang đăng nhập."""

    return await get_me_service(current_user.id, db)


@router.put("/profile")
async def update_profile(
    request: UpdateProfileRequest,
    current_user: Account = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Cập nhật thông tin cá nhân (trừ email)."""

    return await update_profile_service(
        current_user.id,
        request.name,
        request.phone,
        request.address,
        request.password,
        db,
    )


@router.put("/profile/avatar")
async def upload_avatar(
    file: UploadFile = File(...),
    current_user: Account = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Upload ảnh đại diện."""

    content = await file.read()

    return await upload_avatar_service(
        current_user.id, content, file.content_type, db,
    )


@router.get("/avatar/{account_id}")
async def get_avatar(
    account_id: int,
    db: Session = Depends(get_db),
):
    """Lấy ảnh đại diện theo account ID (public)."""

    avatar_bytes, mime_type = await get_avatar_service(account_id, db)

    return Response(content=avatar_bytes, media_type=mime_type)


# =============================================================================
# HEARTBEAT ENDPOINTS
# =============================================================================


@router.post("/heartbeat/ping")
async def heartbeat_ping(
    current_user: Account = Depends(get_current_user),
):
    """Ping heartbeat — client gọi mỗi 60s để giữ trạng thái online."""
    await heartbeat_ping_service(current_user.id)
    return {"status": "ok"}


@router.post("/heartbeat/check")
async def heartbeat_check(
    body: HeartbeatCheckRequest,
    current_user: Account = Depends(require_roles(["root"])),
):
    """Kiểm tra trạng thái online của danh sách users (root only)."""
    result = await heartbeat_check_service(body.user_ids)
    return {"status": "ok", "data": result}


# =============================================================================
# ROOT ONLY ENDPOINTS
# =============================================================================


@router.get("/accounts")
async def list_accounts(
    current_user: Account = Depends(require_roles(["root"])),
    db: Session = Depends(get_db),
):
    """Danh sách tất cả accounts (root only)."""

    return await list_accounts_service(db)


@router.put("/accounts/{account_id}/roles")
async def update_roles(
    account_id: int,
    request: UpdateRolesRequest,
    current_user: Account = Depends(require_roles(["root"])),
    db: Session = Depends(get_db),
):
    """Cập nhật quyền cho tài khoản (root only)."""

    return await update_roles_service(account_id, request.roles, db)


@router.post("/accounts/{account_id}/roles")
async def add_role_to_account(
    account_id: int,
    request: AddRoleRequest,
    current_user: Account = Depends(require_roles(["root"])),
    db: Session = Depends(get_db),
):
    """Thêm 1 role vào account (root only)."""

    return await add_role_to_account_service(account_id, request.role_name, db)


@router.delete("/accounts/{account_id}/roles/{role_name}")
async def remove_role_from_account(
    account_id: int,
    role_name: str,
    current_user: Account = Depends(require_roles(["root"])),
    db: Session = Depends(get_db),
):
    """Xóa 1 role khỏi account (root only)."""

    return await remove_role_from_account_service(account_id, role_name, db)


@router.put("/accounts/{account_id}/activate")
async def activate_account(
    account_id: int,
    current_user: Account = Depends(require_roles(["root"])),
    db: Session = Depends(get_db),
):
    """Bật quyền truy cập cho tài khoản (root only)."""

    return await activate_account_service(account_id, db)


@router.put("/accounts/{account_id}/deactivate")
async def deactivate_account(
    account_id: int,
    current_user: Account = Depends(require_roles(["root"])),
    db: Session = Depends(get_db),
):
    """Tắt quyền truy cập cho tài khoản (root only)."""

    return await deactivate_account_service(account_id, db)


@router.delete("/accounts/{account_id}")
async def delete_account(
    account_id: int,
    current_user: Account = Depends(require_roles(["root"])),
    db: Session = Depends(get_db),
):
    """Xóa tài khoản (root only)."""

    return await delete_account_service(account_id, db)


# =============================================================================
# ADMIN NOTIFICATION ENDPOINTS (ROOT ONLY)
# =============================================================================


@router.get("/notifications")
async def list_notifications(
    limit: int = 50,
    offset: int = 0,
    current_user: Account = Depends(require_roles(["root"])),
    db: Session = Depends(get_db),
):
    """Danh sách thông báo bảo mật (root only, mới nhất trước)."""
    return await list_notifications_service(db, limit=limit, offset=offset)


@router.put("/notifications/{notification_id}/read")
async def mark_notification_read(
    notification_id: int,
    current_user: Account = Depends(require_roles(["root"])),
    db: Session = Depends(get_db),
):
    """Đánh dấu thông báo đã đọc (root only)."""
    return await mark_notification_read_service(notification_id, db)


@router.get("/notifications/sse")
async def notifications_sse(
    current_user: Account = Depends(require_roles(["root"])),
):
    """
    SSE endpoint — realtime alert stream cho admin.

    Client subscribe bằng EventSource:
        const es = new EventSource("/api/v1/auth/notifications/sse", {withCredentials: true});
        es.onmessage = (e) => { const alert = JSON.parse(e.data); ... };
    """
    return StreamingResponse(
        notifications_sse_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store, must-revalidate",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/login-history")
async def list_login_history(
    account_id: int | None = None,
    limit: int = 20,
    offset: int = 0,
    current_user: Account = Depends(require_roles(["root"])),
    db: Session = Depends(get_db),
):
    """Lịch sử đăng nhập (root only). Lọc theo account_id nếu có."""
    return await list_login_history_service(db, account_id=account_id, limit=limit, offset=offset)


@router.delete("/notifications/all-read")
async def delete_all_read_notifications(
    current_user: Account = Depends(require_roles(["root"])),
    db: Session = Depends(get_db),
):
    """Xóa tất cả thông báo đã đọc (root only)."""
    return await delete_all_read_notifications_service(db)


@router.delete("/notifications/{notification_id}")
async def delete_notification(
    notification_id: int,
    current_user: Account = Depends(require_roles(["root"])),
    db: Session = Depends(get_db),
):
    """Xóa một thông báo bảo mật theo ID (root only)."""
    return await delete_notification_service(notification_id, db)


@router.delete("/login-history/entry/{entry_id}")
async def delete_login_history_entry(
    entry_id: int,
    current_user: Account = Depends(require_roles(["root"])),
    db: Session = Depends(get_db),
):
    """Xóa một bản ghi lịch sử đăng nhập theo ID (root only)."""
    return await delete_login_history_entry_service(entry_id, db)


@router.delete("/login-history/{account_id}")
async def delete_login_history(
    account_id: int,
    current_user: Account = Depends(require_roles(["root"])),
    db: Session = Depends(get_db),
):
    """Xóa toàn bộ lịch sử đăng nhập của một tài khoản (root only)."""
    return await delete_login_history_service(account_id, db)


# =============================================================================
# ROLE MANAGEMENT (ROOT ONLY)
# =============================================================================
# ROLE MANAGEMENT (ROOT ONLY)
# =============================================================================


@router.get("/roles", dependencies=[Depends(require_roles(["root"]))])
async def list_roles(db: Session = Depends(get_db)):
    """Lấy danh sách tất cả roles hệ thống."""

    return await list_roles_service(db)


@router.post("/roles", dependencies=[Depends(require_roles(["root"]))])
async def create_role(
    req: CreateRoleRequest,
    db: Session = Depends(get_db),
):
    """Tạo role mới."""

    return await create_role_service(req.name, req.description, db)


@router.put("/roles/{role_id}", dependencies=[Depends(require_roles(["root"]))])
async def update_role(
    role_id: int,
    req: UpdateRoleRequest,
    db: Session = Depends(get_db),
):
    """Cập nhật thông tin role."""

    return await update_role_service(role_id, req.name, req.description, db)


@router.delete("/roles/{role_id}", dependencies=[Depends(require_roles(["root"]))])
async def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
):
    """Xóa role."""

    return await delete_role_service(role_id, db)
