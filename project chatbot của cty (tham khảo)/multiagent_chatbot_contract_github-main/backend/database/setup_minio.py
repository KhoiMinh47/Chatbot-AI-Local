"""
Module cấu hình kết nối MinIO object storage.

Cung cấp MinioService (singleton) để:
    - Khởi tạo kết nối MinIO.
    - Tạo bucket nếu chưa tồn tại khi server startup.
"""

import logging
import os

from minio import Minio
from minio.error import S3Error

logger = logging.getLogger(__name__)

# --- Hằng số cấu hình MinIO (đọc từ .env) ---
MINIO_ENDPOINT = os.getenv("MINIO_ENDPOINT")
MINIO_ACCESS_KEY = os.getenv("MINIO_ACCESS_KEY")
MINIO_SECRET_KEY = os.getenv("MINIO_SECRET_KEY")
MINIO_SECURE = os.getenv("MINIO_SECURE", "false").lower() == "true"
MINIO_BUCKET = os.getenv("MINIO_BUCKET", "contract-templates")
MINIO_CONTRACT_BUCKET = os.getenv("MINIO_CONTRACT_BUCKET", "contracts")
MINIO_RAW_BUCKET = os.getenv("MINIO_RAW_BUCKET", "raw-files")


class MinioService:
    """
    Service quản lý kết nối và khởi tạo MinIO.
    """

    def __init__(self):
        self.client = Minio(
            endpoint=MINIO_ENDPOINT,
            access_key=MINIO_ACCESS_KEY,
            secret_key=MINIO_SECRET_KEY,
            secure=MINIO_SECURE,
        )

    async def initialize_minio(self):
        """
        Khởi tạo MinIO: kiểm tra và tạo bucket hợp đồng & rag nếu chưa tồn tại.
        """

        try:
            # Bucket Hợp đồng
            exists = self.client.bucket_exists(MINIO_BUCKET)
            if not exists:
                self.client.make_bucket(MINIO_BUCKET)
                logger.info("MinIO: Đã tạo bucket '%s'", MINIO_BUCKET)
            else:
                logger.info("MinIO: Bucket '%s' đã tồn tại", MINIO_BUCKET)
                
            # Bucket Contracts (file hợp đồng đã tạo)
            exists_contract = self.client.bucket_exists(MINIO_CONTRACT_BUCKET)
            if not exists_contract:
                self.client.make_bucket(MINIO_CONTRACT_BUCKET)
                logger.info("MinIO: Đã tạo bucket '%s'", MINIO_CONTRACT_BUCKET)
            else:
                logger.info("MinIO: Bucket '%s' đã tồn tại", MINIO_CONTRACT_BUCKET)

            # Bucket RAG Files
            exists_raw = self.client.bucket_exists(MINIO_RAW_BUCKET)
            if not exists_raw:
                self.client.make_bucket(MINIO_RAW_BUCKET)
                logger.info("MinIO: Đã tạo bucket '%s'", MINIO_RAW_BUCKET)
            else:
                logger.info("MinIO: Bucket '%s' đã tồn tại", MINIO_RAW_BUCKET)
                
        except S3Error as e:
            raise RuntimeError(f"Lỗi khi khởi tạo MinIO: {e}") from e
        except Exception as e:
            raise RuntimeError(f"Không thể kết nối MinIO: {e}") from e

    async def close(self):
        logger.info("MinIO client lifecycle completed")


# Singleton instance
minio_service = MinioService()
