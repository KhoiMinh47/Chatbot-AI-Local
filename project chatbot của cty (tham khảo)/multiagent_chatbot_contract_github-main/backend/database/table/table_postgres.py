"""
Module định nghĩa các bảng PostgreSQL (SQLAlchemy ORM models).

Bao gồm các bảng:
    - account: Tài khoản người dùng (email, password, 2 lớp xác thực).
    - email_verification_token: Token one-time để xác thực email.
    - role: Quyền hệ thống (root, rag, create, upload, none).
    - account_role: Quan hệ many-to-many account ↔ role.
    - login_history: Lịch sử truy cập — đăng nhập/đăng xuất (IP, geo, device, ISP/ASN).
    - admin_notification: Thông báo cảnh báo bảo mật cho Admin.
    - contract_template: Quản lý template hợp đồng.
    - session: Session hội thoại chung.
    - contract: Quản lý hợp đồng.
    - history_mess: Lịch sử chat chung.
    - document_fulltext: Lưu toàn bộ nội dung văn bản của file tài liệu đã upload.

Tất cả model kế thừa Base từ setup_postgres để được tự động
tạo bảng khi server khởi động (Base.metadata.create_all).
"""

from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Text,
    Boolean, LargeBinary, JSON, Float, UniqueConstraint,
)
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship

from database.setup_postgres import Base


# =============================================================================
# BẢNG AUTHENTICATION
# =============================================================================


class Account(Base):
    """
    Bảng tài khoản người dùng.

    Hệ thống 2 lớp xác thực:
        - Lớp 1 (is_verified): Email đã xác thực qua link gửi mail.
        - Lớp 2 (is_active): Admin (root) bật quyền truy cập.

    Lockout mechanism:
        - Nhập sai >= 5 lần → khóa lũy tiến: 5p → 50p → 500p.
        - Công thức: lock_minutes = 5 * (10 ** (failed_attempts - 5))

    Columns:
        id (Integer, PK): ID tài khoản.
        email (String, unique): Email đăng nhập (không cho sửa).
        password_hash (String): Mật khẩu đã hash bằng bcrypt.
        name (String): Tên hiển thị.
        phone (String, nullable): Số điện thoại.
        address (String, nullable): Địa chỉ.
        avatar (LargeBinary, nullable): Ảnh đại diện (bytes).
        avatar_mime (String, nullable): MIME type ảnh (image/png, ...).
        is_verified (Boolean): Lớp 1 — email đã verify.
        is_active (Boolean): Lớp 2 — admin đã bật access.
        failed_attempts (Integer): Số lần nhập sai password liên tiếp.
        locked_until (DateTime, nullable): Thời điểm hết khóa (NULL = không khóa).
        created_at (DateTime): Thời điểm tạo tài khoản.
        updated_at (DateTime): Thời điểm cập nhật gần nhất.
    """

    __tablename__ = "account"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    email = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    name = Column(String, nullable=False)
    phone = Column(String, nullable=True)
    address = Column(String, nullable=True)
    avatar = Column(LargeBinary, nullable=True)
    avatar_mime = Column(String, nullable=True)

    # 2 lớp xác thực
    is_verified = Column(Boolean, default=False, nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)

    # Lockout mechanism
    failed_attempts = Column(Integer, default=0, nullable=False)
    locked_until = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    # Relationship → AccountRole → Role
    account_roles = relationship(
        "AccountRole", back_populates="account", cascade="all, delete-orphan"
    )
    email_verification_tokens = relationship(
        "EmailVerificationToken",
        back_populates="account",
        cascade="all, delete-orphan",
    )


