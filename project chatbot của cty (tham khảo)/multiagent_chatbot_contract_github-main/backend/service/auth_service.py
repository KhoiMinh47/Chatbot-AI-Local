"""
Service layer cho hệ thống Authentication.

Cung cấp tất cả business logic liên quan đến:
    - Đăng ký (register): Tạo account, gửi email verify.
    - Đăng nhập (login): Check password, lockout lũy tiến.
    - Xác thực email (verify): Decode token, bật is_verified.
    - Quên mật khẩu (forgot): Generate password mới, gửi email.
    - CRUD accounts (root only): List, sửa quyền, active, xóa.
    - Profile: Sửa thông tin cá nhân, upload/get avatar.

Chiến lược lockout:
    - Sai >= 5 lần → khóa lũy tiến: 5p → 50p → 500p.
    - Công thức: lock_minutes = 5 * (10 ** (failed_attempts - 5))
"""

import asyncio
import hashlib
import ipaddress
import logging
import os
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from sqlalchemy import select, delete, update
from sqlalchemy.orm import selectinload
from user_agents import parse as parse_ua

from auth import (
    hash_password,
    verify_password,
    create_token,
    generate_random_password,
    JWT_EXPIRE_DAYS,
)
from auth.email_utils import (
    send_verification_email,
    send_reset_password_email,
)
from auth.telegram_utils import send_verified_user_notification
from database.setup_postgres import SessionLocal
from database.setup_geoip import geoip_service
from database.setup_redis import (
    CACHE_KEY_HISTORY_PREFIX,
    CACHE_KEY_SESSIONS,
    redis_service,
)
from database.table.table_postgres import (
    Account, EmailVerificationToken, Role, AccountRole,
    contract, history_mess, session,
    LoginHistory, AdminNotification,
)

logger = logging.getLogger(__name__)

# --- Hằng số ---
# Số lần sai tối đa trước khi bắt đầu khóa
MAX_FAILED_ATTEMPTS_BEFORE_LOCK = 5
VERIFY_TOKEN_EXPIRE_MINUTES = int(os.getenv("VERIFY_TOKEN_EXPIRE_MINUTES", "60"))
VERIFY_TOKEN_BYTES = 48
VERIFY_TOKEN_PEPPER = os.getenv("VERIFY_TOKEN_PEPPER", os.getenv("JWT_SECRET_KEY", "change-me-in-production"))

# Regex validate email cơ bản
EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+$")

# Độ dài password tối thiểu
MIN_PASSWORD_LENGTH = 6


# =============================================================================
# HELPER FUNCTIONS
# =============================================================================


def _get_role_names(account: Account) -> list[str]:
    """Trích xuất danh sách tên role từ Account object."""
    return [ar.role.name for ar in account.account_roles if ar.role]


def _calculate_lock_minutes(failed_attempts: int) -> int:
    """
    Tính thời gian khóa lũy tiến (phút).

    Công thức: 5 * (10 ** (failed_attempts - 5))
        - Lần sai 5:  5 phút
        - Lần sai 6:  50 phút
        - Lần sai 7:  500 phút

    Input:
        failed_attempts (int): Số lần sai liên tiếp.

    Output:
        int: Số phút khóa. 0 nếu chưa đủ ngưỡng.
    """

    if failed_attempts < MAX_FAILED_ATTEMPTS_BEFORE_LOCK:
        return 0

    return 5 * (10 ** (failed_attempts - MAX_FAILED_ATTEMPTS_BEFORE_LOCK))


def _serialize_account(account: Account) -> dict:
    """
    Serialize Account ORM object thành dict (không chứa password/avatar).

    Dùng cho response trả về frontend.
    """

    return {
        "id": account.id,
        "email": account.email,
        "name": account.name,
        "phone": account.phone,
        "address": account.address,
        "is_verified": account.is_verified,
        "is_active": account.is_active,
        "has_avatar": account.avatar is not None,
        "roles": _get_role_names(account),
        "created_at": account.created_at.isoformat()
        if account.created_at else None,
        "updated_at": account.updated_at.isoformat()
        if account.updated_at else None,
    }


def _hash_verification_token(raw_token: str) -> str:
    """Hash token verify với pepper để chỉ lưu hash trong DB."""
    payload = f"{VERIFY_TOKEN_PEPPER}:{raw_token}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def _issue_email_verification_token(account_id: int, db) -> str:
    """
    Tạo token verify one-time cho account:
    - Revoke toàn bộ token chưa dùng trước đó.
    - Lưu HASH token + expires_at.
    - Trả raw token để gửi qua email.
    """
    now = datetime.now(timezone.utc)
    raw_token = secrets.token_urlsafe(VERIFY_TOKEN_BYTES)
    token_hash = _hash_verification_token(raw_token)
    expires_at = now + timedelta(minutes=VERIFY_TOKEN_EXPIRE_MINUTES)

    await db.execute(
        delete(EmailVerificationToken).where(
            EmailVerificationToken.account_id == account_id,
            EmailVerificationToken.purpose == "verify_email",
            EmailVerificationToken.used_at.is_(None),
        )
    )

    db.add(
        EmailVerificationToken(
            account_id=account_id,
            purpose="verify_email",
            token_hash=token_hash,
            expires_at=expires_at,
        )
    )
    await db.commit()
    return raw_token


# =============================================================================
# ĐĂNG KÝ (REGISTER)
# =============================================================================


