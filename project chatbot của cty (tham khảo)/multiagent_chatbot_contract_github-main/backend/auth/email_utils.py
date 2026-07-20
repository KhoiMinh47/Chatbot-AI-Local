"""
Module gửi email xác thực và reset mật khẩu.

Sử dụng aiosmtplib (async SMTP) để gửi email không blocking.
Hỗ trợ Google Workspace (smtp.gmail.com:587, STARTTLS).

Cung cấp các hàm:
    - send_verification_email: Gửi link xác thực email.
    - send_reset_password_email: Gửi mật khẩu mới qua email.
"""

import logging
import os
from dataclasses import dataclass
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from urllib.parse import quote

import aiosmtplib
from sqlalchemy import select

logger = logging.getLogger(__name__)

FRONTEND_URL = os.getenv("FRONTEND_URL", "").rstrip("/")
VERIFY_TOKEN_EXPIRE_MINUTES = int(os.getenv("VERIFY_TOKEN_EXPIRE_MINUTES", "60"))
DEFAULT_LOGO_URL = "https://raw.githubusercontent.com/baolnq-ai/images/main/snowflake.png"
LOGO_URL = "{MAIL_LOGO_URL}"


@dataclass
class ActiveMailConfig:
    host: str
    port: int
    user: str
    password: str
    from_email: str
    from_name: str
    logo_url: str


async def _get_active_mail_config() -> ActiveMailConfig | None:
    """
    Lấy cấu hình SMTP đang active từ database.
    Không fallback về .env để đảm bảo hệ thống đồng nhất với cấu hình Admin.
    """
    from database.setup_postgres import SessionLocal
    from database.table.table_postgres import MailServerConfig

    try:
        async with SessionLocal() as db:
            result = await db.execute(
                select(MailServerConfig)
                .where(MailServerConfig.is_active.is_(True))
                .order_by(MailServerConfig.id.desc())
            )
            config = result.scalars().first()
    except Exception as e:
        logger.warning("[EMAIL] Lỗi khi đọc cấu hình mail từ DB: %s", e)
        return None

    if not config:
        logger.warning("[EMAIL] Không có cấu hình mail active trong DB.")
        return None

    required_fields = [
        config.host,
        config.port,
        config.user,
        config.password,
        config.from_email,
        config.from_name,
    ]
    if any(v in (None, "") for v in required_fields):
        logger.warning("[EMAIL] Cấu hình mail active thiếu thông tin bắt buộc.")
        return None

    return ActiveMailConfig(
        host=config.host,
        port=config.port,
        user=config.user,
        password=config.password,
        from_email=config.from_email,
        from_name=config.from_name,
        logo_url=config.logo_url or DEFAULT_LOGO_URL,
    )


async def _send_email(
    mail_config: ActiveMailConfig, to_email: str, subject: str, html_body: str
):
    """
    Hàm nội bộ gửi email qua SMTP (async).
    """
    message = MIMEMultipart("alternative")
    message["From"] = f"{mail_config.from_name} <{mail_config.from_email}>"
    message["To"] = to_email
    message["Subject"] = subject
    message.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        is_ssl_smtp = mail_config.port == 465
        await aiosmtplib.send(
            message,
            hostname=mail_config.host,
            port=mail_config.port,
            username=mail_config.user,
            password=mail_config.password,
            use_tls=is_ssl_smtp,
            start_tls=not is_ssl_smtp,
        )
        logger.info("[EMAIL] Đã gửi email tới %s: %s", to_email, subject)
    except Exception as e:
        logger.warning("[EMAIL] Gửi email thất bại tới %s: %s", to_email, e)


def _resolve_verify_frontend_url() -> str:
    """
    Resolve domain frontend để tạo link verify cho email.

    Chuẩn production: bắt buộc FRONTEND_URL được cấu hình rõ ràng.
    """
    if FRONTEND_URL:
        return FRONTEND_URL
    return ""


def _verify_ttl_label() -> str:
    """Format TTL token verify để render trong email."""
    minutes = max(1, VERIFY_TOKEN_EXPIRE_MINUTES)
    if minutes % 60 == 0:
        hours = minutes // 60
        return f"{hours} giờ"
    return f"{minutes} phút"