class EmailVerificationToken(Base):
    """
    Bảng lưu token xác thực email dạng one-time, chỉ lưu HASH để tăng bảo mật.

    Token flow:
        - Khi đăng ký: tạo raw token ngẫu nhiên, chỉ gửi qua email.
        - DB chỉ lưu token_hash (không lưu raw token).
        - Khi verify thành công: đánh dấu used_at để chống replay.
    """

    __tablename__ = "email_verification_token"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    account_id = Column(
        Integer, ForeignKey("account.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    purpose = Column(String, nullable=False, default="verify_email", index=True)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    used_at = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    account = relationship("Account", back_populates="email_verification_tokens")


class Role(Base):
    """
    Bảng quyền hệ thống (static data).

    4 quyền mặc định:
        - root: Quản trị toàn hệ thống.
        - rag: Được phép tra cứu tài liệu RAG.
        - create: Được phép tạo hợp đồng.
        - none: Chưa được cấp quyền cụ thể.

    Columns:
        id (Integer, PK): ID quyền.
        name (String, unique): Tên quyền (root/rag/create/none).
        description (String): Mô tả quyền.
    """

    __tablename__ = "role"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String, unique=True, nullable=False)
    description = Column(String, nullable=True)

    account_roles = relationship("AccountRole", back_populates="role")


class AccountRole(Base):
    """
    Bảng quan hệ many-to-many giữa Account và Role.

    Mỗi account có thể có nhiều quyền, mỗi quyền gán cho nhiều account.

    Columns:
        account_id (Integer, FK, PK): ID tài khoản.
        role_id (Integer, FK, PK): ID quyền.
    """

    __tablename__ = "account_role"

    account_id = Column(
        Integer, ForeignKey("account.id", ondelete="CASCADE"),
        primary_key=True,
    )
    role_id = Column(
        Integer, ForeignKey("role.id", ondelete="CASCADE"),
        primary_key=True,
    )

    account = relationship("Account", back_populates="account_roles")
    role = relationship("Role", back_populates="account_roles")


# =============================================================================
# BẢNG BẢO MẬT (SECURITY)
# =============================================================================


class LoginHistory(Base):
    """
    Bảng lịch sử truy cập (access history) của mỗi account.

    Lưu lại thông tin thiết bị, IP, vị trí địa lý, ISP/ASN
    mỗi lần đăng nhập hoặc đăng xuất.

    Columns:
        id (Integer, PK): ID record.
        account_id (Integer, FK): Tài khoản.
        action (String): Loại hành động: "login" hoặc "logout".
        ip_address (String): Địa chỉ IP.
        country (String, nullable): Quốc gia (ISO code, VD: "VN").
        city (String, nullable): Thành phố.
        latitude (Float, nullable): Vĩ độ.
        longitude (Float, nullable): Kinh độ.
        isp (String, nullable): Nhà mạng (ISP).
        asn (Integer, nullable): Autonomous System Number.
        as_org (String, nullable): Tổ chức sở hữu ASN.
        os (String, nullable): Hệ điều hành (VD: "Windows 10").
        browser (String, nullable): Trình duyệt (VD: "Chrome 120").
        device_type (String, nullable): Loại thiết bị (PC/Mobile/Tablet/Bot).
        is_vpn_or_datacenter (Boolean): True nếu ASN thuộc datacenter/VPN.
        user_agent (Text, nullable): Chuỗi User-Agent gốc.
        created_at (DateTime): Thời điểm thực hiện.
    """

    __tablename__ = "login_history"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    account_id = Column(
        Integer, ForeignKey("account.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    ip_address = Column(String, nullable=False, index=True)
    action = Column(String, nullable=False, default="login", index=True)
    country = Column(String, nullable=True)
    city = Column(String, nullable=True)
    latitude = Column(Float, nullable=True)
    longitude = Column(Float, nullable=True)
    isp = Column(String, nullable=True)
    asn = Column(Integer, nullable=True)
    as_org = Column(String, nullable=True)
    os = Column(String, nullable=True)
    browser = Column(String, nullable=True)
    device_type = Column(String, nullable=True)
    is_vpn_or_datacenter = Column(Boolean, default=False, nullable=False)
    user_agent = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    account = relationship("Account")


class AdminNotification(Base):
    """
    Bảng thông báo cảnh báo bảo mật dành cho Admin.

    Ghi nhận các sự kiện bất thường: VPN/Tor, impossible travel,
    đăng nhập từ datacenter, v.v.

    Columns:
        id (Integer, PK): ID thông báo.
        account_id (Integer, FK): Tài khoản liên quan.
        alert_type (String): Loại cảnh báo (vpn_detected, impossible_travel, datacenter_ip).
        severity (String): Mức độ (low, medium, high, critical).
        title (String): Tiêu đề ngắn gọn.
        detail (Text): Mô tả chi tiết sự cố (JSON-friendly text).
        ip_address (String, nullable): IP gây ra cảnh báo.
        country (String, nullable): Quốc gia của IP đáng ngờ.
        is_read (Boolean): Admin đã đọc chưa.
        created_at (DateTime): Thời điểm tạo cảnh báo.
    """

    __tablename__ = "admin_notification"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    account_id = Column(
        Integer, ForeignKey("account.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    alert_type = Column(String, nullable=False, index=True)
    severity = Column(String, nullable=False, default="high")
    title = Column(String, nullable=False)
    detail = Column(Text, nullable=True)
    ip_address = Column(String, nullable=True)
    country = Column(String, nullable=True)
    is_read = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    account = relationship("Account")



# =============================================================================
# BẢNG HỢP ĐỒNG (CONTRACT)
# =============================================================================


class contract_template(Base):
    """
    Bảng lưu thông tin template hợp đồng.

    Mỗi record đại diện cho một mẫu hợp đồng (.docx) đã upload,
    kèm theo nội dung markdown đã parse bằng Docling.

    Columns:
        id (Integer, PK): ID template (auto-increment).
        name (String): Tên file template (VD: "hopdongmuaban.docx").
        content (Text): Nội dung markdown của template sau khi Docling parse.
        path (String): Đường dẫn file trên MinIO.
        created_at (DateTime): Thời điểm upload.
    """

    __tablename__ = "contract_template"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String)
    content = Column(Text)
    path = Column(String)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    contracts = relationship("contract", back_populates="template_info")


class contract(Base):
    """
    Bảng lưu thông tin hợp đồng đang tạo hoặc đã hoàn thành.

    Mỗi record theo dõi tiến trình điền dữ liệu vào template,
    bao gồm dữ liệu đã thu thập và các trường còn thiếu.

    Columns:
        id (Integer, PK): ID hợp đồng (auto-increment).
        template_id (Integer, FK): ID template hợp đồng.
        user_id (String): ID người dùng.
        session_id (Integer, FK): ID session tạo hợp đồng.
        name (String): Tên hợp đồng (đã clean).
        content (Text): Nội dung hợp đồng từ LLM.
        path (String): Đường dẫn file hợp đồng.
        created_at (DateTime): Thời điểm tạo.
    """

    __tablename__ = "contract"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    template_id = Column(Integer, ForeignKey("contract_template.id"))
    user_id = Column(String)
    session_id = Column(Integer, ForeignKey("session.id"))
    name = Column(String)
    
    content = Column(Text)
    path = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    template_info = relationship("contract_template", back_populates="contracts")
    session_info = relationship("session", back_populates="contract_info")


class session(Base):
    """
    Bảng lưu session hội thoại.

    Mỗi session là một phiên làm việc giữa user và chatbot.

    Columns:
        id (Integer, PK): ID session (auto-increment).
        user_id (String): ID người dùng sở hữu session.
        created_at (DateTime): Thời điểm tạo session.
    """

    __tablename__ = "session"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String)
    name = Column(String)
    
    # New fields for session enhancement
    paths = Column(JSON, default=[], nullable=True) # Dùng cho RAG (List of files)
    template_path = Column(String, nullable=True)   # Dùng cho Contract (1 pinned file duy nhất)
    is_pinned = Column(Boolean, default=False, nullable=False)
    
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )

    history_info = relationship("history_mess", back_populates="session_info")
    contract_info = relationship("contract", back_populates="session_info")


class history_mess(Base):
    """
    Bảng lưu lịch sử tin nhắn giữa user và chatbot.

    Columns:
        id (Integer, PK): ID tin nhắn (auto-increment).
        user_id (String): ID người dùng.
        session_id (Integer, FK): ID session chứa tin nhắn.
        role (String): Vai trò gửi tin ("user" hoặc "chatbot").
        mess (Text): Nội dung tin nhắn.
        created_at (DateTime): Thời điểm gửi tin nhắn.
    """

    __tablename__ = "history_mess"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String)
    session_id = Column(Integer, ForeignKey("session.id"), index=True)
    role = Column(String)
    mess = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    session_info = relationship("session", back_populates="history_info")


class semantic_history(Base):
    """
    Bảng lưu history đã chuẩn hóa để phục vụ semantic retrieval.

    Mỗi turn chat có thể tạo 1-2 records (user/chatbot), dùng chung turn_id
    để resolver ưu tiên thông tin mới nhất theo ngữ cảnh hội thoại.
    """

    __tablename__ = "semantic_history"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "session_id",
            "turn_id",
            "role",
            "task_type",
            name="uq_semantic_history_turn_role_task",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    user_id = Column(String, index=True, nullable=False)
    session_id = Column(Integer, ForeignKey("session.id"), index=True, nullable=False)
    turn_id = Column(Integer, index=True, nullable=False)
    role = Column(String, nullable=False)
    task_type = Column(String, index=True, nullable=False)
    raw_text = Column(Text, nullable=False)
    summary_text = Column(Text, nullable=False)
    entity_keys = Column(JSON, nullable=True)
    time_scope = Column(String, nullable=True)
    is_negation = Column(Boolean, default=False, nullable=False)
    supersedes_turn_id = Column(Integer, nullable=True)
    embedding = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


# =============================================================================
# BẢNG LƯU NỘI DUNG TOÀN VĂN TÀI LIỆU (RAG DOCUMENT FULLTEXT)
# =============================================================================


class document_fulltext(Base):
    """
    Bảng lưu toàn bộ nội dung văn bản của file tài liệu đã upload.

    Mục đích: Khi cần tra cứu sâu vào 1 file cụ thể, cho LLM đọc
    trực tiếp toàn bộ nội dung thay vì chỉ đọc từng chunk nhỏ.

    Columns:
        id (Integer, PK): ID record (auto-increment).
        file_name (String): Tên file đã chuẩn hóa (unique, dùng để lookup).
        file_path (String): Đường dẫn file trên server.
        content (Text): Toàn bộ nội dung markdown của tài liệu.
        created_at (DateTime): Thời điểm lưu.
    """

    __tablename__ = "document_fulltext"

    id = Column(
        Integer, primary_key=True, autoincrement=True, index=True
    )
    file_path = Column(String, unique=True, index=True)
    content = Column(Text)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now()
    )
    