async def register_service(email: str, password: str, name: str, db):
    """
    Đăng ký tài khoản mới.

    Quy trình:
        1. Validate email format.
        2. Check email đã tồn tại → 409 Conflict.
        3. Hash password (bcrypt, 12 rounds).
        4. Tạo account (is_verified=False, is_active=False).
        5. Gán role "none" mặc định.
        6. Gửi email verification (async, non-blocking).
        7. Tạo access token (JWT 30 ngày).

    Input:
        email (str): Email đăng ký.
        password (str): Mật khẩu.
        name (str): Tên hiển thị.
        db (AsyncSession): Database session.

    Output:
        dict: {account info, token}

    Raises:
        HTTPException 400: Email không hợp lệ / password quá ngắn.
        HTTPException 409: Email đã tồn tại.
    """

    # 1. Validate
    if not EMAIL_REGEX.match(email):
        raise HTTPException(status_code=400, detail="Email không hợp lệ")

    if len(password) < MIN_PASSWORD_LENGTH:
        raise HTTPException(
            status_code=400,
            detail=f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự",
        )

    # 2. Check trùng email
    existing = await db.execute(
        select(Account).where(Account.email == email)
    )
    if existing.scalars().first():
        raise HTTPException(status_code=409, detail="Email đã được sử dụng")

    # 3. Hash password
    hashed = hash_password(password)

    # 4. Tạo account
    new_account = Account(
        email=email,
        password_hash=hashed,
        name=name,
        is_verified=False,
        is_active=False,
    )
    db.add(new_account)
    await db.flush()
    
    db.add(AccountRole(
        account_id=new_account.id,
        role_id=2,
    ))

    await db.commit()
    await db.refresh(new_account)

    # 6. Gửi email verification (one-time token, non-blocking)
    verify_token = await _issue_email_verification_token(new_account.id, db)
    asyncio.create_task(send_verification_email(email, verify_token))

    # 7. Tạo access token
    roles = ["none"]
    access_token = create_token(new_account.id, roles)

    logger.info(
        "[AUTH] Đăng ký thành công: %s (id=%d)",
        email, new_account.id,
    )

    return {
        "status": 200,
        "token": access_token,
        "account": {
            "id": new_account.id,
            "email": new_account.email,
            "name": new_account.name,
            "is_verified": new_account.is_verified,
            "is_active": new_account.is_active,
            "roles": roles,
        },
    }


# =============================================================================
# ĐĂNG NHẬP (LOGIN)
# =============================================================================


async def login_service(email: str, password: str, db, request: Request = None):
    """
    Đăng nhập tài khoản.

    Thuật toán lockout lũy tiến:
        - Sai 1-4 lần: chỉ tăng failed_attempts.
        - Sai >= 5 lần: khóa 5 * (10 ** (n - 5)) phút.
        - Đúng password: reset failed_attempts = 0.

    Khi login thành công:
        - Bóc tách IP, OS, Browser, Device, Geo, ISP/ASN.
        - Lưu LoginHistory vào PostgreSQL.
        - Embed login_ip vào JWT token (cho middleware fast-path).

    Input:
        email (str): Email đăng nhập.
        password (str): Mật khẩu.
        db (AsyncSession): Database session.
        request (Request | None): FastAPI Request để lấy IP + User-Agent.

    Output:
        dict: {account info, token}

    Raises:
        HTTPException 401: Sai credentials / bị khóa.
        HTTPException 403: Chưa verify / chưa active.
    """

    # 1. Tìm account (eager load roles)
    result = await db.execute(
        select(Account)
        .where(Account.email == email)
        .options(
            selectinload(Account.account_roles)
            .selectinload(AccountRole.role)
        )
    )
    account = result.scalars().first()

    if not account:
        raise HTTPException(
            status_code=401, detail="Email hoặc mật khẩu không đúng",
        )

    # 2. Check lockout
    now = datetime.now(timezone.utc)
    if account.locked_until and account.locked_until > now:
        remaining = (account.locked_until - now).total_seconds() / 60
        raise HTTPException(
            status_code=401,
            detail=(
                f"Tài khoản bị khóa do nhập sai quá nhiều lần. "
                f"Thử lại sau {int(remaining) + 1} phút."
            ),
        )

    # 3. Nếu hết lock → xóa locked_until (giữ failed_attempts)
    if account.locked_until and account.locked_until <= now:
        account.locked_until = None

    # 4. Check password
    if not verify_password(password, account.password_hash):
        account.failed_attempts += 1

        # Tính lockout nếu đủ ngưỡng
        lock_minutes = _calculate_lock_minutes(account.failed_attempts)
        if lock_minutes > 0:
            account.locked_until = now + timedelta(minutes=lock_minutes)
            logger.warning(
                "[AUTH] Account %s bị khóa %d phút (sai %d lần)",
                email, lock_minutes, account.failed_attempts,
            )

        await db.commit()

        raise HTTPException(
            status_code=401,
            detail="Email hoặc mật khẩu không đúng",
        )

    # 5. Password đúng → reset lockout
    account.failed_attempts = 0
    account.locked_until = None

    # 6. Check is_verified
    if not account.is_verified:
        await db.commit()
        raise HTTPException(
            status_code=403,
            detail="Tài khoản chưa xác thực email. Kiểm tra hộp thư.",
        )

    # 7. Check is_active
    if not account.is_active:
        await db.commit()
        raise HTTPException(
            status_code=403,
            detail="Tài khoản chưa được admin kích hoạt.",
        )

    await db.commit()

    # 8. Bóc tách IP, User-Agent, GeoIP và lưu LoginHistory
    client_ip = _extract_client_ip(request) if request else "unknown"
    ua_info = _parse_user_agent(request) if request else {}
    private_ip = _is_private_ip(client_ip)

    # GeoIP chỉ hoạt động với public IP — private IP (LAN) sẽ trả null
    if client_ip != "unknown" and not private_ip:
        geo = geoip_service.lookup(client_ip)
    else:
        geo = None

    # Chặn đăng nhập từ VPN/datacenter IP
    if geo and geo.is_vpn_or_datacenter:
        logger.warning(
            "[AUTH] VPN login blocked: %s | IP=%s | ASN=%s (%s)",
            email, client_ip, geo.asn, geo.as_org,
        )
        raise HTTPException(
            status_code=403,
            detail="Đăng nhập từ VPN/proxy không được phép. Vui lòng tắt VPN và thử lại.",
        )

    login_record = LoginHistory(
        account_id=account.id,
        action="login",
        ip_address=client_ip,
        country=geo.country if geo else ("LAN" if private_ip else None),
        city=geo.city if geo else ("Private Network" if private_ip else None),
        latitude=geo.latitude if geo else None,
        longitude=geo.longitude if geo else None,
        isp=geo.isp if geo else ("Local Network" if private_ip else None),
        asn=geo.asn if geo else None,
        as_org=geo.as_org if geo else None,
        os=ua_info.get("os"),
        browser=ua_info.get("browser"),
        device_type=ua_info.get("device_type"),
        is_vpn_or_datacenter=geo.is_vpn_or_datacenter if geo else False,
        user_agent=ua_info.get("user_agent"),
    )
    db.add(login_record)
    await db.commit()

    # 9. Tạo access token — INCR session_ver để kick tất cả session cũ
    roles = _get_role_names(account)
    session_ver = None
    if redis_service.client:
        try:
            redis_key = f"session_ver:{account.id}"
            session_ver = await redis_service.client.incr(redis_key)
            await redis_service.client.expire(redis_key, JWT_EXPIRE_DAYS * 86400)
        except Exception as e:
            logger.warning("[AUTH] Không thể INCR session_ver: %s", e)
    access_token = create_token(account.id, roles, login_ip=client_ip, session_ver=session_ver)

    # Tổng hợp login tracking info để trả về frontend
    login_tracking = {
        "action": "login",
        "ip": client_ip,
        "is_private_ip": private_ip,
        "country": login_record.country,
        "city": login_record.city,
        "latitude": login_record.latitude,
        "longitude": login_record.longitude,
        "isp": login_record.isp,
        "asn": login_record.asn,
        "as_org": login_record.as_org,
        "os": login_record.os,
        "browser": login_record.browser,
        "device_type": login_record.device_type,
        "is_vpn_or_datacenter": login_record.is_vpn_or_datacenter,
        "user_agent": login_record.user_agent,
    }

    logger.info(
        "[AUTH] Đăng nhập thành công: %s | IP=%s | %s | VPN=%s",
        email, client_ip,
        login_record.country or "?",
        login_record.is_vpn_or_datacenter,
    )

    return {
        "status": 200,
        "token": access_token,
        "account": _serialize_account(account),
        "login_tracking": login_tracking,
    }


