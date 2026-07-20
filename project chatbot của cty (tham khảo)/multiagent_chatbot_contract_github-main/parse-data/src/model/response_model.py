"""
Module định nghĩa các response model chuẩn cho API.

Đảm bảo tất cả response (thành công lẫn lỗi) đều có chung format:
{ status, result, description }
"""

from typing import Any, List
from pydantic import BaseModel


class ParseResultItem(BaseModel):
    """
    Kết quả parse của 1 file.

    Input: Không có (Pydantic model tự validate)
    Output: Không có

    Attributes:
        file_name (str): Tên file gốc đã upload.
        content (str): Nội dung markdown sau khi parse.
    """

    file_name: str
    content: str


class ApiResponse(BaseModel):
    """
    Response chuẩn cho mọi API endpoint.

    Input: Không có (Pydantic model tự validate)
    Output: Không có

    Dùng chung cho cả thành công và lỗi:
    - Thành công: status=200, result=[...], description=""
    - Lỗi: status=<mã lỗi>, result="", description="<mô tả lỗi>"
    """

    status: int
    result: Any
    description: str
