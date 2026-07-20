"""
Module chứa các hàm tiện ích cho pipeline upload template hợp đồng.

Các hàm:
    - parse_template_docling: Gọi Docling API parse file sang markdown.
    - save_template_file: Lưu file local và upload MinIO.
"""

import io
import logging
import os

import httpx

from database.setup_minio import minio_service, MINIO_BUCKET

logger = logging.getLogger(__name__)

# --- Hằng số ---
FOLDER_PATH_TEMPLATE = os.getenv("FOLDER_PATH_TEMPLATE", "database/storage/template")

DOCLING_URL = os.getenv("MARKER_URL")
DOCLING_REQUEST_TIMEOUT = 300.0
DOCLING_CONNECT_TIMEOUT = 10.0


# =============================================================================
# HÀM TIỆN ÍCH
# =============================================================================


async def parse_template_docling(filename: str, file_content: bytes) -> str:
    """
    Gọi Docling (parse-data service) để parse file DOCX template sang markdown.

    Input:
        filename (str): Tên file template.
        file_content (bytes): Nội dung file template.

    Output:
        str: Nội dung markdown sau khi parse.

    Raises:
        RuntimeError: Nếu Docling API trả lỗi hoặc không parse được.
    """

    content_type = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    files = {"files": (filename, file_content, content_type)}

    timeout_config = httpx.Timeout(
        DOCLING_REQUEST_TIMEOUT,
        connect=DOCLING_CONNECT_TIMEOUT,
    )

    async with httpx.AsyncClient(timeout=timeout_config) as client:
        response = await client.post(DOCLING_URL, files=files)
        response.raise_for_status()
        data = response.json()

    if data.get("status") != 200:
        raise RuntimeError(f"Docling API lỗi: {data.get('description', 'Unknown error')}")

    results = data.get("result", [])
    if not results or not results[0].get("content"):
        raise RuntimeError("Docling API trả về nội dung rỗng.")

    markdown_content = results[0]["content"]
    logger.info("Docling parse thành công: %s (%d ký tự)", filename, len(markdown_content))

    return markdown_content


def save_template_file(filename: str, file_content: bytes) -> dict:
    """
    Lưu file template xuống local và upload lên MinIO.

    Input:
        filename (str): Tên file template.
        file_content (bytes): Nội dung file template.

    Output:
        dict: {"file_path": str, "minio_path": str}

    Raises:
        RuntimeError: Nếu lưu file hoặc upload MinIO thất bại.
    """

    file_path = os.path.join(FOLDER_PATH_TEMPLATE, filename)

    os.makedirs(FOLDER_PATH_TEMPLATE, exist_ok=True)
    with open(file_path, "wb") as f:
        f.write(file_content)

    minio_service.client.put_object(
        bucket_name=MINIO_BUCKET,
        object_name=filename,
        data=io.BytesIO(file_content),
        length=len(file_content),
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    minio_path = f"{MINIO_BUCKET}/{filename}"
    logger.info("Đã lưu template: local=%s, minio=%s", file_path, minio_path)

    return {"file_path": file_path, "minio_path": minio_path}
