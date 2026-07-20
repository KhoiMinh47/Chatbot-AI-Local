"""
Entry point cho FastAPI backend.

Khởi tạo ứng dụng FastAPI, cấu hình CORS middleware,
và tự động tạo bảng PostgreSQL + collection Qdrant khi server khởi động
thông qua lifespan context manager.
"""

import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

# Load .env file TRƯỚC tất cả import khá  — bắt buộc khi chạy local (không Docker).
# Các module con (contract_create_pipeline, rag_upload_util, ...) đọc os.getenv()
# ngay khi import, nên .env phải được load trước thời điểm đó.
from dotenv import load_dotenv
ROOT_DIR = Path(__file__).resolve().parent.parent
ROOT_ENV_ALL_PATH = ROOT_DIR / ".env.all"
ROOT_ENV_PATH = ROOT_DIR / ".env"

# Env tập trung ở project root. Frontend là service duy nhất giữ env riêng.
if ROOT_ENV_ALL_PATH.exists():
    load_dotenv(ROOT_ENV_ALL_PATH, override=False)
if ROOT_ENV_PATH.exists():
    load_dotenv(ROOT_ENV_PATH, override=True)

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text, select

from database.setup_postgres import engine, Base, SessionLocal
from database.setup_qdrant import qdrant_service
from database.setup_minio import minio_service
from database.setup_redis import redis_service
from database.setup_geoip import geoip_service
from auth.ip_monitor_middleware import IPMonitorMiddleware
from database.table.table_postgres import (
    Account, Role, AccountRole, LoginHistory, AdminNotification,
    MailServerConfig, PromptConfig, LLMProviderConfig,
    TelegramBotConfig, TelegramRecipientConfig,
)
from router.router import api_router

# Cấu hình logging cho toàn bộ module thay vì dùng print
logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

