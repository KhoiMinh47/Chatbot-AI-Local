"""
Module cấu hình kết nối PostgreSQL bằng SQLAlchemy async.

Sử dụng asyncpg driver để kết nối async tới PostgreSQL.
Cung cấp engine, session factory và dependency `get_db()`
để inject database session vào các endpoint FastAPI.
"""

import os

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

# Connection string cho PostgreSQL async
# Đọc từ biến môi trường, fallback về giá trị Docker Compose mặc định
SQLALCHEMY_DATABASE_URL = os.getenv(
    "SQLALCHEMY_DATABASE_URL",
    "postgresql+asyncpg://bao:3568@postgres:5432/multiangent_db",
)

# echo=True sẽ log toàn bộ SQL query ra console, chỉ bật khi debug
engine = create_async_engine(
    SQLALCHEMY_DATABASE_URL, echo=False,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=1800,
)

# expire_on_commit=False bắt buộc với AsyncSession,
# vì sau commit object sẽ bị expired và truy cập lại attribute
# sẽ trigger lazy load — không được phép trong async context
SessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)

# Base class cho tất cả SQLAlchemy models
Base = declarative_base()


async def get_db():
    """
    Dependency tạo database session cho mỗi request.

    Sử dụng async context manager để đảm bảo session
    luôn được đóng sau khi request hoàn thành.

    Output:
        AsyncGenerator[AsyncSession]: Database session.
    """

    async with SessionLocal() as db:
        yield db