"""
Module middleware xác thực JWT cho FastAPI.

Cung cấp 2 dependency chính:
    - get_current_user: Đọc JWT từ cookie, trả Account object.
    - require_roles: Factory dependency kiểm tra quyền.

Cách dùng trong controller:
    @router.get("/protected")
    async def protected_endpoint(
        current_user: Account = Depends(get_current_user),
    ):
        ...

    @router.get("/admin-only")
    async def admin_endpoint(
        current_user: Account = Depends(require_roles(["root"])),
    ):
        ...
"""

import logging

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from auth import decode_token
from database.setup_postgres import get_db
from database.table.table_postgres import Account, AccountRole

logger = logging.getLogger(__name__)


async def get_current_user(
    request: Request,
) -> Account:
    """
    FastAPI Dependency: xác thực user từ JWT cookie.

    Quy trình:
        1. Đọc cookie "access_token".
        2. Decode JWT (check signature + expiry).
        3. Load Account từ DB (eager load roles).
        4. Check is_active.

    Input:
        request (Request): FastAPI request object.

    Output:
        Account: ORM object của user hiện tại.

    Raises:
        HTTPException 401: Chưa đăng nhập / token hết hạn / invalid.
    """
    from database.setup_postgres import SessionLocal

    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(
            status_code=401,
            detail="Chưa đăng nhập. Vui lòng đăng nhập để tiếp tục.",
        )

    try:
        payload = decode_token(token)
    except Exception:
        raise HTTPException(
            status_code=401,
            detail="Phiên đăng nhập đã hết hạn. Vui lòng đăng nhập lại.",
        )

    # Check purpose = access
    if payload.get("purpose") != "access":
        raise HTTPException(
            status_code=401, detail="Token không hợp lệ",
        )

    account_id = payload["sub"]

    async with SessionLocal() as db:
        result = await db.execute(
            select(Account)
            .where(Account.id == account_id)
            .options(
                selectinload(Account.account_roles)
                .selectinload(AccountRole.role)
            )
        )
        account = result.scalars().first()

    if not account:
        raise HTTPException(status_code=401, detail="Tài khoản không tồn tại")

    if not account.is_active:
        raise HTTPException(
            status_code=401,
            detail="Tài khoản đã bị vô hiệu hóa.",
        )

    return account


def require_roles(allowed_roles: list[str]):
    """
    Factory tạo dependency kiểm tra quyền truy cập.

    Root có mọi quyền — luôn pass.
    Các role khác check giao nhau giữa roles của user
    và allowed_roles.

    Input:
        allowed_roles (list[str]): Danh sách role được phép.

    Output:
        Callable: Dependency function trả về Account.

    Ví dụ:
        require_roles(["rag"])        → cho phép rag, root
        require_roles(["create"])     → cho phép create, root
        require_roles(["root"])       → chỉ root
    """

    async def _checker(
        current_user: Account = Depends(get_current_user),
    ) -> Account:
        user_roles = [
            ar.role.name for ar in current_user.account_roles if ar.role
        ]

        # Root luôn có mọi quyền
        if "root" in user_roles:
            return current_user

        # Check giao nhau
        if not any(r in allowed_roles for r in user_roles):
            raise HTTPException(
                status_code=403,
                detail="Bạn không có quyền truy cập chức năng này.",
            )

        return current_user

    return _checker


async def require_vllm_ready():
    """
    FastAPI Dependency: từ chối request nếu vLLM đang trong quá trình đổi model.

    Check Redis key 'vllm:locking':
        - Không tồn tại → bình thường, cho qua.
        - Tồn tại → đang đổi model, trả 503 với TTL còn lại.

    Dùng tại mọi endpoint gọi LLM (contract + rag).
    """
    from database.setup_redis import redis_service

    try:
        ttl: int = await redis_service.client.ttl("vllm:locking")
        if ttl > 0:
            minutes = (ttl + 59) // 60  # Làm tròn lên phút
            raise HTTPException(
                status_code=503,
                detail=(
                    f"Hệ thống đang đổi mô hình AI. "
                    f"Vui lòng thử lại sau khoảng {minutes} phút."
                ),
            )
    except HTTPException:
        raise
    except Exception as e:
        # Redis lỗi → không chặn request (fail open)
        logger.warning("[VLLM-LOCK] Không kiểm tra được lock Redis: %s", e)
