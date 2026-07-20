"""
Module cấu hình kết nối Qdrant vector database.

Cung cấp QdrantService (singleton) để:
    - Khởi tạo collection với cấu hình vector và payload indexes.
    - Quản lý kết nối async tới Qdrant server.

Collection 'rag_data' lưu trữ vector embeddings của các đoạn tài liệu,
kèm theo metadata (payload) để hỗ trợ filtering khi truy vấn RAG.
"""

import asyncio
import logging
import os

from qdrant_client import AsyncQdrantClient
from qdrant_client.http import models

logger = logging.getLogger(__name__)

# --- Hằng số cấu hình Qdrant ---
QDRANT_URL = os.getenv("QDRANT_URL")
COLLECTION_NAME = os.getenv("QDRANT_COLLECTION_NAME", "rag_data")

# Kích thước vector phụ thuộc vào model embedding đang dùng.
# 2048 tương ứng với model Llama-Nemotron-Embed-1b-v2.
VECTOR_SIZE = int(os.getenv("QDRANT_VECTOR_SIZE", "2048"))

# Timeout kết nối Qdrant (giây) — tăng lên nếu server chậm hoặc collection lớn
QDRANT_TIMEOUT = 60.0

# Số segment tối thiểu cho optimizer — 2 là hợp lý cho collection vừa phải,
# giúp cân bằng giữa tốc độ search và tốc độ indexing
DEFAULT_SEGMENT_NUMBER = 2

# Ngưỡng kích hoạt memory-mapped storage (số points),
# khi collection vượt ngưỡng này sẽ chuyển sang đọc từ disk thay vì RAM
MEMMAP_THRESHOLD = 20000


class QdrantService:
    """
    Service quản lý kết nối và khởi tạo Qdrant vector database.

    Sử dụng Singleton pattern — chỉ tạo 1 instance duy nhất (`qdrant_service`)
    để tất cả module dùng chung kết nối.

    Methods:
        initialize_qdrant(): Tạo collection và indexes nếu chưa tồn tại.
        close(): Đóng kết nối client.
    """

    def __init__(self):
        """Khởi tạo AsyncQdrantClient với URL và timeout đã cấu hình."""

        self.client = AsyncQdrantClient(
            url=QDRANT_URL,
            timeout=QDRANT_TIMEOUT,
        )

    async def initialize_qdrant(self):
        """
        Khởi tạo Qdrant: tạo collection và payload indexes nếu chưa tồn tại.

        Được gọi trong lifespan startup của FastAPI (main.py).
        Nếu collection đã tồn tại thì bỏ qua, không tạo lại.

        Raises:
            RuntimeError: Nếu không thể kết nối hoặc tạo collection.
        """

        try:
            collections = await self.client.get_collections()
            collection_names = {c.name for c in collections.collections}

            if COLLECTION_NAME in collection_names:
                logger.info("Qdrant: Collection '%s' đã sẵn sàng", COLLECTION_NAME)
                return

            logger.info("Qdrant: Collection '%s' chưa có, đang tạo...", COLLECTION_NAME)
            await self._create_collection()
            await self._create_payload_indexes()
            logger.info("Qdrant: Khởi tạo hoàn tất!")

        except Exception as e:
            raise RuntimeError(f"Lỗi khi khởi tạo Qdrant: {e}")

    async def _create_collection(self):
        """
        Tạo collection với cấu hình vector COSINE distance.

        Vector được lưu trên disk (on_disk=True) để tiết kiệm RAM
        khi collection lớn, đổi lại tốc độ search chậm hơn chút.
        """

        await self.client.create_collection(
            collection_name=COLLECTION_NAME,
            vectors_config={
                "dense_content": models.VectorParams(
                    size=VECTOR_SIZE,
                    distance=models.Distance.COSINE,
                    on_disk=True,
                ),
            },
            optimizers_config=models.OptimizersConfigDiff(
                default_segment_number=DEFAULT_SEGMENT_NUMBER,
                memmap_threshold=MEMMAP_THRESHOLD,
            ),
        )

    async def _create_payload_indexes(self):
        """
        Tạo payload indexes cho collection để tăng tốc filtering khi truy vấn.

        Chia thành 3 loại index:
            1. INTEGER: Dùng cho hard filter exact match (VD: năm ký kết, loại văn bản).
            2. TEXT (word tokenizer): Dùng cho fuzzy/partial match trên chuỗi
               (VD: tên dự án, tên gói thầu, các bên tham gia).

        Tất cả indexes được tạo song song (asyncio.gather) để giảm thời gian khởi tạo.
        """

        logger.info("Đang tạo Payload Indexes cho '%s'...", COLLECTION_NAME)

        text_index_params = models.TextIndexParams(
            type="text",
            tokenizer=models.TokenizerType.WORD,
            lowercase=True,
        )

        indexes = [
            # --- Hard filter / Exact match (INTEGER) ---
            # Dùng cho các trường có giá trị số, lọc chính xác
            ("loai_van_ban_bit", models.PayloadSchemaType.INTEGER),
            ("nam_ky_ket", models.PayloadSchemaType.INTEGER),
            ("dieu_khoan", models.PayloadSchemaType.INTEGER),

            # --- Fuzzy / Semantic match (TEXT) ---
            # Dùng cho các trường chuỗi, hỗ trợ tìm kiếm từng từ (word tokenizer)
            ("cac_ben_tham_gia", text_index_params),
            ("ten_goi_thau", text_index_params),
            ("ten_du_an", text_index_params),
            ("ten_hang_muc", text_index_params),
            ("ten_do_an", text_index_params),
            ("dia_diem_thuc_hien", text_index_params),
            ("so_tien", text_index_params),
            ("moc_thoi_gian", text_index_params),
            ("ty_le_phan_tram", text_index_params),
            ("dieu_khoan_lien_ket", text_index_params),

            # --- Exact match trên chuỗi (TEXT) ---
            # Dùng cho các trường cần khớp chính xác nguyên cụm
            ("ma_hop_dong", text_index_params),
            ("loai_van_ban_str", text_index_params),
        ]

        # Tạo tất cả indexes song song để giảm thời gian khởi tạo
        tasks = [
            self.client.create_payload_index(
                collection_name=COLLECTION_NAME,
                field_name=field_name,
                field_schema=field_schema,
            )
            for field_name, field_schema in indexes
        ]

        await asyncio.gather(*tasks)

        logger.info("Payload Indexes đã được tạo xong")

    async def close(self):
        """Đóng kết nối Qdrant client, giải phóng tài nguyên."""

        await self.client.close()
        logger.info("Qdrant client đã đóng kết nối")


# Singleton instance — dùng chung cho toàn bộ ứng dụng
qdrant_service = QdrantService()