# =============================================================================
# ĐĂNG XUẤT (LOGOUT)
# =============================================================================


async def logout_service(account_id: int, request: Request, db):
    """
    Lưu lịch sử đăng xuất vào LoginHistory (action="logout").

    Bóc tách IP + User-Agent giống login, nhưng không cần GeoIP đầy đủ
    — chỉ ghi nhận IP và thiết bị để đối chiếu với lịch sử đăng nhập.

    Input:
        account_id (int): ID tài khoản từ JWT.
        request (Request): FastAPI Request để lấy IP + UA.
        db (AsyncSession): Database session.
    """

    client_ip = _extract_client_ip(request) if request else "unknown"
    ua_info = _parse_user_agent(request) if request else {}
    private_ip = _is_private_ip(client_ip)

    # GeoIP lookup cho public IP
    if client_ip != "unknown" and not private_ip:
        geo = geoip_service.lookup(client_ip)
    else:
        geo = None

    logout_record = LoginHistory(
        account_id=account_id,
        action="logout",
        ip_address=client_ip,
        country=geo.country if geo else ("LAN" if private_ip else None),
        city=geo.city if geo else ("Private Network" if private_ip else None),
        latitude=geo.latitude if geo else None,
        longitude=geo.longitude if geo else None,
        isp=geo.isp if geo else ("Local Network" if private_ip else None),
        asn=geo.asn if geo else None,
        as_org=geo.as_org if geo else None,
        os=ua_info.get("os"),
        browser=ua_info.get("browser"),
        device_type=ua_info.get("device_type"),
        is_vpn_or_datacenter=geo.is_vpn_or_datacenter if geo else False,
        user_agent=ua_info.get("user_agent"),
    )
    db.add(logout_record)
    await db.commit()

    # Increment session_ver để invalidate token ngay khi logout
    if redis_service.client:
        try:
            await redis_service.client.incr(f"session_ver:{account_id}")
        except Exception as e:
            logger.warning("[AUTH] Không thể INCR session_ver on logout: %s", e)

    logger.info(
        "[AUTH] Đăng xuất: account_id=%d | IP=%s",
        account_id, client_ip,
    )


# =============================================================================
# XÁC THỰC EMAIL (VERIFY)
# =============================================================================


async def verify_email_confirm_service(verification_token: str, db):
    """
    Xác thực email qua one-time token do frontend gửi ngầm (POST JSON).

    Input:
        verification_token (str): Raw token nhận từ link email.
        db (AsyncSession): Database session.

    Output:
        dict: JSON kết quả xác thực.

    Raises:
        HTTPException 400: Token không hợp lệ / hết hạn.
    """
    raw_token = str(verification_token or "").strip()
    if len(raw_token) < 32 or len(raw_token) > 1024:
        raise HTTPException(
            status_code=400,
            detail="Link xác thực không hợp lệ hoặc đã hết hạn.",
        )

    now = datetime.now(timezone.utc)
    token_hash = _hash_verification_token(raw_token)

    result = await db.execute(
        select(EmailVerificationToken).where(
            EmailVerificationToken.token_hash == token_hash,
            EmailVerificationToken.purpose == "verify_email",
        )
    )
    token_row = result.scalars().first()

    if not token_row:
        raise HTTPException(
            status_code=400,
            detail="Link xác thực không hợp lệ hoặc đã hết hạn.",
        )

    if token_row.used_at is not None:
        raise HTTPException(
            status_code=400,
            detail="Link xác thực đã được sử dụng. Vui lòng yêu cầu gửi lại email xác thực.",
        )

    if token_row.expires_at <= now:
        raise HTTPException(
            status_code=400,
            detail="Link xác thực đã hết hạn. Vui lòng yêu cầu gửi lại email xác thực.",
        )

    account = await db.get(Account, token_row.account_id)
    if not account:
        raise HTTPException(
            status_code=400,
            detail="Link xác thực không hợp lệ hoặc đã hết hạn.",
        )

    token_row.used_at = now
    if account.is_verified:
        await db.commit()
        return {
            "status": 200,
            "code": "ALREADY_VERIFIED",
            "message": "Email đã được xác thực trước đó.",
        }

    account.is_verified = True
    await db.execute(
        update(EmailVerificationToken)
        .where(
            EmailVerificationToken.account_id == account.id,
            EmailVerificationToken.purpose == "verify_email",
            EmailVerificationToken.used_at.is_(None),
            EmailVerificationToken.id != token_row.id,
        )
        .values(used_at=now)
    )
    await db.commit()

    asyncio.create_task(
        send_verified_user_notification(
            {
                "id": account.id,
                "email": account.email,
                "name": account.name,
            }
        )
    )

    logger.info("[AUTH] Email verified: %s (id=%d)", account.email, account.id)
    return {
        "status": 200,
        "code": "VERIFIED",
        "message": "Xác thực email thành công!",
    }


# =============================================================================
# QUÊN MẬT KHẨU (FORGOT PASSWORD)
# =============================================================================