# Hằng số cấu hình server
SERVER_HOST = os.getenv("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.getenv("SERVER_PORT", "9000"))
_cors_origins_raw = os.getenv("CORS_ALLOW_ORIGINS", os.getenv("FRONTEND_URL", "")).strip()
_cors_allow_origins = [x.strip() for x in _cors_origins_raw.split(",") if x.strip()]


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Quản lý vòng đời (startup/shutdown) của ứng dụng FastAPI.

    Startup:
        - Tạo tất cả bảng PostgreSQL nếu chưa tồn tại (Base.metadata.create_all).
        - Khởi tạo Qdrant collection và payload indexes.
        - Khởi tạo MinIO bucket (tạo bucket nếu chưa tồn tại).
    Shutdown:
        - Kết thúc vòng đời Qdrant và MinIO service.

    Input:
        app (FastAPI): Instance ứng dụng FastAPI.

    Output:
        AsyncGenerator: Context manager cho lifespan events.
    """

    # Startup: tạo bảng DB và migrate nhẹ
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

        # Migrate: thêm cột action vào login_history nếu chưa có
        await conn.execute(
            text("ALTER TABLE login_history ADD COLUMN IF NOT EXISTS action VARCHAR DEFAULT 'login'")
        )
        # Backfill: các record cũ chưa có action -> mặc định login
        await conn.execute(
            text("UPDATE login_history SET action = 'login' WHERE action IS NULL")
        )

        # Mail config
        await conn.execute(
            text("ALTER TABLE mail_server_config ADD COLUMN IF NOT EXISTS logo_url VARCHAR")
        )

        # Prompt config
        await conn.execute(
            text("ALTER TABLE prompt_config ADD COLUMN IF NOT EXISTS feature_key VARCHAR DEFAULT 'custom'")
        )
        await conn.execute(
            text(
                """
                UPDATE prompt_config
                SET feature_key = CASE
                    WHEN name = 'RAG_SYSTEM_PROMPT' THEN 'rag_assistant'
                    WHEN name = 'CONTRACT_SYSTEM_PROMPT' THEN 'contract_template_drafter'
                    WHEN name = 'CONTRACT_FAST_SYSTEM_PROMPT' THEN 'contract_fast_drafter'
                    WHEN name = 'CONTRACT_SUMMARY_SYSTEM_PROMPT' THEN 'contract_summary'
                    WHEN name = 'CONTRACT_REASONING_DRAFTER_PROMPT' THEN 'contract_reasoning_drafter'
                    WHEN name = 'CONTRACT_REASONING_CRITIC_PROMPT' THEN 'contract_reasoning_critic'
                    WHEN name = 'CONTRACT_REASONING_REVISER_PROMPT' THEN 'contract_reasoning_reviser'
                    ELSE COALESCE(feature_key, 'custom')
                END
                WHERE feature_key IS NULL OR feature_key = '' OR feature_key = 'custom'
                """
            )
        )

        # LLM provider config
        await conn.execute(
            text("ALTER TABLE llm_provider_config ADD COLUMN IF NOT EXISTS api_key VARCHAR")
        )
        await conn.execute(
            text("ALTER TABLE llm_provider_config ADD COLUMN IF NOT EXISTS models JSON")
        )
        await conn.execute(
            text("ALTER TABLE llm_provider_config ADD COLUMN IF NOT EXISTS description VARCHAR")
        )
        await conn.execute(
            text("ALTER TABLE llm_provider_config ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
        )
        await conn.execute(
            text("ALTER TABLE llm_provider_config ADD COLUMN IF NOT EXISTS is_default BOOLEAN DEFAULT FALSE")
        )

        # Telegram bot config
        await conn.execute(
            text("ALTER TABLE telegram_bot_config ADD COLUMN IF NOT EXISTS bot_id VARCHAR")
        )
        await conn.execute(
            text("ALTER TABLE telegram_bot_config ADD COLUMN IF NOT EXISTS bot_token VARCHAR")
        )
        await conn.execute(
            text("ALTER TABLE telegram_bot_config ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT FALSE")
        )

        # Telegram recipient config
        await conn.execute(
            text("ALTER TABLE telegram_recipient_config ADD COLUMN IF NOT EXISTS name VARCHAR")
        )
        await conn.execute(
            text("ALTER TABLE telegram_recipient_config ADD COLUMN IF NOT EXISTS chat_id VARCHAR")
        )
        await conn.execute(
            text("ALTER TABLE telegram_recipient_config ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE")
        )

    # Seed dữ liệu mặc định (roles, accounts, configs)
    await _seed_auth_data()
    await _seed_system_config()

    await qdrant_service.initialize_qdrant()
    await minio_service.initialize_minio()
    await redis_service.initialize_redis()
    geoip_service.initialize()

    # Warmup prompt cache từ DB vào Redis để tránh query DB mỗi request.
    try:
        from service.runtime_config_service import warmup_active_prompt_cache

        warm_count = await warmup_active_prompt_cache()
        logger.info("[PROMPT_CACHE] Warmed %d active prompt feature(s)", warm_count)
    except Exception as e:
        logger.warning("[PROMPT_CACHE] Warmup skipped due to error: %s", e)

    # Warmup web source policy cache để tránh query rules lặp lại mỗi câu hỏi web_search.
    try:
        from agent_chatbot.node.util.rag_query_util import warmup_web_source_policy_cache

        await warmup_web_source_policy_cache()
        logger.info("[WEB_SOURCE_POLICY] Warmed active source policy cache")
    except Exception as e:
        logger.warning("[WEB_SOURCE_POLICY] Warmup skipped due to error: %s", e)

    # Xóa lock vLLM cũ nếu còn sót từ lần khởi động trước (process restart/crash)
    try:
        await redis_service.client.delete("vllm:locking")
        logger.info("Cleared stale vLLM lock on startup")
    except Exception as _e:
        logger.warning("Could not clear vLLM lock on startup: %s", _e)

    logger.info("Backend started successfully")

    yield

    # Shutdown: giải phóng tài nguyên
    await qdrant_service.close()
    await minio_service.close()
    await redis_service.close()
    geoip_service.close()
    logger.info("Backend shutdown completed")


# --- Khởi tạo FastAPI application ---
app = FastAPI(
    title="Chatbot Multi-Agent Bách Việt",
    description="Backend API cho hệ thống chatbot multi-agent",
    version="1.0.0",
    lifespan=lifespan,
)

# Middleware order: trong Starlette, add_middleware cuối cùng = outermost (chạy đầu tiên).
# IPMonitorMiddleware phải là innermost để response 401 từ nó vẫn đi qua CORSMiddleware.
# -> Thêm IPMonitorMiddleware TRƯỚC, CORSMiddleware SAU (CORSMiddleware = outermost).

# IP Monitor: phát hiện VPN, impossible travel, force logout khi anomaly.
app.add_middleware(IPMonitorMiddleware)

# CORS: outermost — bao bọc mọi response kể cả 401 từ IPMonitorMiddleware.
# Không dùng allow_origins=["*"] vì trình duyệt chặn khi kết hợp credentials=True.
# Thay vào đó dùng allow_origin_regex để match tất cả origins (kể cả cloudflare tunnel).
if _cors_allow_origins:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_cors_allow_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )
else:
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r".*",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["*"],
    )

# Gắn toàn bộ hệ thống router vào app với prefix /api/v1
app.include_router(api_router, prefix="/api/v1")

# Export metrics cho Prometheus
try:
    from prometheus_fastapi_instrumentator import Instrumentator
    Instrumentator().instrument(app).expose(app, include_in_schema=False)
    logger.info("Prometheus Instrumentator initialized at /metrics")
except ImportError:
    logger.warning("prometheus_fastapi_instrumentator not installed, /metrics disabled")

# Serve static files (logo email, etc.)
app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    uvicorn.run("main:app", host=SERVER_HOST, port=SERVER_PORT, workers=4)


# =============================================================================
# SEED DATA
# =============================================================================

# Danh sách roles mặc định của hệ thống
DEFAULT_ROLES = [
    {"name": "root", "description": "Quản trị toàn hệ thống"},
    {"name": "rag", "description": "Được phép tra cứu tài liệu RAG"},
    {"name": "create", "description": "Được phép tạo hợp đồng"},
    {"name": "upload", "description": "Được phép upload/xóa tài liệu RAG"},
    {"name": "none", "description": "Chưa có quyền cụ thể"},
]


async def _seed_auth_data():
    """
    Tạo dữ liệu mặc định cho hệ thống authentication.

    1. Tạo 5 roles (root, rag, create, upload, none) nếu chưa tồn tại.
    2. Tạo root account mặc định nếu chưa tồn tại.

    Được gọi trong lifespan startup sau khi tạo bảng.
    """

    from auth import hash_password

    async with SessionLocal() as db:
        # --- Seed Roles ---
        existing_roles = await db.execute(select(Role))
        if not existing_roles.scalars().first():
            for role_data in DEFAULT_ROLES:
                db.add(Role(**role_data))
            await db.commit()
            logger.info("[SEED] Đã tạo %d roles mặc định", len(DEFAULT_ROLES))
        else:
            logger.info("[SEED] Roles đã tồn tại")

        # --- Seed Root Account ---
        root_email = os.getenv("ROOT_EMAIL", "admin@bachviet.com")
        root_password = os.getenv("ROOT_PASSWORD", "Admin@2026")

        existing_root = await db.execute(
            select(Account).where(Account.email == root_email)
        )
        if not existing_root.scalars().first():
            # Lấy role root
            root_role_result = await db.execute(
                select(Role).where(Role.name == "root")
            )
            root_role = root_role_result.scalars().first()

            root_account = Account(
                email=root_email,
                password_hash=hash_password(root_password),
                name="Root Admin",
                is_verified=True,
                is_active=True,
            )
            db.add(root_account)
            await db.flush()  # Lấy root_account.id

            # Gán role root
            if root_role:
                db.add(AccountRole(
                    account_id=root_account.id,
                    role_id=root_role.id,
                ))

            await db.commit()
            logger.info(
                "[SEED] Đã tạo root account: %s (id=%d)",
                root_email, root_account.id,
            )
        else:
            logger.info("[SEED] Root account đã tồn tại: %s", root_email)


async def _seed_system_config():
    """
    Khởi tạo cấu hình hệ thống (Mail, Prompts, LLM Providers) trong database.
    """
    from service.runtime_config_service import (
        PROMPT_FEATURE_CONTRACT_FAST,
        PROMPT_FEATURE_CONTRACT_REASONING_CRITIC,
        PROMPT_FEATURE_CONTRACT_REASONING_DRAFTER,
        PROMPT_FEATURE_CONTRACT_REASONING_REVISER,
        PROMPT_FEATURE_CONTRACT_SUMMARY,
        PROMPT_FEATURE_CONTRACT_TEMPLATE,
        PROMPT_FEATURE_RAG_ASSISTANT,
        PROMPT_FEATURE_WEB_SEARCH_COORDINATOR,
        PROMPT_FEATURE_WEB_SEARCH_SYNTHESIZER,
        PROMPT_FEATURE_WEB_SEARCH_VERIFIER,
    )

    from agent_chatbot.node.util.rag_query_util import (
        SYSTEM_PROMPT as RAG_SYSTEM_PROMPT,
        WEB_COORDINATOR_SYSTEM_PROMPT,
        WEB_SYNTHESIZER_SYSTEM_PROMPT,
        WEB_VERIFIER_SYSTEM_PROMPT,
    )
    from agent_chatbot.node.util.contract_create_util import (
        FAST_SYSTEM_PROMPT,
        SYSTEM_PROMPT as CONTRACT_SYSTEM_PROMPT,
        _SUMMARY_SYSTEM_PROMPT,
    )
    from agent_chatbot.node.contract_reasoning_pipeline import (
        DRAFTER_SYSTEM_PROMPT,
        CRITIC_SYSTEM_PROMPT,
        REVISER_SYSTEM_PROMPT,
    )

    async with SessionLocal() as db:
        # --- Seed Mail Server Config (DB-first) ---
        existing_mail = await db.execute(select(MailServerConfig))
        if not existing_mail.scalars().first():
            mail_data = {
                "host": "smtp.gmail.com",
                "port": 587,
                "user": "change-me",
                "password": "change-me",
                "from_email": "service@ntcai.vn",
                "from_name": "ChatBot NTC",
                "logo_url": None,
                "is_active": False,
            }
            db.add(MailServerConfig(**mail_data))
            await db.commit()
            logger.warning(
                "[SEED] Đã tạo mail config mặc định trong DB. "
                "Root admin cần cập nhật SMTP thật và bật active."
            )
        else:
            logger.info("[SEED] Cấu hình Mail Server đã tồn tại trong DB")

        # --- Seed Default Prompts ---
        default_prompts = [
            {
                "name": "RAG_SYSTEM_PROMPT",
                "feature_key": PROMPT_FEATURE_RAG_ASSISTANT,
                "content": RAG_SYSTEM_PROMPT,
                "description": "Prompt hệ thống mặc định cho tra cứu hồ sơ/hợp đồng (RAG)",
            },
            {
                "name": "CONTRACT_SYSTEM_PROMPT",
                "feature_key": PROMPT_FEATURE_CONTRACT_TEMPLATE,
                "content": CONTRACT_SYSTEM_PROMPT,
                "description": "Prompt tạo hợp đồng theo template mẫu",
            },
            {
                "name": "CONTRACT_FAST_SYSTEM_PROMPT",
                "feature_key": PROMPT_FEATURE_CONTRACT_FAST,
                "content": FAST_SYSTEM_PROMPT,
                "description": "Prompt tạo hợp đồng nhanh không cần template",
            },
            {
                "name": "CONTRACT_SUMMARY_SYSTEM_PROMPT",
                "feature_key": PROMPT_FEATURE_CONTRACT_SUMMARY,
                "content": _SUMMARY_SYSTEM_PROMPT,
                "description": "Prompt tóm tắt hợp đồng",
            },
            {
                "name": "CONTRACT_REASONING_DRAFTER_PROMPT",
                "feature_key": PROMPT_FEATURE_CONTRACT_REASONING_DRAFTER,
                "content": DRAFTER_SYSTEM_PROMPT,
                "description": "Prompt tác tử soạn thảo bản nháp",
            },
            {
                "name": "CONTRACT_REASONING_CRITIC_PROMPT",
                "feature_key": PROMPT_FEATURE_CONTRACT_REASONING_CRITIC,
                "content": CRITIC_SYSTEM_PROMPT,
                "description": "Prompt tác tử phản biện",
            },
            {
                "name": "CONTRACT_REASONING_REVISER_PROMPT",
                "feature_key": PROMPT_FEATURE_CONTRACT_REASONING_REVISER,
                "content": REVISER_SYSTEM_PROMPT,
                "description": "Prompt tác tử chỉnh sửa",
            },
            {
                "name": "WEB_SEARCH_COORDINATOR_PROMPT",
                "feature_key": PROMPT_FEATURE_WEB_SEARCH_COORDINATOR,
                "content": WEB_COORDINATOR_SYSTEM_PROMPT,
                "description": "Prompt điều phối kế hoạch tra cứu web",
            },
            {
                "name": "WEB_SEARCH_SYNTHESIZER_PROMPT",
                "feature_key": PROMPT_FEATURE_WEB_SEARCH_SYNTHESIZER,
                "content": WEB_SYNTHESIZER_SYSTEM_PROMPT,
                "description": "Prompt tổng hợp câu trả lời từ nguồn web",
            },
            {
                "name": "WEB_SEARCH_VERIFIER_PROMPT",
                "feature_key": PROMPT_FEATURE_WEB_SEARCH_VERIFIER,
                "content": WEB_VERIFIER_SYSTEM_PROMPT,
                "description": "Prompt kiểm định độ tin cậy web search",
            },
        ]

        legacy_web_prompts_by_feature = {
            PROMPT_FEATURE_WEB_SEARCH_COORDINATOR: {
                (
                    "Bạn là điều phối viên tra cứu web. "
                    "Nhiệm vụ: hiểu câu hỏi, xác định nguồn hợp lệ, và tạo kế hoạch tìm kiếm ngắn gọn. "
                    "Không trả lời cuối cùng thay người tổng hợp. "
                    "Ưu tiên bằng chứng web chất lượng cao, kiểm soát ngân sách fetch."
                ),
                (
                    "Bạn là Web Research Coordinator trong hệ thống trợ lý doanh nghiệp. "
                    "Mục tiêu: chuyển câu hỏi người dùng thành kế hoạch tìm kiếm rõ ràng, ưu tiên nguồn đáng tin cậy, "
                    "và kiểm soát ngân sách URL/fetch để tối ưu tốc độ. "
                    "Không tự trả lời nội dung cuối cùng thay cho synthesizer."
                ),
            },
            PROMPT_FEATURE_WEB_SEARCH_SYNTHESIZER: {
                (
                    "Bạn là trợ lý tổng hợp thông tin web theo bằng chứng. "
                    "Chỉ dùng evidence đã cung cấp, không tự bịa. "
                    "Bắt buộc trích dẫn URL trong phần trả lời. "
                    "Nếu thiếu bằng chứng, nói rõ giới hạn."
                ),
                (
                    "Bạn là chuyên gia tổng hợp thông tin web. "
                    "Chỉ sử dụng evidence được cung cấp; tuyệt đối không suy đoán ngoài bằng chứng. "
                    "Trả lời súc tích, chuyên nghiệp, có cấu trúc rõ ràng và bắt buộc kèm citation URL cho từng ý chính. "
                    "Khi bằng chứng không đủ, nêu rõ giới hạn dữ liệu và đề xuất bước truy vấn tiếp theo."
                ),
            },
            PROMPT_FEATURE_WEB_SEARCH_VERIFIER: {
                (
                    "Bạn là bộ kiểm định chất lượng đầu ra. "
                    "Đánh giá nhanh mức tin cậy high/medium/low dựa trên độ đầy đủ và nhất quán bằng chứng."
                ),
            },
        }

        existing_prompts = await db.execute(select(PromptConfig))
        existing_prompt_rows = existing_prompts.scalars().all()
        existing_by_name = {p.name: p for p in existing_prompt_rows}

        added_prompt_count = 0
        healed_prompt_count = 0
        for prompt_data in default_prompts:
            existing = existing_by_name.get(prompt_data["name"])
            if existing:
                updated = False
                if not existing.feature_key:
                    existing.feature_key = prompt_data["feature_key"]
                    updated = True
                if not (existing.content or "").strip() or (existing.content or "").strip().startswith("[Seed]"):
                    existing.content = prompt_data["content"]
                    updated = True
                # Nếu prompt web vẫn đang dùng text mặc định cũ, tự động nâng cấp sang bản chuyên nghiệp.
                legacy_contents = legacy_web_prompts_by_feature.get(prompt_data["feature_key"], set())
                existing_content = (existing.content or "").strip()
                if any(existing_content == legacy.strip() for legacy in legacy_contents):
                    existing.content = prompt_data["content"]
                    updated = True
                if (
                    prompt_data["feature_key"] == PROMPT_FEATURE_WEB_SEARCH_COORDINATOR
                    and "allowlist nguồn web" not in existing_content
                ):
                    existing.content = prompt_data["content"]
                    updated = True
                if (
                    prompt_data["feature_key"] == PROMPT_FEATURE_WEB_SEARCH_SYNTHESIZER
                    and "một tổ chức/sản phẩm cụ thể" not in existing_content
                ):
                    existing.content = prompt_data["content"]
                    updated = True
                if not (existing.description or "").strip():
                    existing.description = prompt_data["description"]
                    updated = True
                if updated:
                    healed_prompt_count += 1
                continue

            has_active_in_feature = await db.execute(
                select(PromptConfig.id)
                .where(
                    PromptConfig.feature_key == prompt_data["feature_key"],
                    PromptConfig.is_active.is_(True),
                )
                .limit(1)
            )
            is_active = has_active_in_feature.scalar_one_or_none() is None

            db.add(
                PromptConfig(
                    name=prompt_data["name"],
                    feature_key=prompt_data["feature_key"],
                    content=prompt_data["content"],
                    description=prompt_data["description"],
                    is_active=is_active,
                )
            )
            added_prompt_count += 1

        if added_prompt_count > 0 or healed_prompt_count > 0:
            await db.commit()
            logger.info(
                "[SEED] Prompt seed: thêm mới %d, đồng bộ lại %d",
                added_prompt_count,
                healed_prompt_count,
            )
        else:
            logger.info("[SEED] Cấu hình Prompts đã tồn tại")

        # --- Seed LLM Providers ---
        existing_provider = await db.execute(select(LLMProviderConfig))
        provider_rows = existing_provider.scalars().all()

        if not provider_rows:
            local_models_raw = os.getenv("VLLM_MODELS_LIST", "")
            local_models = [m.strip() for m in local_models_raw.split(",") if m.strip()]
            if not local_models:
                local_models = [os.getenv("VLLM_MODEL_NAME", "google/gemma-4-E4B-it")]

            defaults = [
                LLMProviderConfig(
                    name="Local vLLM",
                    provider_type="local_vllm",
                    base_url=os.getenv("VLLM_BASE_URL", "http://127.0.0.1:8000/v1"),
                    api_key=os.getenv("VLLM_API_KEY", ""),
                    models=local_models,
                    description="Model local chạy qua vLLM",
                    is_active=True,
                    is_default=True,
                ),
                LLMProviderConfig(
                    name="NVIDIA Enterprise (OpenAI Compatible)",
                    provider_type="openai_compatible",
                    base_url="https://integrate.api.nvidia.com/v1",
                    api_key=os.getenv("NVIDIA_API_KEY", ""),
                    models=[
                        "meta/llama-3.1-70b-instruct", 
                        "meta/llama-3.1-405b-instruct"
                    ],
                    description="NVIDIA NIM API có sẵn các model cao cấp (cần NVIDIA API key).",
                    is_active=True,
                    is_default=False,
                ),
            ]

            for item in defaults:
                db.add(item)
            await db.commit()
            logger.info("[SEED] Đã khởi tạo cấu hình LLM providers mặc định")
        else:
            # Đảm bảo luôn có đúng 1 provider default trong các provider active (nếu có).
            active_default = await db.execute(
                select(LLMProviderConfig.id)
                .where(LLMProviderConfig.is_active.is_(True), LLMProviderConfig.is_default.is_(True))
                .limit(1)
            )
            if active_default.scalar_one_or_none() is None:
                first_active = await db.execute(
                    select(LLMProviderConfig)
                    .where(LLMProviderConfig.is_active.is_(True))
                    .order_by(LLMProviderConfig.id.asc())
                    .limit(1)
                )
                target = first_active.scalars().first()
                if target:
                    target.is_default = True
                    await db.commit()
            logger.info("[SEED] Cấu hình LLM Providers đã tồn tại")

        # --- Seed Telegram Bot Config ---
        existing_tg_bots = await db.execute(select(TelegramBotConfig))
        tg_bots = existing_tg_bots.scalars().all()
        if not tg_bots:
            db.add(
                TelegramBotConfig(
                    bot_id=os.getenv("TELEGRAM_BOT_ID", "change-me"),
                    bot_token=os.getenv("TELEGRAM_BOT_TOKEN", "change-me"),
                    is_active=os.getenv("TELEGRAM_BOT_TOKEN", "").strip() != "",
                )
            )
            await db.commit()
            logger.info("[SEED] Đã tạo Telegram bot mặc định từ ENV/placeholder")
        else:
            active_bots = [bot for bot in tg_bots if bot.is_active]
            if not active_bots:
                tg_bots[0].is_active = True
                await db.commit()
            elif len(active_bots) > 1:
                keep_id = active_bots[0].id
                for bot in active_bots[1:]:
                    bot.is_active = False
                await db.commit()
                logger.warning("[SEED] Có nhiều bot Telegram active, đã giữ bot id=%s", keep_id)
            logger.info("[SEED] Cấu hình Telegram bot đã tồn tại")

        # --- Seed Telegram Recipient Config ---
        existing_tg_recipients = await db.execute(select(TelegramRecipientConfig))
        tg_recipients = existing_tg_recipients.scalars().all()
        if not tg_recipients:
            db.add(
                TelegramRecipientConfig(
                    name="hoài an",
                    chat_id="1607805142",
                    is_active=True,
                )
            )
            await db.commit()
            logger.info("[SEED] Đã tạo Telegram recipient mặc định")
        else:
            logger.info("[SEED] Cấu hình Telegram recipient đã tồn tại")
