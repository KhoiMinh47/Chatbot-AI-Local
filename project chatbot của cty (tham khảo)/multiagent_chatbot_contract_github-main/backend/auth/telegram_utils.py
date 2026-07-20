"""
Module gửi thông báo Telegram cho các sự kiện bảo mật/xác thực.

Nguồn cấu hình lấy trực tiếp từ database:
    - TelegramBotConfig: chọn duy nhất bot đang active.
    - TelegramRecipientConfig: gửi tới toàn bộ chat_id đang active.
"""

import logging
from typing import Any

import httpx
from sqlalchemy import select

from database.setup_postgres import SessionLocal
from database.table.table_postgres import TelegramBotConfig, TelegramRecipientConfig

logger = logging.getLogger(__name__)


async def _get_active_bot_and_recipients() -> tuple[TelegramBotConfig | None, list[TelegramRecipientConfig]]:
    """Đọc cấu hình Telegram active từ DB."""
    try:
        async with SessionLocal() as db:
            bot_result = await db.execute(
                select(TelegramBotConfig)
                .where(TelegramBotConfig.is_active.is_(True))
                .order_by(TelegramBotConfig.id.desc())
            )
            bot = bot_result.scalars().first()

            recipient_result = await db.execute(
                select(TelegramRecipientConfig)
                .where(TelegramRecipientConfig.is_active.is_(True))
                .order_by(TelegramRecipientConfig.id.desc())
            )
            recipients = recipient_result.scalars().all()

            return bot, recipients
    except Exception as e:
        logger.warning("[TELEGRAM] Không thể đọc cấu hình Telegram từ DB: %s", e)
        return None, []


async def send_verified_user_notification(account_payload: dict[str, Any]) -> None:
    """
    Gửi thông báo khi người dùng verify email thành công.

    account_payload kỳ vọng có các key:
        - id
        - email
        - name
    """
    bot, recipients = await _get_active_bot_and_recipients()
    if not bot:
        logger.warning("[TELEGRAM] Không có bot active. Bỏ qua gửi thông báo verify.")
        return

    if not recipients:
        logger.info("[TELEGRAM] Không có recipient active. Bỏ qua gửi thông báo verify.")
        return

    user_id = account_payload.get("id", "?")
    user_email = account_payload.get("email", "unknown")
    user_name = account_payload.get("name", "N/A")

    message = (
        "✅ *Xác thực email thành công*\n"
        f"- ID: `{user_id}`\n"
        f"- Name: {user_name}\n"
        f"- Email: {user_email}"
    )

    endpoint = f"https://api.telegram.org/bot{bot.bot_token}/sendMessage"
    timeout = httpx.Timeout(10.0)

    async with httpx.AsyncClient(timeout=timeout) as client:
        for recipient in recipients:
            payload = {
                "chat_id": recipient.chat_id,
                "text": message,
                "parse_mode": "Markdown",
            }
            try:
                resp = await client.post(endpoint, json=payload)
                if resp.status_code >= 400:
                    logger.warning(
                        "[TELEGRAM] Gửi thất bại chat_id=%s status=%s body=%s",
                        recipient.chat_id,
                        resp.status_code,
                        resp.text,
                    )
            except Exception as e:
                logger.warning(
                    "[TELEGRAM] Gửi thất bại chat_id=%s: %s",
                    recipient.chat_id,
                    e,
                )
