"""
Module định nghĩa Pydantic request models cho API truy vấn RAG hợp đồng.

Model này được FastAPI sử dụng để validate và parse
dữ liệu JSON từ request body khi người dùng gửi câu hỏi tới RAG.
"""

from typing import Literal
from urllib.parse import urlparse

from pydantic import BaseModel, Field, validator


MAX_USER_URLS_PER_QUERY = 10


class rag_chat_request(BaseModel):
    """
    Request model cho API truy vấn RAG.

    Attributes:
        session_id (int): ID session hiện tại, gửi -1 để tạo session mới.
        user_input (str): Câu hỏi hoặc yêu cầu truy vấn của người dùng.
        model_name (str): Tên model sử dụng.
    """

    session_id: int = Field(
        ...,
        example=1,
        description="ID session hiện tại, gửi -1 để tạo session mới",
    )
    user_input: str = Field(
        ...,
        example="Tìm hợp đồng mua bán thiết bị văn phòng",
        description="Câu hỏi hoặc yêu cầu truy vấn RAG",
    )
    model_name: str = Field(
        default="Qwen/Qwen3-VL-8B-Instruct-FP8",
        example="Qwen/Qwen3-VL-8B-Instruct-FP8",
        description="Tên model sử dụng (mặc định cho RAG Contract Fast)",
    )
    is_api: bool = Field(
        default=False,
        example=False,
        description="Đánh dấu model có phải là API bên ngoài hay không",
    )
    file_paths: list[str] = Field(
        default=[],
        example=["file1.pdf", "file2.pdf"],
        description="Danh sách file được chọn để truy vấn"
    )
    query_flow: Literal["fast", "web_search"] = Field(
        default="fast",
        example="fast",
        description="Luồng truy vấn: fast (RAG nội bộ) hoặc web_search",
    )
    web_urls: list[str] = Field(
        default=[],
        example=["https://example.com/blog/bai-viet"],
        description="Danh sách URL web user cung cấp (tối đa 10)",
    )
    web_mode: Literal["open_web"] = Field(
        default="open_web",
        example="open_web",
        description="Chính sách nguồn web: open_web (mặc định, không dùng domain mặc định)",
    )

    @validator("web_urls", pre=True, always=True)
    def validate_web_urls(cls, value):
        urls = value or []
        if not isinstance(urls, list):
            raise ValueError("web_urls phải là danh sách URL")

        cleaned: list[str] = []
        for raw in urls:
            if raw is None:
                continue
            url = str(raw).strip()
            if not url:
                continue

            if not url.startswith(("http://", "https://")):
                url = f"https://{url}"

            parsed = urlparse(url)
            if parsed.scheme not in {"http", "https"} or not parsed.netloc:
                raise ValueError(f"URL không hợp lệ: {raw}")

            cleaned.append(url)

        if len(cleaned) > MAX_USER_URLS_PER_QUERY:
            raise ValueError(
                f"Số URL vượt giới hạn {MAX_USER_URLS_PER_QUERY}"
            )

        return cleaned
