"""
Module định nghĩa các endpoint cho parse PDF.

Endpoint chính: POST /parse - nhận tối đa 10 file,
trả về nội dung markdown cho từng file.
"""

import logging

from fastapi import APIRouter, UploadFile, File

from src.model.response_model import ApiResponse
from src.service.parse_service import parse_multiple_files


# Cấu hình logging cho module này
logger = logging.getLogger(__name__)

# Giới hạn số file tối đa mỗi request
MAX_FILES_PER_REQUEST = 10

# Danh sách extension được phép upload (PDF, Office, CSV, Image)
ALLOWED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".csv",
    ".jpg", ".jpeg", ".png", ".bmp", ".tiff", ".webp",
}

router = APIRouter()


@router.post("/parse", response_model=ApiResponse)
async def parse_files_endpoint(files: list[UploadFile]):
    """
    Endpoint nhận danh sách file PDF và parse sang markdown.

    Input:
        files (List[UploadFile]): Danh sách file upload (tối đa 10 file).

    Output:
        ApiResponse: Response chuẩn với status, result, description.
    """

    # --- Validate: Kiểm tra số lượng file ---
    try:
        if len(files) > MAX_FILES_PER_REQUEST:
            logger.warning(f"Client gửi quá {MAX_FILES_PER_REQUEST} file: {len(files)}")

            return ApiResponse(
                status=400,
                result="",
                description=f"Tối đa {MAX_FILES_PER_REQUEST} file mỗi request. Bạn đã gửi {len(files)} file."
            )
    except Exception as count_error:
        logger.error(f"Lỗi khi kiểm tra số lượng file: {count_error}")

        return ApiResponse(
            status=400,
            result="",
            description=f"Lỗi khi kiểm tra số lượng file: {str(count_error)}"
        )

    # --- Validate: Kiểm tra không gửi file rỗng ---
    try:
        if len(files) == 0:
            logger.warning("Client gửi request không có file")

            return ApiResponse(
                status=400,
                result="",
                description="Vui lòng gửi ít nhất 1 file."
            )
    except Exception as empty_error:
        logger.error(f"Lỗi khi kiểm tra file rỗng: {empty_error}")

        return ApiResponse(
            status=400,
            result="",
            description=f"Lỗi khi kiểm tra file: {str(empty_error)}"
        )

    # --- Validate: Kiểm tra extension từng file ---
    try:
        invalid_files = []

        for file in files:
            # Lấy extension (vd: ".pdf") và chuyển thành lowercase
            file_extension = "." + file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""

            if file_extension not in ALLOWED_EXTENSIONS:
                invalid_files.append(file.filename)

        if invalid_files:
            logger.error(f"Định dạng file không được hỗ trợ hoặc bị cấm: {invalid_files}")

            return ApiResponse(
                status=400,
                result="",
                description=f"Định dạng file không được hỗ trợ. Chỉ chấp nhận PDF, Word, PPT, CSV và ảnh (JPG, PNG, BMP, TIFF, WEBP). Các file lỗi: {', '.join(invalid_files)}"
            )
    except Exception as ext_error:
        logger.error(f"Lỗi khi kiểm tra extension file: {ext_error}")

        return ApiResponse(
            status=400,
            result="",
            description=f"Lỗi khi kiểm tra định dạng file: {str(ext_error)}"
        )

    # --- Xử lý: Parse tất cả file ---
    try:
        results = await parse_multiple_files(files)

        logger.info(f"Parse thành công {len(results)} file")

        return ApiResponse(
            status=200,
            result=results,
            description=""
        )
    except Exception as parse_error:
        logger.exception(f"Lỗi không mong đợi khi parse file: {parse_error}")

        return ApiResponse(
            status=500,
            result="",
            description=f"Lỗi server khi parse file: {str(parse_error)}"
        )
