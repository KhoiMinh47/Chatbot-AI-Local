from typing import Optional
from pydantic import BaseModel, Field


class ContractTemplatedRequest(BaseModel):
    """
    Request model cho API tạo hợp đồng (Luồng 1: Template Mẫu).
    """

    session_id: int = Field(
        ...,
        example=-1,
        description="ID session hiện tại, gửi -1 để tạo session mới",
    )
    template_id: int = Field(
        ...,
        example=1,
        description="ID template hợp đồng trong database",
    )
    user_input: str = Field(
        ...,
        example="Hãy điền thông tin: Chủ đầu tư (Bên A): Sở Xây Dựng TP HCM",
        description="Câu hỏi hoặc yêu cầu của người dùng",
    )
    model_name: Optional[str] = Field(
        default=None,
        example=None,
        description="Tên model LLM",
    )
    is_api: bool = Field(
        default=False,
        example=False,
        description="Đánh dấu model có phải là API bên ngoài hay không",
    )


class ContractFastRequest(BaseModel):
    """
    Request model cho API tạo hợp đồng (Luồng 2: AI Fast KHÔNG cần Template).
    """

    session_id: int = Field(
        ...,
        example=-1,
        description="ID session hiện tại, gửi -1 để tạo session mới",
    )
    user_input: str = Field(
        ...,
        example="Tạo hợp đồng với thông tin: Nhà đầu tư (Bên A): Công ty Cổ phần Bách Việt, Nhà thầu (Bên B): Công ty Xây dựng ABC.",
        description="Câu hỏi hoặc yêu cầu của người dùng",
    )
    model_name: Optional[str] = Field(
        default=None,
        example=None,
        description="Tên model LLM",
    )
    is_api: bool = Field(
        default=False,
        example=False,
        description="Đánh dấu model có phải là API bên ngoài hay không",
    )


class ContractReasoningRequest(BaseModel):
    """
    Request model cho API tạo hợp đồng (Luồng 3: AI Reasoning Đa Tác Tử).
    """

    session_id: int = Field(
        ...,
        example=-1,
        description="ID session hiện tại, gửi -1 để tạo session mới",
    )
    user_input: str = Field(
        ...,
        example="Hãy điền thông tin: Nhà đầu tư (Bên A): Công ty Cổ phần Bách Việt",
        description="Câu hỏi hoặc yêu cầu của người dùng",
    )
    model_name: Optional[str] = Field(
        default=None,
        example=None,
        description="Tên model LLM",
    )
    is_api: bool = Field(
        default=False,
        example=False,
        description="Đánh dấu model có phải là API bên ngoài hay không",
    )


class ContractPathRequest(BaseModel):
    session_id: int = Field(..., description="ID của session")
    file_path: str = Field(..., description="Đường dẫn file template")