async def send_verification_email(to_email: str, token: str):
    """
    Gửi email xác thực tài khoản với nút bấm.

    Email chứa link frontend dạng:
        {FRONTEND_URL}/verify-email#vt={opaque_token}

    Input:
        to_email (str): Email cần xác thực.
        token (str): Opaque one-time token xác thực email.
    """

    verify_frontend_base = _resolve_verify_frontend_url()
    if not verify_frontend_base:
        logger.warning("[EMAIL] Thiếu FRONTEND_URL, không thể gửi link xác thực.")
        return

    mail_config = await _get_active_mail_config()
    if not mail_config:
        return

    verify_url = f"{verify_frontend_base}/verify-email#vt={quote(token, safe='')}"

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:'Segoe UI',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:40px 16px;">
<tr><td align="center">
<table width="580" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

    <!-- Top accent bar -->
    <tr><td style="height:4px;background:linear-gradient(90deg,#f59e0b,#f97316,#ea580c);"></td></tr>

    <!-- Header with logo -->
    <tr><td style="padding:36px 44px 0;text-align:center;">
        <table cellpadding="0" cellspacing="0" align="center"><tr>
            <td style="line-height:1;"><img src="{LOGO_URL}" alt="NTC" width="40" height="40" style="display:block;border:0;border-radius:8px;"></td>
            <td style="padding-left:12px;">
                <span style="font-size:24px;font-weight:800;color:#1c1917;letter-spacing:-0.5px;">ChatBot</span>
                <span style="font-size:24px;font-weight:800;color:#ea580c;letter-spacing:-0.5px;"> NTC</span>
            </td>
        </tr></table>
    </td></tr>

    <!-- Divider -->
    <tr><td style="padding:20px 44px 0;"><div style="border-top:1px solid #e5e5e5;"></div></td></tr>

    <!-- Content -->
    <tr><td style="padding:28px 44px 0;">
        <h1 style="color:#1c1917;font-size:22px;font-weight:700;margin:0 0 12px;line-height:1.3;">
            Xác thực email của bạn
        </h1>
        <p style="color:#525252;font-size:14px;line-height:1.75;margin:0 0 28px;">
            Cảm ơn bạn đã đăng ký tài khoản tại <strong style="color:#1c1917;">ChatBot NTC</strong>.<br>
            Nhấn nút bên dưới để xác thực và kích hoạt tài khoản:
        </p>
    </td></tr>

    <!-- CTA Button -->
    <tr><td style="padding:0 44px;text-align:center;">
        <table cellpadding="0" cellspacing="0" align="center"><tr><td style="
            background:linear-gradient(135deg,#f59e0b,#ea580c);
            border-radius:10px;
        ">
            <a href="{verify_url}" style="
                display:inline-block;padding:14px 48px;
                color:#ffffff;text-decoration:none;
                font-size:15px;font-weight:700;
                letter-spacing:0.3px;
            ">Xác thực ngay &#8594;</a>
        </td></tr></table>
    </td></tr>

    <!-- Timer notice -->
    <tr><td style="padding:28px 44px 0;">
        <table width="100%" cellpadding="0" cellspacing="0" style="
            background:#fefce8;border-radius:8px;
            border-left:3px solid #f59e0b;
        "><tr><td style="padding:14px 18px;">
            <p style="color:#713f12;font-size:13px;margin:0;line-height:1.6;">
                &#9201; Link có hiệu lực <strong>{_verify_ttl_label()}</strong> kể từ khi nhận email.<br>
                Bỏ qua email này nếu bạn không đăng ký tài khoản.
            </p>
        </td></tr></table>
    </td></tr>

    <!-- Footer -->
    <tr><td style="padding:32px 44px;">
        <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td style="border-top:1px solid #e5e5e5;padding-top:20px;">
                <p style="color:#a3a3a3;font-size:11px;text-align:center;margin:0;line-height:1.6;">
                    &#169; 2026 ChatBot NTC &#183; Nền tảng trợ lý thông minh<br>
                    <span style="color:#d4d4d4;">Email này được gửi tự động, vui lòng không trả lời.</span>
                </p>
            </td>
        </tr></table>
    </td></tr>

</table>
</td></tr>
</table>
</body></html>"""

    await _send_email(
        mail_config,
        to_email,
        "Xác thực tài khoản — ChatBot NTC",
        html.replace(LOGO_URL, mail_config.logo_url),
    )


async def send_reset_password_email(to_email: str, new_password: str):
    """
    Gửi email chứa mật khẩu mới.

    Sau khi nhận, người dùng đăng nhập bằng mật khẩu mới
    và tự đổi lại trong phần cài đặt.

    Input:
        to_email (str): Email người nhận.
        new_password (str): Mật khẩu mới (plain text).
    """

    mail_config = await _get_active_mail_config()
    if not mail_config:
        return

    html = f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"></head>
<body style="margin:0;padding:0;background:#f4f4f5;font-family:'Segoe UI',Helvetica,Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="background:#f4f4f5;padding:40px 16px;">
<tr><td align="center">
<table width="580" cellpadding="0" cellspacing="0" style="background:#ffffff;border-radius:16px;overflow:hidden;box-shadow:0 4px 24px rgba(0,0,0,0.08);">

    <!-- Top accent bar -->
    <tr><td style="height:4px;background:linear-gradient(90deg,#f59e0b,#f97316,#ea580c);"></td></tr>

    <!-- Header with logo -->
    <tr><td style="padding:36px 44px 0;text-align:center;">
        <table cellpadding="0" cellspacing="0" align="center"><tr>
            <td style="line-height:1;"><img src="{LOGO_URL}" alt="NTC" width="40" height="40" style="display:block;border:0;border-radius:8px;"></td>
            <td style="padding-left:12px;">
                <span style="font-size:24px;font-weight:800;color:#1c1917;letter-spacing:-0.5px;">ChatBot</span>
                <span style="font-size:24px;font-weight:800;color:#ea580c;letter-spacing:-0.5px;"> NTC</span>
            </td>
        </tr></table>
    </td></tr>

    <!-- Divider -->
    <tr><td style="padding:20px 44px 0;"><div style="border-top:1px solid #e5e5e5;"></div></td></tr>

    <!-- Content -->
    <tr><td style="padding:28px 44px 0;">
        <h1 style="color:#1c1917;font-size:22px;font-weight:700;margin:0 0 12px;line-height:1.3;">
            &#128272; Mật khẩu mới của bạn
        </h1>
        <p style="color:#525252;font-size:14px;line-height:1.75;margin:0 0 24px;">
            Yêu cầu đặt lại mật khẩu đã được xử lý.<br>
            Sử dụng mật khẩu bên dưới để đăng nhập vào <strong style="color:#1c1917;">ChatBot NTC</strong>:
        </p>
    </td></tr>

    <!-- Password display -->
    <tr><td style="padding:0 44px;text-align:center;">
        <table cellpadding="0" cellspacing="0" align="center"><tr><td style="
            background:#1c1917;
            border:2px solid #ea580c;
            border-radius:10px;
            padding:18px 36px;
        ">
            <span style="font-family:'Courier New',Consolas,monospace;font-size:24px;font-weight:800;color:#fbbf24;letter-spacing:3px;">{new_password}</span>
        </td></tr></table>
    </td></tr>

    <!-- Warning -->
    <tr><td style="padding:24px 44px 0;">
        <table width="100%" cellpadding="0" cellspacing="0" style="
            background:#fef2f2;border-radius:8px;
            border-left:3px solid #ef4444;
        "><tr><td style="padding:14px 18px;">
            <p style="color:#991b1b;font-size:13px;font-weight:600;margin:0;">
                &#9888;&#65039; Hãy đăng nhập và đổi mật khẩu ngay sau khi nhận email này.
            </p>
        </td></tr></table>
    </td></tr>

    <!-- Info note -->
    <tr><td style="padding:16px 44px 0;">
        <p style="color:#737373;font-size:13px;margin:0;line-height:1.6;">
            Nếu bạn không yêu cầu đặt lại mật khẩu, vui lòng liên hệ quản trị viên ngay lập tức.
        </p>
    </td></tr>

    <!-- Footer -->
    <tr><td style="padding:32px 44px;">
        <table width="100%" cellpadding="0" cellspacing="0"><tr>
            <td style="border-top:1px solid #e5e5e5;padding-top:20px;">
                <p style="color:#a3a3a3;font-size:11px;text-align:center;margin:0;line-height:1.6;">
                    &#169; 2026 ChatBot NTC &#183; Nền tảng trợ lý thông minh<br>
                    <span style="color:#d4d4d4;">Email này được gửi tự động, vui lòng không trả lời.</span>
                </p>
            </td>
        </tr></table>
    </td></tr>

</table>
</td></tr>
</table>
</body></html>"""

    await _send_email(
        mail_config,
        to_email,
        "Mật khẩu mới — ChatBot NTC",
        html.replace(LOGO_URL, mail_config.logo_url),
    )