async def forgot_password_service(email: str, db):
    """
    Reset mật khẩu: tạo password mới, gửi qua email.

    Quy trình:
        1. Tìm account theo email.
        2. Generate random password (12 chars).
        3. Hash và update vào DB.
        4. Reset failed_attempts + locked_until.
        5. Gửi email với password mới.

    Input:
        email (str): Email tài khoản.
        db (AsyncSession): Database session.

    Output:
        dict: {status, message}

    Raises:
        HTTPException 404: Email không tồn tại.
    """

    result = await db.execute(
        select(Account).where(Account.email == email)
    )
    account = result.scalars().first()

    if not account:
        raise HTTPException(
            status_code=404, detail="Email không tồn tại trong hệ thống",
        )

    # Generate và update password mới
    new_password = generate_random_password()
    account.password_hash = hash_password(new_password)
    account.failed_attempts = 0
    account.locked_until = None
    await db.commit()

    # Gửi email (non-blocking)
    asyncio.create_task(send_reset_password_email(email, new_password))

    logger.info("[AUTH] Reset password cho: %s", email)

    return {
        "status": 200,
        "message": "Mật khẩu mới đã được gửi qua email.",
    }


# =============================================================================
# CRUD ACCOUNTS (ROOT ONLY)
# =============================================================================


# Cache accounts list cho admin dashboard polling
CACHE_KEY_ACCOUNTS = "auth:accounts:all"
CACHE_TTL_ACCOUNTS = 15  # 15s — tươi hơn khi polling 30s


async def _invalidate_accounts_cache():
    """Xóa cache accounts list khi có thay đổi."""
    try:
        await redis_service.client.delete(CACHE_KEY_ACCOUNTS)
    except Exception as e:
        logger.warning("[CACHE] Redis invalidate accounts failed: %s", e)


async def list_accounts_service(db):
    """
    Lấy danh sách tất cả tài khoản (root only).

    Cache trong Redis 30s để giảm tải Postgres khi nhiều admin poll cùng lúc.

    Input:
        db (AsyncSession): Database session.

    Output:
        dict: {status, result: list[account_dict]}
    """
    import json

    # 1. Check cache Redis
    try:
        cached = await redis_service.client.get(CACHE_KEY_ACCOUNTS)
        if cached:
            return {"status": 200, "result": json.loads(cached)}
    except Exception as e:
        logger.warning("[CACHE] Redis get accounts failed: %s", e)

    # 2. Query Postgres
    # Query accounts with roles and find latest login history for each
    from sqlalchemy import func
    
    # Subquery to find the latest login history ID for each account
    latest_history_subquery = (
        select(
            LoginHistory.account_id,
            func.max(LoginHistory.id).label("latest_id")
        )
        .group_by(LoginHistory.account_id)
        .subquery()
    )

    result = await db.execute(
        select(Account, LoginHistory)
        .options(
            selectinload(Account.account_roles)
            .selectinload(AccountRole.role)
        )
        .outerjoin(
            latest_history_subquery,
            Account.id == latest_history_subquery.c.account_id
        )
        .outerjoin(
            LoginHistory,
            LoginHistory.id == latest_history_subquery.c.latest_id
        )
    )
    
    rows = result.all()
    
    serialized = []
    for account, history in rows:
        acc_dict = _serialize_account(account)
        if history:
            acc_dict.update({
                "last_seen_at": history.created_at.isoformat() if history.created_at else None,
                "last_seen_action": history.action,
                "last_seen_ip": history.ip_address,
                "last_seen_location": f"{history.city}, {history.country}" if history.city and history.country else history.country,
                "last_seen_device": f"{history.os} / {history.browser}" if history.os and history.browser else history.os,
            })
        else:
            acc_dict.update({
                "last_seen_at": None,
                "last_seen_action": None,
                "last_seen_ip": None,
                "last_seen_location": None,
                "last_seen_device": None,
            })
        serialized.append(acc_dict)

    # 3. Lưu cache
    try:
        await redis_service.client.setex(
            CACHE_KEY_ACCOUNTS, CACHE_TTL_ACCOUNTS, json.dumps(serialized),
        )
    except Exception as e:
        logger.warning("[CACHE] Redis set accounts failed: %s", e)

    return {
        "status": 200,
        "result": serialized,
    }


async def update_roles_service(account_id: int, role_names: list[str], db):
    """
    Cập nhật quyền cho tài khoản (root only).

    Xóa toàn bộ roles cũ, gán roles mới.

    Input:
        account_id (int): ID tài khoản.
        role_names (list[str]): Danh sách tên role mới.
        db (AsyncSession): Database session.

    Raises:
        HTTPException 404: Account không tồn tại.
        HTTPException 400: Role name không hợp lệ.
    """

    # Check account tồn tại
    account_result = await db.execute(
        select(Account).where(Account.id == account_id)
    )
    account = account_result.scalars().first()
    if not account:
        raise HTTPException(status_code=404, detail="Tài khoản không tồn tại")

    # Lấy role objects theo tên
    roles_result = await db.execute(
        select(Role).where(Role.name.in_(role_names))
    )
    roles = roles_result.scalars().all()

    if len(roles) != len(role_names):
        found_names = {r.name for r in roles}
        invalid = set(role_names) - found_names
        raise HTTPException(
            status_code=400,
            detail=f"Role không hợp lệ: {', '.join(invalid)}",
        )

    # Xóa roles cũ
    await db.execute(
        delete(AccountRole).where(AccountRole.account_id == account_id)
    )

    # Gán roles mới
    for role in roles:
        db.add(AccountRole(account_id=account_id, role_id=role.id))

    await db.commit()

    logger.info(
        "[AUTH] Cập nhật roles cho account %d: %s",
        account_id, role_names,
    )

    await _invalidate_accounts_cache()
    return {"status": 200, "result": "ok"}


async def add_role_to_account_service(account_id: int, role_name: str, db):
    """
    Thêm 1 role vào account (không xóa roles cũ).

    Input:
        account_id (int): ID tài khoản.
        role_name (str): Tên role cần thêm.
        db (AsyncSession): Database session.

    Raises:
        HTTPException 404: Account hoặc role không tồn tại.
        HTTPException 400: Account đã có role này.
    """

    account = await _get_account_or_404(account_id, db)

    role_result = await db.execute(select(Role).where(Role.name == role_name))
    role = role_result.scalars().first()
    if not role:
        raise HTTPException(status_code=404, detail=f"Role '{role_name}' không tồn tại")

    # Check đã có chưa
    existing = await db.execute(
        select(AccountRole).where(
            AccountRole.account_id == account_id,
            AccountRole.role_id == role.id,
        )
    )
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail=f"Account đã có role '{role_name}'")

    db.add(AccountRole(account_id=account_id, role_id=role.id))
    await db.commit()

    logger.info("[AUTH] Thêm role '%s' cho account %d", role_name, account_id)
    await _invalidate_accounts_cache()
    return {"status": 200, "result": "ok"}


