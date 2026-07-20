"""
Module định nghĩa request và response models chuẩn cho API.

Tất cả response (thành công + lỗi) đều theo format:
{ status, result, description }
"""

from typing import Any, List
from pydantic import BaseModel


class EmbeddingRequest(BaseModel):
    """
    Request body cho endpoint embedding.

    Attributes:
        texts (List[str]): Danh sách text cần embedding.
    """

    texts: List[str]


class RerankRequest(BaseModel):
    """
    Request body cho endpoint rerank.

    Attributes:
        query (str): Câu truy vấn.
        documents (List[str]): Danh sách document cần xếp hạng.
    """

    query: str
    documents: List[str]


class ApiResponse(BaseModel):
    """
    Response chuẩn cho mọi endpoint.

    Dùng chung cho cả thành công và lỗi:
    - Thành công: status=200, result=[...], description=""
    - Lỗi: status=<mã lỗi>, result="", description="<mô tả>"
    """

    status: int
    result: Any
    description: str
