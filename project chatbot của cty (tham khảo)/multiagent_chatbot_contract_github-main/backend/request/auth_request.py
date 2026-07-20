"""
Module định nghĩa Pydantic request models cho Authentication API.
"""

from pydantic import BaseModel, Field


class RegisterRequest(BaseModel):
    """Request model cho đăng ký tài khoản."""

    email: str = Field(
        ..., example="user@example.com",
        description="Email đăng ký",
    )
    password: str = Field(
        ..., example="MyPassword123",
        description="Mật khẩu (tối thiểu 6 ký tự)",
    )
    name: str = Field(
        ..., example="Nguyễn Văn A",
        description="Tên hiển thị",
    )


class LoginRequest(BaseModel):
    """Request model cho đăng nhập."""

    email: str = Field(
        ..., example="user@example.com",
        description="Email đăng nhập",
    )
    password: str = Field(
        ..., example="MyPassword123",
        description="Mật khẩu",
    )


class ForgotPasswordRequest(BaseModel):
    """Request model cho quên mật khẩu."""

    email: str = Field(
        ..., example="user@example.com",
        description="Email cần reset mật khẩu",
    )


class VerifyEmailConfirmRequest(BaseModel):
    """Request model cho xác thực email one-time token."""

    verification_token: str = Field(
        ...,
        min_length=32,
        max_length=1024,
        example="uJmNqT6X...opaque_token...",
        description="One-time token nhận từ link email",
    )


class UpdateRolesRequest(BaseModel):
    """Request model cho cập nhật quyền (root only)."""

    account_id: int = Field(
        ..., example=1,
        description="ID tài khoản cần sửa quyền",
    )
    roles: list[str] = Field(
        ..., example=["rag", "create"],
        description="Danh sách quyền mới (root/rag/create/none)",
    )


class AddRoleRequest(BaseModel):
    """Request model cho thêm role vào account (root only)."""

    role_name: str = Field(
        ..., example="rag",
        description="Tên role cần thêm vào account",
    )


class HeartbeatCheckRequest(BaseModel):
    """Request model cho kiểm tra heartbeat (root only)."""

    user_ids: list[int] = Field(
        ..., example=[1, 2, 3],
        description="Danh sách ID người dùng cần kiểm tra trạng thái online",
    )


class UpdateProfileRequest(BaseModel):
    """Request model cho cập nhật thông tin cá nhân."""

    name: str | None = Field(
        default=None, example="Nguyễn Văn B",
        description="Tên mới (None = không đổi)",
    )
    phone: str | None = Field(
        default=None, example="0901234567",
        description="Số điện thoại (None = không đổi)",
    )
    address: str | None = Field(
        default=None, example="123 Đường ABC, TP.HCM",
        description="Địa chỉ (None = không đổi)",
    )
    password: str | None = Field(
        default=None, example="NewPassword123",
        description="Mật khẩu mới (None = không đổi)",
    )


class CreateRoleRequest(BaseModel):
    """Request model cho tạo role mới (root only)."""

    name: str = Field(
        ..., example="editor",
        description="Tên role (phải là duy nhất, không khoảng trắng)",
    )
    description: str | None = Field(
        default=None, example="Quyền sửa nội dung",
        description="Mô tả quyền",
    )


class UpdateRoleRequest(BaseModel):
    """Request model cho cập nhật role (root only)."""

    name: str | None = Field(
        default=None, example="editor_v2",
        description="Tên mới (None = không đổi)",
    )
    description: str | None = Field(
        default=None, example="Mô tả mới",
        description="Mô tả mới (None = không đổi)",
    )