async def remove_role_from_account_service(account_id: int, role_name: str, db):
    """
    Xóa 1 role khỏi account.

    Input:
        account_id (int): ID tài khoản.
        role_name (str): Tên role cần xóa.
        db (AsyncSession): Database session.

    Raises:
        HTTPException 404: Account hoặc role không tồn tại.
        HTTPException 400: Account không có role này.
    """

    account = await _get_account_or_404(account_id, db)

    role_result = await db.execute(select(Role).where(Role.name == role_name))
    role = role_result.scalars().first()
    if not role:
        raise HTTPException(status_code=404, detail=f"Role '{role_name}' không tồn tại")

    existing = await db.execute(
        select(AccountRole).where(
            AccountRole.account_id == account_id,
            AccountRole.role_id == role.id,
        )
    )
    if not existing.scalars().first():
        raise HTTPException(status_code=400, detail=f"Account không có role '{role_name}'")

    await db.execute(
        delete(AccountRole).where(
            AccountRole.account_id == account_id,
            AccountRole.role_id == role.id,
        )
    )
    await db.commit()

    logger.info("[AUTH] Xóa role '%s' khỏi account %d", role_name, account_id)
    await _invalidate_accounts_cache()
    return {"status": 200, "result": "ok"}


async def list_roles_service(db):
    """Lấy danh sách tất cả roles."""

    result = await db.execute(select(Role).order_by(Role.id.asc()))
    roles = result.scalars().all()

    return {
        "status": 200,
        "result": [
            {"id": r.id, "name": r.name, "description": r.description}
            for r in roles
        ],
    }


async def create_role_service(name: str, description: str | None, db):
    """Tạo role mới."""

    # Check trùng tên
    existing = await db.execute(select(Role).where(Role.name == name))
    if existing.scalars().first():
        raise HTTPException(status_code=400, detail="Role name đã tồn tại")

    new_role = Role(name=name, description=description)
    db.add(new_role)
    await db.commit()
    await db.refresh(new_role)

    logger.info("[AUTH] Đã tạo role mới: %s", name)
    return {
        "status": 200,
        "result": {"id": new_role.id, "name": new_role.name, "description": new_role.description}
    }


async def update_role_service(role_id: int, name: str | None, description: str | None, db):
    """Cập nhật thông tin role."""

    result = await db.execute(select(Role).where(Role.id == role_id))
    role = result.scalars().first()
    if not role:
        raise HTTPException(status_code=404, detail="Role không tồn tại")

    if name:
        # Check trùng tên với role khác
        existing = await db.execute(
            select(Role).where(Role.name == name, Role.id != role_id)
        )
        if existing.scalars().first():
            raise HTTPException(status_code=400, detail="Role name đã tồn tại")
        role.name = name

    if description is not None:
        role.description = description

    await db.commit()
    logger.info("[AUTH] Đã cập nhật role id=%d", role_id)
    return {"status": 200, "result": "ok"}


async def delete_role_service(role_id: int, db):
    """Xóa role."""

    result = await db.execute(select(Role).where(Role.id == role_id))
    role = result.scalars().first()
    if not role:
        raise HTTPException(status_code=404, detail="Role không tồn tại")

    # Không cho xóa root role
    if role.name == 'root':
        raise HTTPException(status_code=400, detail="Không thể xóa role root")

    # Check ràng buộc với AccountRole
    rel_result = await db.execute(
        select(AccountRole).where(AccountRole.role_id == role_id)
    )
    if rel_result.scalars().first():
        raise HTTPException(
            status_code=400,
            detail="Không thể xóa role đang có account sử dụng"
        )

    await db.delete(role)
    await db.commit()
    logger.info("[AUTH] Đã xóa role id=%d", role_id)
    return {"status": 200, "result": "ok"}


async def activate_account_service(account_id: int, db):
    """Bật is_active và auto-verify email cho tài khoản (root only)."""

    account = await _get_account_or_404(account_id, db)
    account.is_active = True
    account.is_verified = True
    await db.commit()

    logger.info("[AUTH] Activated + verified account %d", account_id)
    await _invalidate_accounts_cache()
    return {"status": 200, "result": "ok"}


async def deactivate_account_service(account_id: int, db):
    """Tắt is_active cho tài khoản (root only)."""

    account = await _get_account_or_404(account_id, db)
    account.is_active = False
    await db.commit()

    logger.info("[AUTH] Deactivated account %d", account_id)
    await _invalidate_accounts_cache()
    return {"status": 200, "result": "ok"}


async def delete_account_service(account_id: int, db):
    """
    Xóa tài khoản và toàn bộ dữ liệu liên quan user (root only).

    Bao gồm:
        - Dữ liệu auth có FK account_id (cascade DB): account_role, login_history,
          admin_notification, email_verification_token.
        - Dữ liệu domain theo user_id/session_id (xóa thủ công): contract, session,
          history_mess.
        - Redis state: session_ver, heartbeat, cache sessions/history.
    """

    account = await _get_account_or_404(account_id, db)
    user_id = str(account.id)

    # 1) Thu thập session IDs của user để dọn dữ liệu phụ thuộc theo session_id
    session_ids_rs = await db.execute(
        select(session.id).where(session.user_id == user_id)
    )
    session_ids = session_ids_rs.scalars().all()

    # 2) Xóa dữ liệu domain theo user_id
    await db.execute(
        delete(contract).where(contract.user_id == user_id)
    )
    await db.execute(
        delete(history_mess).where(history_mess.user_id == user_id)
    )

    # 3) Xóa dữ liệu phụ thuộc theo session_id (đúng thứ tự để tránh FK conflict)
    if session_ids:
        await db.execute(
            delete(contract).where(contract.session_id.in_(session_ids))
        )
        await db.execute(
            delete(history_mess).where(history_mess.session_id.in_(session_ids))
        )
        await db.execute(
            delete(session).where(session.id.in_(session_ids))
        )

    # 4) Xóa account (phần auth liên quan account_id sẽ được DB cascade)
    await db.delete(account)
    await db.commit()

    # 5) Dọn state/cache ở Redis (best-effort)
    await _cleanup_account_redis_state(account_id=account_id, user_id=user_id, session_ids=session_ids)

    logger.info("[AUTH] Deleted account %d", account_id)
    await _invalidate_accounts_cache()
    return {"status": 200, "result": "ok"}


