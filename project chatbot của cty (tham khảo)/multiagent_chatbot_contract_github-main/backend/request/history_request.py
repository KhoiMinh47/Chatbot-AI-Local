

from pydantic import BaseModel, Field


class history_request(BaseModel):
    session_id: int = Field(..., description="1")

class SessionRenameRequest(BaseModel):
    session_id: int = Field(..., description="ID của session cần đổi tên")
    new_name: str = Field(..., description="Tên mới của session")

class SessionCreateRequest(BaseModel):
    name: str = Field(..., description="Tên của session mới")