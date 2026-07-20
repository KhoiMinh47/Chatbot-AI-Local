"""
Module gom tất cả router của ứng dụng vào một APIRouter duy nhất.

Mỗi controller được gắn với một prefix riêng, giúp tổ chức
API endpoints theo nhóm chức năng (health, contracts, rags).
Router này được import trong main.py và gắn vào app với prefix /api/v1.
"""

from fastapi import APIRouter

from controller import (
    auth_controller,
    contract_controller,
    rag_controller,
    analytics_controller,
    admin_controller,
)

# Router gốc - tập trung toàn bộ sub-router của các controller
api_router = APIRouter()

# Gắn từng controller với prefix và tag tương ứng cho Swagger UI
api_router.include_router(
    auth_controller.router, prefix="/auth", tags=["authentication"]
)
api_router.include_router(
    contract_controller.router, prefix="/contracts", tags=["contract"]
)
api_router.include_router(
    rag_controller.router, prefix="/rags", tags=["rag-service"]
)
api_router.include_router(
    analytics_controller.router, prefix="/analytics", tags=["analytics"]
)
api_router.include_router(
    admin_controller.router, prefix="/admin", tags=["admin-settings"]
)