# =============================================================================
# PROFILE
# =============================================================================


async def get_me_service(account_id: int, db):
    """
    Lấy thông tin account hiện tại (từ JWT token).

    Input:
        account_id (int): ID từ JWT payload.
        db (AsyncSession): Database session.

    Output:
        dict: {status, result: account_dict}
    """

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
        raise HTTPException(status_code=404, detail="Tài khoản không tồn tại")

    return {
        "status": 200,
        "result": _serialize_account(account),
    }


async def update_profile_service(
    account_id: int,
    name: str | None,
    phone: str | None,
    address: str | None,
    password: str | None,
    db,
):
    """
    Cập nhật thông tin cá nhân (trừ email).

    Input:
        account_id (int): ID tài khoản.
        name, phone, address, password: Các trường cần sửa (None = không sửa).
        db (AsyncSession): Database session.
    """

    account = await _get_account_or_404(account_id, db)

    if name is not None:
        account.name = name
    if phone is not None:
        account.phone = phone
    if address is not None:
        account.address = address
    if password is not None:
        if len(password) < MIN_PASSWORD_LENGTH:
            raise HTTPException(
                status_code=400,
                detail=f"Mật khẩu phải có ít nhất {MIN_PASSWORD_LENGTH} ký tự",
            )
        account.password_hash = hash_password(password)

    await db.commit()

    logger.info("[AUTH] Updated profile for account %d", account_id)

    return {"status": 200, "result": "ok"}


async def upload_avatar_service(account_id: int, avatar_bytes: bytes, mime_type: str, db):
    """
    Upload ảnh đại diện.

    Lưu trực tiếp bytes vào DB (LargeBinary).

    Input:
        account_id (int): ID tài khoản.
        avatar_bytes (bytes): Nội dung ảnh.
        mime_type (str): MIME type (image/png, image/jpeg, ...).
        db (AsyncSession): Database session.
    """

    account = await _get_account_or_404(account_id, db)
    account.avatar = avatar_bytes
    account.avatar_mime = mime_type
    await db.commit()

    logger.info("[AUTH] Updated avatar for account %d", account_id)
    return {"status": 200, "result": "ok"}


async def get_avatar_service(account_id: int, db):
    """
    Lấy ảnh đại diện.

    Output:
        tuple: (bytes, mime_type) hoặc raise 404.
    """

    result = await db.execute(
        select(Account.avatar, Account.avatar_mime)
        .where(Account.id == account_id)
    )
    row = result.first()

    if not row or not row.avatar:
        raise HTTPException(status_code=404, detail="Không có ảnh đại diện")

    return row.avatar, row.avatar_mime or "image/png"


# =============================================================================
# HEARTBEAT (NHỊP TIM)
# =============================================================================

# TTL cho key online (giây).
# Lý do chọn 120s:
#   - Foreground: client ping mỗi 30s → TTL refresh đều đặn, hoàn toàn OK.
#   - Background tab: trình duyệt Chrome/Firefox throttle setInterval còn ~60s,
#     nên nếu TTL ≤ 60s, key sẽ hết hạn trước khi ping tiếp theo tới → user hiện offline.
#     120s = 2× buffer so với 60s throttle → cần miss ≥ 2 ping liên tiếp mới offline.
HEARTBEAT_TTL = 120
HEARTBEAT_PREFIX = "user:online"


async def heartbeat_ping_service(user_id: int):
    """
    Nhận ping từ user, đánh dấu online trên Redis.

    Lệnh: SETEX user:online:{id} 75 "active"
    Tuyệt đối không đụng Postgres.

    Input:
        user_id (int): ID user từ JWT token.

    Output:
        dict: {"status": 200, "result": "ok"}
    """

    await redis_service.client.setex(
        f"{HEARTBEAT_PREFIX}:{user_id}",
        HEARTBEAT_TTL,
        "active",
    )

    return {"status": 200, "result": "ok"}


async def heartbeat_check_service(user_ids: list[int]):
    """
    Admin check trạng thái online của danh sách users.

    Dùng MGET (Multi-Get) để query hàng loạt trong 1 round-trip,
    không dùng vòng lặp GET.

    Input:
        user_ids (list[int]): Danh sách user ID cần check.

    Output:
        dict: {"status": 200, "result": {user_id: True/False}}
    """

    if not user_ids:
        return {"status": 200, "result": {}}

    keys = [f"{HEARTBEAT_PREFIX}:{uid}" for uid in user_ids]
    values = await redis_service.client.mget(keys)

    result = {
        uid: val is not None
        for uid, val in zip(user_ids, values)
    }

    return {"status": 200, "result": result}


# =============================================================================
# PRIVATE HELPERS
# =============================================================================


async def _get_account_or_404(account_id: int, db) -> Account:
    """Lấy account theo ID, raise 404 nếu không tồn tại."""

    result = await db.execute(
        select(Account).where(Account.id == account_id)
    )
    account = result.scalars().first()

    if not account:
        raise HTTPException(status_code=404, detail="Tài khoản không tồn tại")

    return account


async def _cleanup_account_redis_state(account_id: int, user_id: str, session_ids: list[int]):
    """
    Dọn toàn bộ Redis state liên quan đến account sau khi xóa account.

    Best-effort: lỗi Redis không được làm fail luồng xóa account trong DB.
    """
    client = redis_service.client
    if not client:
        return

    try:
        static_keys = [
            f"session_ver:{account_id}",
            f"{HEARTBEAT_PREFIX}:{account_id}",
            f"{CACHE_KEY_SESSIONS}:{user_id}",
        ]
        await client.delete(*static_keys)

        if session_ids:
            history_keys = [
                f"{CACHE_KEY_HISTORY_PREFIX}:{sid}:{user_id}" for sid in session_ids
            ]
            await client.delete(*history_keys)

        # Dọn thêm key lịch sử còn sót theo pattern
        stale_history_keys = []
        async for key in client.scan_iter(match=f"{CACHE_KEY_HISTORY_PREFIX}:*:{user_id}", count=500):
            stale_history_keys.append(key)

        if stale_history_keys:
            await client.delete(*stale_history_keys)

    except Exception as e:
        logger.warning("[AUTH] Redis cleanup khi xóa account thất bại: %s", e)