# =============================================================================
# BẢNG CẤU HÌNH HỆ THỐNG (SYSTEM CONFIG)
# =============================================================================


class MailServerConfig(Base):
    """
    Bảng lưu cấu hình Mail Server (SMTP).
    Cho phép Admin thay đổi mail server mà không cần sửa file .env.
    """

    __tablename__ = "mail_server_config"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    host = Column(String, nullable=False)
    port = Column(Integer, nullable=False, default=587)
    user = Column(String, nullable=False)
    password = Column(String, nullable=False)
    from_email = Column(String, nullable=False)
    from_name = Column(String, nullable=False)
    logo_url = Column(String, nullable=True)
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class TelegramBotConfig(Base):
    """
    Bảng lưu cấu hình Telegram Bot để gửi thông báo hệ thống.

    Quy tắc:
        - Luôn phải có đúng 1 bot đang active để hệ thống gửi tin.
        - Khi bật bot mới, bot active cũ sẽ bị tắt.
    """

    __tablename__ = "telegram_bot_config"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    bot_id = Column(String, nullable=False, unique=True, index=True)
    bot_token = Column(String, nullable=False)
    is_active = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class TelegramRecipientConfig(Base):
    """
    Bảng lưu danh sách người nhận Telegram.

    Chỉ các recipient có is_active=True mới nhận thông báo.
    """

    __tablename__ = "telegram_recipient_config"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String, nullable=False)
    chat_id = Column(String, nullable=False, unique=True, index=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class PromptConfig(Base):
    """
    Bảng lưu cấu hình System Prompts cho LLM.
    Admin có thể tùy chỉnh prompt theo từng chức năng cụ thể.
    """

    __tablename__ = "prompt_config"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)  # Vd: "RAG_SYSTEM_PROMPT"
    feature_key = Column(String, nullable=False, default="custom", index=True)
    content = Column(Text, nullable=False)
    description = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class LLMProviderConfig(Base):
    """
    Bảng lưu nguồn model LLM có thể dùng trong hệ thống.

    provider_type:
        - local_vllm: model chạy local qua vLLM
        - openai_compatible: API ngoài tương thích OpenAI spec
    """

    __tablename__ = "llm_provider_config"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    provider_type = Column(String, nullable=False, default="openai_compatible")
    base_url = Column(String, nullable=False)
    api_key = Column(String, nullable=True)
    models = Column(JSON, nullable=False, default=list)
    description = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False)
    is_default = Column(Boolean, default=False, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class DomainUrlIndex(Base):
    """
    Bảng index URL theo domain để phục vụ Domain Mapper/incremental crawl.
    """

    __tablename__ = "domain_url_index"

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    domain = Column(String, nullable=False, index=True)
    url = Column(String, nullable=False, index=True)
    title = Column(String, nullable=True)
    path_type = Column(String, nullable=True, index=True)
    content_hash = Column(String, nullable=True, index=True)
    quality_score = Column(Float, nullable=True, default=0.0, index=True)
    fetch_status = Column(String, nullable=True, default="ok")
    last_seen = Column(DateTime(timezone=True), nullable=True, index=True)
    last_modified = Column(DateTime(timezone=True), nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )


class WebSourceRule(Base):
    """
    Bảng policy nguồn web cho web_search (root quản trị).

    rule_type:
        - allow: cho phép nguồn khi strict filter bật.
        - block: chặn nguồn luôn.

    match_type:
        - domain: match theo domain/subdomain.
        - url_prefix: match theo prefix URL cụ thể.
    """

    __tablename__ = "web_source_rule"
    __table_args__ = (
        UniqueConstraint("rule_type", "match_type", "value", name="uq_web_source_rule_triplet"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True, index=True)
    rule_type = Column(String, nullable=False, index=True)   # allow | block
    match_type = Column(String, nullable=False, index=True)  # domain | url_prefix
    value = Column(String, nullable=False, index=True)
    note = Column(String, nullable=True)
    is_active = Column(Boolean, default=True, nullable=False, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
