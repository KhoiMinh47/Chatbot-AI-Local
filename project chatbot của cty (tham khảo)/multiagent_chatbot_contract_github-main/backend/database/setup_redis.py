"""
Module cấu hình kết nối Redis (async).

Cung cấp RedisService (singleton) để:
    - Khởi tạo connection pool async tới Redis server.
    - Quản lý vòng đời kết nối (startup/shutdown).

Redis được dùng làm cache layer cho:
    - Danh sách sessions (key: sessions:all)
    - Lịch sử tin nhắn theo session (key: history:{session_id}:{user_id})

Chiến lược: Cache-Aside (Lazy Loading)
    - Read: Check Redis → miss → query PostgreSQL → set cache với TTL.
    - Write/Delete: Thao tác DB trước → invalidate cache.
"""

import logging
import os

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)

# --- Hằng số cấu hình Redis ---
# Đọc từ biến môi trường, fallback về giá trị Docker Compose mặc định
REDIS_URL = os.getenv(
    "REDIS_URL",
    "redis://:Redis@BachViet2026@redis:6379/0",
)

# Giới hạn connection pool tránh tràn file descriptor
REDIS_MAX_CONNECTIONS = 20

# TTL (giây) cho các loại cache
# Vì đã có invalidation khi write/delete, TTL chỉ là safety net
CACHE_TTL_SESSIONS = 3600      # 1h — sessions list thay đổi thường xuyên hơn
CACHE_TTL_HISTORY = 7200       # 2h — history ít thay đổi sau khi tạo

# Cache key prefixes
CACHE_KEY_SESSIONS = "sessions:all"
CACHE_KEY_HISTORY_PREFIX = "history"


class RedisService:
    """
    Service quản lý kết nối Redis async.

    Sử dụng Singleton pattern — chỉ tạo 1 instance duy nhất
    (`redis_service`) để tất cả module dùng chung connection pool.

    Attributes:
        client (redis.asyncio.Redis | None): Redis client instance.

    Methods:
        initialize_redis(): Tạo connection pool và test ping.
        close(): Đóng connection pool, giải phóng tài nguyên.
    """

    def __init__(self):
        """Khởi tạo với client = None, chờ initialize_redis() được gọi."""
        self.client: aioredis.Redis | None = None

    async def initialize_redis(self):
        """
        Tạo Redis connection pool và kiểm tra kết nối.

        Sử dụng `from_url` để tạo ConnectionPool nội bộ,
        tái sử dụng TCP connections giữa các request.
        `decode_responses=True` tự động decode bytes → str.
        `hiredis` parser (nếu có) tăng tốc parse response ~10x.

        Raises:
            RuntimeError: Nếu không thể kết nối tới Redis.
        """

        try:
            self.client = aioredis.from_url(
                REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                max_connections=REDIS_MAX_CONNECTIONS,
                socket_timeout=5,          # Timeout mỗi lệnh Redis (giây) — tránh treo request
                socket_connect_timeout=3,  # Timeout kết nối TCP tới Redis
            )

            # Test kết nối
            await self.client.ping()
            logger.info("Redis: Connected successfully to %s", REDIS_URL)

        except Exception as e:
            logger.error("Redis: Connection failed — %s", e)
            raise RuntimeError(f"Lỗi khi kết nối Redis: {e}") from e

    async def close(self):
        """Đóng connection pool Redis, giải phóng tài nguyên."""

        if self.client:
            await self.client.aclose()
            logger.info("Redis: Connection pool closed")


# Singleton instance — dùng chung cho toàn bộ ứng dụng
redis_service = RedisService()