def _is_private_ip(ip: str) -> bool:
    """
    Kiểm tra IP có phải private/internal không.

    Private IP ranges: 10.x, 172.16-31.x, 192.168.x, 127.x, ::1, link-local.
    GeoIP không thể tra cứu IP private → cần xử lý riêng.
    """
    try:
        return ipaddress.ip_address(ip).is_private
    except (ValueError, TypeError):
        return False


# IPs của reverse proxy tin cậy — chỉ trust X-Forwarded-For khi peer IP nằm trong list này
_TRUSTED_PROXY_IPS = frozenset(
    ip.strip()
    for ip in os.getenv("TRUSTED_PROXY_IPS", "127.0.0.1,::1").split(",")
    if ip.strip()
)


def _extract_client_ip(request: Request) -> str:
    """
    Trích xuất IP thực của client từ request.

    Ưu tiên đọc header X-Forwarded-For (khi đứng sau reverse proxy),
    fallback về request.client.host.

    Input:
        request (Request): FastAPI Request object.

    Output:
        str: IP address của client.
    """

    peer_ip = request.client.host if request.client else None
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded and peer_ip in _TRUSTED_PROXY_IPS:
        # X-Forwarded-For: client, proxy1, proxy2 → lấy client (đầu tiên)
        return forwarded.split(",")[0].strip()
    return peer_ip or "unknown"


def _parse_user_agent(request: Request) -> dict:
    """
    Parse chuỗi User-Agent để lấy OS, Browser, Device type.

    Sử dụng thư viện user-agents (dựa trên ua-parser).

    Input:
        request (Request): FastAPI Request object.

    Output:
        dict: {os, browser, device_type, user_agent}
    """

    ua_string = request.headers.get("user-agent", "")
    if not ua_string:
        return {"os": None, "browser": None, "device_type": None, "user_agent": None}

    ua = parse_ua(ua_string)

    # Xác định device type
    if ua.is_bot:
        device_type = "Bot"
    elif ua.is_mobile:
        device_type = "Mobile"
    elif ua.is_tablet:
        device_type = "Tablet"
    elif ua.is_pc:
        device_type = "PC"
    else:
        device_type = "Unknown"

    os_str = f"{ua.os.family}"
    if ua.os.version_string:
        os_str += f" {ua.os.version_string}"

    browser_str = f"{ua.browser.family}"
    if ua.browser.version_string:
        browser_str += f" {ua.browser.version_string}"

    return {
        "os": os_str,
        "browser": browser_str,
        "device_type": device_type,
        "user_agent": ua_string[:500],  # Giới hạn độ dài
    }


# =============================================================================
# ADMIN NOTIFICATION SERVICES
# =============================================================================

NOTIFICATION_CHANNEL = "channel:notifications"


