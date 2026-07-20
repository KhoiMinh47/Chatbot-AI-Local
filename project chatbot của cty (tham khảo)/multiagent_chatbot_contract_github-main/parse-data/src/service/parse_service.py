"""
Module xử lý logic parse đa định dạng bằng Docling.

Chứa các hàm parse file đơn lẻ và parse nhiều file,
với error handling chi tiết cho từng bước. Sử dụng asyncio.to_thread để tránh block Event Loop.
"""

import gc
import os
import uuid
import logging
import tempfile
import asyncio
from typing import List, Dict, Any

from fastapi import UploadFile

from src.config.docling_config import document_converter
from src.model.response_model import ParseResultItem


# Cấu hình logging cho module này
logger = logging.getLogger(__name__)

# Thư mục tạm để lưu file upload trước khi parse
TEMP_DIR = tempfile.gettempdir()


async def save_temp_file(file: UploadFile) -> str:
    """
    Lưu file upload vào thư mục tạm.

    Input:
        file (UploadFile): File được upload từ client.

    Output:
        str: Đường dẫn tuyệt đối của file tạm đã lưu.

    Raises:
        IOError: Khi không thể ghi file vào disk.
    """

    # Tạo tên file unique để tránh trùng khi nhiều request đồng thời
    unique_name = f"{uuid.uuid4()}_{file.filename}"
    temp_path = os.path.join(TEMP_DIR, unique_name)

    try:
        file_content = await file.read()
    except Exception as read_error:
        logger.error(f"Không thể đọc nội dung file '{file.filename}': {read_error}")
        raise IOError(f"Không thể đọc nội dung file '{file.filename}'") from read_error

    try:
        with open(temp_path, "wb") as temp_file:
            temp_file.write(file_content)
    except Exception as write_error:
        logger.error(f"Không thể ghi file tạm '{temp_path}': {write_error}")
        raise IOError(f"Không thể lưu file '{file.filename}' vào disk") from write_error

    logger.info(f"Đã lưu file tạm: {temp_path} ({len(file_content)} bytes)")

    return temp_path


def convert_file_to_markdown(file_path: str) -> str:
    """
    Dùng Docling để convert file sang markdown.

    Input:
        file_path (str): Đường dẫn tuyệt đối đến file cần parse.

    Output:
        str: Nội dung markdown sau khi parse.

    Raises:
        RuntimeError: Khi Docling không thể convert file.
    """

    try:
        result = document_converter.convert(file_path)
    except Exception as convert_error:
        logger.error(f"Docling convert thất bại cho '{file_path}': {convert_error}")
        raise RuntimeError(f"Docling không thể parse file: {convert_error}") from convert_error

    try:
        markdown_content = result.document.export_to_markdown()
    except Exception as export_error:
        logger.error(f"Export markdown thất bại cho '{file_path}': {export_error}")
        raise RuntimeError(f"Không thể export sang markdown: {export_error}") from export_error

    # Giải phóng Docling result object (chứa pages, hình ảnh, bảng nội bộ)
    del result
    gc.collect()

    return markdown_content


def cleanup_temp_file(file_path: str) -> None:
    """
    Xóa file tạm sau khi đã parse xong.

    Input:
        file_path (str): Đường dẫn file tạm cần xóa.

    Output: Không có (None)
    """

    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            logger.info(f"Đã xóa file tạm: {file_path}")
    except OSError as cleanup_error:
        # Không raise lỗi vì cleanup không critical - chỉ log warning
        logger.warning(f"Không thể xóa file tạm '{file_path}': {cleanup_error}")


async def parse_single_file(file: UploadFile) -> ParseResultItem:
    """
    Parse một file đơn lẻ: lưu tạm → convert → xóa tạm.

    Input:
        file (UploadFile): File được upload từ client.

    Output:
        ParseResultItem: Kết quả gồm tên file và nội dung markdown.

    Raises:
        IOError: Khi lưu file tạm thất bại.
        RuntimeError: Khi Docling convert thất bại.
    """

    temp_path = None

    try:
        # Bước 1: Lưu file upload vào thư mục tạm
        temp_path = await save_temp_file(file)

        # Bước 2: Dùng Docling convert sang markdown (chạy trong worker thread tránh block event loop)
        markdown_content = await asyncio.to_thread(convert_file_to_markdown, temp_path)

        return ParseResultItem(
            file_name=file.filename,
            content=markdown_content
        )

    finally:
        # Bước 3: Luôn xóa file tạm dù thành công hay thất bại
        if temp_path:
            cleanup_temp_file(temp_path)


async def parse_multiple_files(files: List[UploadFile]) -> List[Dict[str, Any]]:
    """
    Parse nhiều file, bắt lỗi từng file riêng biệt.

    File lỗi không ảnh hưởng đến các file khác -
    mỗi file sẽ có kết quả hoặc thông báo lỗi riêng.

    Input:
        files (List[UploadFile]): Danh sách file cần parse (tối đa 10).

    Output:
        List[Dict[str, Any]]: Danh sách kết quả, mỗi item gồm:
            - file_name (str): Tên file
            - content (str): Nội dung markdown (nếu thành công)
            - error (str): Thông báo lỗi (nếu thất bại, chỉ có khi lỗi)
    """

    results = []

    for file in files:
        try:
            parsed_item = await parse_single_file(file)

            results.append({
                "file_name": parsed_item.file_name,
                "content": parsed_item.content,
            })

            logger.info(f"Parse thành công: {file.filename}")

        except IOError as io_error:
            # Lỗi đọc/ghi file - bắt riêng để phân biệt với lỗi convert
            logger.error(f"Lỗi I/O khi parse '{file.filename}': {io_error}")

            results.append({
                "file_name": file.filename,
                "content": "",
                "error": f"Lỗi I/O: {str(io_error)}",
            })

        except RuntimeError as runtime_error:
            # Lỗi từ Docling (convert hoặc export)
            logger.error(f"Lỗi convert khi parse '{file.filename}': {runtime_error}")

            results.append({
                "file_name": file.filename,
                "content": "",
                "error": f"Lỗi convert: {str(runtime_error)}",
            })

        except Exception as unexpected_error:
            # Lỗi không mong đợi - log đầy đủ stack trace
            logger.exception(f"Lỗi không xác định khi parse '{file.filename}': {unexpected_error}")

            results.append({
                "file_name": file.filename,
                "content": "",
                "error": f"Lỗi không xác định: {str(unexpected_error)}",
            })

    logger.info(f"Hoàn tất parse {len(results)}/{len(files)} file")

    return results
