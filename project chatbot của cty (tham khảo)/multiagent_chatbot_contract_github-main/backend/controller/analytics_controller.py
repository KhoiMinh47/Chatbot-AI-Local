from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
import logging

from database.setup_postgres import get_db
from database.table.table_postgres import Account, session as SessionModel, history_mess, document_fulltext
from auth.auth_middleware import require_roles, get_current_user
from service.prometheus_service import get_system_metrics

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/admin")
async def get_admin_analytics(
    db: AsyncSession = Depends(get_db),
    # Require root role for admin analytics
    current_user: Account = Depends(require_roles(["root"]))
):
    """
    API lấy dữ liệu thống kê tổng cục cho màn hình Analytics của Admin.
    """
    try:
        total_users_result = await db.execute(select(func.count(Account.id)))
        total_users = total_users_result.scalar() or 0

        total_chats_result = await db.execute(select(func.count(SessionModel.id)))
        total_chats = total_chats_result.scalar() or 0

        total_messages_result = await db.execute(select(func.count(history_mess.id)))
        total_messages = total_messages_result.scalar() or 0
        
        # Estimate total tokens by summing lengths of all messages
        # Note: 1 token ≈ 4 chars for Vietnamese on average
        total_chars_result = await db.execute(select(func.sum(func.length(history_mess.mess))))
        total_chars_query = total_chars_result.scalar() or 0
        total_tokens = total_chars_query // 4
        
        total_files_result = await db.execute(select(func.count(document_fulltext.id)))
        total_files = total_files_result.scalar() or 0

        return {
            "users": total_users,
            "chats": total_chats,
            "messages": total_messages,
            "tokens": total_tokens,
            "files": total_files,
            "success": True
        }
    except Exception as e:
        logger.error(f"Error fetching admin analytics: {e}")
        raise HTTPException(status_code=500, detail="Không thể tải dữ liệu thống kê")


@router.get("/system-metrics")
async def get_admin_system_metrics(
    current_user: Account = Depends(require_roles(["root"]))
):
    """
    API lấy dữ liệu tài nguyên hệ thống từ Prometheus cho Admin.
    """
    try:
        metrics = await get_system_metrics()
        return {
            "metrics": metrics,
            "success": True
        }
    except Exception as e:
        logger.error(f"Error fetching system metrics: {e}")
        raise HTTPException(status_code=500, detail="Không thể tải dữ liệu tài nguyên hệ thống")


@router.get("/me")
async def get_user_analytics(
    db: AsyncSession = Depends(get_db),
    current_user: Account = Depends(get_current_user)
):
    """
    API lấy dữ liệu thống kê cá nhân cho User đang đăng nhập.
    """
    try:
        user_id_str = str(current_user.id)
        
        my_chats_result = await db.execute(select(func.count(SessionModel.id)).filter(SessionModel.user_id == user_id_str))
        my_chats = my_chats_result.scalar() or 0

        my_messages_result = await db.execute(select(func.count(history_mess.id)).filter(history_mess.user_id == user_id_str))
        my_messages = my_messages_result.scalar() or 0
        
        my_chars_result = await db.execute(select(func.sum(func.length(history_mess.mess))).filter(history_mess.user_id == user_id_str))
        total_chars_query = my_chars_result.scalar() or 0
        my_tokens = total_chars_query // 4
        
        my_files = 0

        return {
            "my_chats": my_chats,
            "my_messages": my_messages,
            "my_tokens": my_tokens,
            "my_files": my_files,
            "success": True
        }
    except Exception as e:
        logger.error(f"Error fetching user analytics for {current_user.id}: {e}")
        raise HTTPException(status_code=500, detail="Không thể tải dữ liệu thống kê cá nhân")
