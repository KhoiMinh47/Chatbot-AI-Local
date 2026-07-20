"""
Module tiện ích xác thực (Authentication Utilities).

Cung cấp các hàm:
    - hash_password / verify_password: Mã hóa và kiểm tra mật khẩu (bcrypt).
    - create_token / decode_token: Tạo và giải mã JWT token.
    - generate_random_password: Tạo mật khẩu ngẫu nhiên.

Tất cả hằng số đọc từ biến môi trường (.env).
"""

import os
import secrets
import string
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt

# --- Hằng số JWT (đọc từ .env) ---
JWT_SECRET_KEY = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
JWT_ALGORITHM = os.getenv("JWT_ALGORITHM", "HS256")
JWT_EXPIRE_DAYS = int(os.getenv("JWT_EXPIRE_DAYS", "30"))

# Độ dài mật khẩu ngẫu nhiên khi reset
RANDOM_PASSWORD_LENGTH = 12


def hash_password(plain: str) -> str:
    """
    Hash mật khẩu bằng bcrypt (12 rounds).

    Thuật toán:
        - bcrypt tự tạo salt ngẫu nhiên (16 bytes).
        - 12 rounds (2^12 = 4096 iterations) — ~0.3s, đủ chậm
          để brute force không khả thi.

    Input:
        plain (str): Mật khẩu gốc.

    Output:
        str: Chuỗi hash bcrypt (60 chars).
    """

    return bcrypt.hashpw(
        plain.encode("utf-8"), bcrypt.gensalt()
    ).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """
    Kiểm tra mật khẩu có khớp với hash không.

    Input:
        plain (str): Mật khẩu người dùng nhập.
        hashed (str): Hash đã lưu trong database.

    Output:
        bool: True nếu khớp, False nếu sai.
    """

    return bcrypt.checkpw(
        plain.encode("utf-8"), hashed.encode("utf-8")
    )


def create_token(
    account_id: int,
    roles: list[str],
    purpose: str = "access",
    expire_days: int | None = None,
    login_ip: str | None = None,
    session_ver: int | None = None,
) -> str:
    """
    Tạo JWT token.

    Payload chứa:
        - sub: account_id (subject).
        - roles: danh sách quyền (để middleware check nhanh,
          không cần query DB).
        - purpose: mục đích token (access / verify / reset).
        - login_ip: IP lúc đăng nhập (để middleware so sánh fast-path).
        - session_ver: version session hiện tại (để kick old sessions).
        - exp: thời điểm hết hạn.
        - iat: thời điểm tạo.

    Input:
        account_id (int): ID tài khoản.
        roles (list[str]): Danh sách tên quyền.
        purpose (str): Mục đích token. Mặc định "access".
        expire_days (int | None): Số ngày hết hạn.
            None → dùng JWT_EXPIRE_DAYS từ .env.
        login_ip (str | None): IP lúc đăng nhập. Lưu vào token để middleware
            so sánh fast-path (không cần query DB mỗi request).
        session_ver (int | None): Version session. Tăng mỗi lần login mới để
            invalidate tất cả token cũ (single active session).

    Output:
        str: JWT token string.
    """

    if expire_days is None:
        expire_days = JWT_EXPIRE_DAYS

    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(account_id),
        "roles": roles,
        "purpose": purpose,
        "exp": now + timedelta(days=expire_days),
        "iat": now,
    }

    if login_ip:
        payload["login_ip"] = login_ip

    if session_ver is not None:
        payload["session_ver"] = session_ver

    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)


def decode_token(token: str) -> dict:
    """
    Giải mã và validate JWT token.

    Tự động kiểm tra:
        - Chữ ký hợp lệ (SECRET_KEY).
        - Token chưa hết hạn (exp).

    Input:
        token (str): JWT token string.

    Output:
        dict: Payload đã giải mã.

    Raises:
        jwt.ExpiredSignatureError: Token đã hết hạn.
        jwt.InvalidTokenError: Token không hợp lệ.
    """

    payload = jwt.decode(
        token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM]
    )
    # Chuyển sub về int để dùng như account_id
    payload["sub"] = int(payload["sub"])
    return payload


def generate_random_password(length: int = RANDOM_PASSWORD_LENGTH) -> str:
    """
    Tạo mật khẩu ngẫu nhiên an toàn.

    Bảo đảm có ít nhất: 1 chữ hoa, 1 chữ thường, 1 số, 1 ký tự đặc biệt.
    Sử dụng secrets module (cryptographically secure).

    Input:
        length (int): Độ dài mật khẩu. Mặc định 12.

    Output:
        str: Mật khẩu ngẫu nhiên.
    """

    alphabet = string.ascii_letters + string.digits + "!@#$%&*"

    while True:
        password = "".join(secrets.choice(alphabet) for _ in range(length))

        # Đảm bảo ít nhất 1 ký tự mỗi loại
        has_upper = any(c.isupper() for c in password)
        has_lower = any(c.islower() for c in password)
        has_digit = any(c.isdigit() for c in password)
        has_special = any(c in "!@#$%&*" for c in password)

        if has_upper and has_lower and has_digit and has_special:
            return password