async def list_notifications_service(db, limit: int = 50, offset: int = 0):
    """
    Lấy danh sách thông báo bảo mật (mới nhất trước), kèm tên + avatar của account.

    Input:
        db: Database session.
        limit (int): Số lượng tối đa.
        offset (int): Vị trí bắt đầu (phân trang).

    Output:
        dict: {"status": 200, "data": [...], "total": int}
    """
    from sqlalchemy import func as sa_func
    from sqlalchemy.orm import selectinload

    count_result = await db.execute(
        select(sa_func.count()).select_from(AdminNotification)
    )
    total = count_result.scalar()

    result = await db.execute(
        select(AdminNotification)
        .options(selectinload(AdminNotification.account))
        .order_by(AdminNotification.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    notifications = result.scalars().all()

    data = [
        {
            "id": n.id,
            "account_id": n.account_id,
            "account_name": n.account.name if n.account else None,
            "account_email": n.account.email if n.account else None,
            "has_avatar": n.account.avatar is not None if n.account else False,
            "alert_type": n.alert_type,
            "severity": n.severity,
            "title": n.title,
            "detail": n.detail,
            "ip_address": n.ip_address,
            "country": n.country,
            "is_read": n.is_read,
            "created_at": n.created_at.isoformat() if n.created_at else None,
        }
        for n in notifications
    ]

    return {"status": 200, "data": data, "total": total}


async def mark_notification_read_service(notification_id: int, db):
    """
    Đánh dấu thông báo đã đọc.

    Input:
        notification_id (int): ID thông báo.
        db: Database session.

    Output:
        dict: {"status": 200, "result": "ok"}

    Raises:
        HTTPException 404: Không tìm thấy thông báo.
    """

    result = await db.execute(
        select(AdminNotification).where(AdminNotification.id == notification_id)
    )
    notification = result.scalars().first()

    if not notification:
        raise HTTPException(status_code=404, detail="Thông báo không tồn tại")

    notification.is_read = True
    await db.commit()

    return {"status": 200, "result": "ok"}


# --- SSE Connection limiter ---
import asyncio as _asyncio

_sse_active_connections = 0
_sse_lock = _asyncio.Lock()
SSE_MAX_CONNECTIONS = 10          # Tối đa 10 admin SSE cùng lúc
SSE_RETRY_MS = 1_800_000          # Client reconnect sau 30 phút nếu mất kết nối
SSE_KEEPALIVE_INTERVAL = 1800     # Gửi keepalive mỗi 30 phút (1800s) — giảm tải server
SSE_REDIS_RECONNECT_DELAY = 5     # Chờ 5s trước khi retry khi Redis lỗi


async def notifications_sse_generator():
    """
    Async generator cho SSE — subscribe Redis pub/sub channel:notifications.

    Production features:
        - Standalone Redis connection (không chiếm shared pool).
        - Connection limit (tối đa SSE_MAX_CONNECTIONS đồng thời).
        - retry: hint 30s (tránh client flood reconnect khi server restart).
        - event: security_alert (client dùng addEventListener thay vì onmessage).
        - Keepalive comment mỗi 25s (giữ connection sống qua proxy).
        - Auto-recover khi Redis disconnect (log + retry, không crash).
        - Graceful cleanup trong finally block.

    Yields:
        str: SSE frames
    """
    import redis.asyncio as aioredis
    from database.setup_redis import REDIS_URL

    global _sse_active_connections

    # --- Gate: kiểm tra connection limit ---
    async with _sse_lock:
        if _sse_active_connections >= SSE_MAX_CONNECTIONS:
            yield f"retry: {SSE_RETRY_MS}\n"
            yield "event: error\n"
            yield "data: {\"error\": \"Too many SSE connections\"}\n\n"
            return
        _sse_active_connections += 1

    standalone = None
    pubsub = None

    try:
        # --- Gửi retry hint đầu tiên ---
        yield f"retry: {SSE_RETRY_MS}\n\n"

        standalone = aioredis.from_url(
            REDIS_URL, encoding="utf-8", decode_responses=True,
        )
        pubsub = standalone.pubsub()
        await pubsub.subscribe(NOTIFICATION_CHANNEL)

        while True:
            try:
                message = await pubsub.get_message(
                    ignore_subscribe_messages=True,
                    timeout=float(SSE_KEEPALIVE_INTERVAL),
                )

                if message and message["type"] == "message":
                    yield f"event: security_alert\ndata: {message['data']}\n\n"
                else:
                    yield ": keepalive\n\n"

            except (ConnectionError, OSError, Exception) as e:
                logger.warning("[SSE] Redis pub/sub error: %s — reconnecting...", e)
                # Cleanup connection cũ
                try:
                    if pubsub:
                        await pubsub.unsubscribe(NOTIFICATION_CHANNEL)
                        await pubsub.aclose()
                    if standalone:
                        await standalone.aclose()
                except Exception:
                    pass

                # Gửi keepalive để giữ HTTP connection sống trong lúc reconnect
                yield ": reconnecting\n\n"
                await _asyncio.sleep(SSE_REDIS_RECONNECT_DELAY)

                # Tạo connection mới
                try:
                    standalone = aioredis.from_url(
                        REDIS_URL, encoding="utf-8", decode_responses=True,
                    )
                    pubsub = standalone.pubsub()
                    await pubsub.subscribe(NOTIFICATION_CHANNEL)
                    logger.info("[SSE] Redis pub/sub reconnected")
                except Exception as reconnect_err:
                    logger.error("[SSE] Redis reconnect failed: %s", reconnect_err)
                    return  # Thoát generator, client sẽ reconnect sau retry_ms

    finally:
        # --- Cleanup ---
        try:
            if pubsub:
                await pubsub.unsubscribe(NOTIFICATION_CHANNEL)
                await pubsub.aclose()
            if standalone:
                await standalone.aclose()
        except Exception:
            pass

        async with _sse_lock:
            _sse_active_connections = max(0, _sse_active_connections - 1)


async def list_login_history_service(
    db, account_id: int | None = None, limit: int = 10, offset: int = 0,
):
    """
    Lấy lịch sử đăng nhập (mới nhất trước).

    Input:
        db: Database session.
        account_id: Lọc theo account (None = tất cả).
        limit: Số lượng tối đa.
        offset: Phân trang.

    Output:
        dict: {"status": 200, "data": [...], "total": int}
    """
    from sqlalchemy import func as sa_func

    query = select(LoginHistory)
    count_query = select(sa_func.count()).select_from(LoginHistory)

    if account_id is not None:
        query = query.where(LoginHistory.account_id == account_id)
        count_query = count_query.where(LoginHistory.account_id == account_id)

    count_result = await db.execute(count_query)
    total = count_result.scalar()

    result = await db.execute(
        query.order_by(LoginHistory.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    records = result.scalars().all()

    data = [
        {
            "id": r.id,
            "account_id": r.account_id,
            "action": r.action,
            "ip_address": r.ip_address,
            "country": r.country,
            "city": r.city,
            "latitude": r.latitude,
            "longitude": r.longitude,
            "isp": r.isp,
            "asn": r.asn,
            "as_org": r.as_org,
            "os": r.os,
            "browser": r.browser,
            "device_type": r.device_type,
            "is_vpn_or_datacenter": r.is_vpn_or_datacenter,
            "user_agent": r.user_agent,
            "created_at": r.created_at.isoformat() if r.created_at else None,
        }
        for r in records
    ]

    return {"status": 200, "data": data, "total": total}


async def delete_notification_service(notification_id: int, db):
    """
    Xóa một thông báo bảo mật theo ID.

    Input:
        notification_id (int): ID thông báo.
        db: Database session.

    Output:
        dict: {"status": 200, "result": "deleted"}

    Raises:
        HTTPException 404: Không tìm thấy thông báo.
    """
    result = await db.execute(
        select(AdminNotification).where(AdminNotification.id == notification_id)
    )
    notification = result.scalars().first()

    if not notification:
        raise HTTPException(status_code=404, detail="Thông báo không tồn tại")

    await db.delete(notification)
    await db.commit()

    return {"status": 200, "result": "deleted"}


async def delete_all_read_notifications_service(db):
    """
    Xóa tất cả thông báo đã đọc (is_read=True).

    Input:
        db: Database session.

    Output:
        dict: {"status": 200, "deleted": int}
    """
    from sqlalchemy import delete as sa_delete

    result = await db.execute(
        sa_delete(AdminNotification).where(AdminNotification.is_read == True)
    )
    await db.commit()

    return {"status": 200, "deleted": result.rowcount}


async def delete_login_history_entry_service(entry_id: int, db):
    """
    Xóa một bản ghi lịch sử đăng nhập theo ID.

    Input:
        entry_id (int): ID bản ghi LoginHistory.
        db: Database session.

    Output:
        dict: {"status": 200, "result": "deleted"}

    Raises:
        HTTPException 404: Không tìm thấy bản ghi.
    """
    result = await db.execute(
        select(LoginHistory).where(LoginHistory.id == entry_id)
    )
    entry = result.scalars().first()

    if not entry:
        raise HTTPException(status_code=404, detail="Bản ghi không tồn tại")

    await db.delete(entry)
    await db.commit()

    return {"status": 200, "result": "deleted"}


async def delete_login_history_service(account_id: int, db):
    """
    Xóa toàn bộ lịch sử đăng nhập của một tài khoản.

    Input:
        account_id (int): ID tài khoản.
        db: Database session.

    Output:
        dict: {"status": 200, "deleted": int}
    """
    from sqlalchemy import delete as sa_delete

    result = await db.execute(
        sa_delete(LoginHistory).where(LoginHistory.account_id == account_id)
    )
    await db.commit()

    return {"status": 200, "deleted": result.rowcount}
