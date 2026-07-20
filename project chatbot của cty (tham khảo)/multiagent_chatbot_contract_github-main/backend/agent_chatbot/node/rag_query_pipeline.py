"""
Pipeline nodes cho RAG Fast Contract.

Khai báo các node LangGraph và gọi qua file query_contract_ultil.py để xử lý logic chính.
Mỗi node push SSE event vào queue để frontend biết đang chạy node nào.
"""

import logging
from agent_chatbot.node.util.rag_query_util import (
    node_search_logic,
    node_seach_with_path_logic,
    node_asisstant_logic,
    node_search_path_user_chose_logic,
    node_fetch_history_logic,
    node_web_coordinator_logic,
    node_web_domain_mapper_logic,
    node_web_url_selector_logic,
    node_web_fetch_clean_logic,
    node_web_rerank_logic,
    node_web_summarize_logic,
    node_web_synthesize_logic,
    node_web_verify_logic,
)

logger = logging.getLogger(__name__)


async def _push_sse(state: dict, title: str, mess: str = "", end: bool = False):
    """Helper: push SSE event vào queue nếu có."""
    queue = state.get("sse_queue")
    if queue:
        await queue.put({
            "user_id": state.get("user_id", ""),
            "session_id": state.get("session_id", -1),
            "title": title,
            "mess": mess,
            "end": end,
        })


async def node_search(state: dict) -> dict:
    """Tạo embedding, tìm Qdrant points và rerank."""
    await _push_sse(state, title="Đang tìm kiếm tài liệu...")
    return await node_search_logic(state)


async def node_seach_with_path(state: dict) -> dict:
    """Lấy dữ liệu context chi tiết cho từng path."""
    await _push_sse(state, title="Đang trích xuất context...")
    return await node_seach_with_path_logic(state)


async def node_asisstant(state: dict) -> dict:
    """LLM phân tích và sinh ra câu trả lời cuối cùng (stream tokens)."""
    await _push_sse(state, title="Đang tạo câu trả lời...")
    return await node_asisstant_logic(state)


async def node_fetch_history(state: dict) -> dict:
    """Lấy thông tin lịch sử."""
    await _push_sse(state, title="Đang truy xuất lịch sử trò chuyện...")
    return await node_fetch_history_logic(state)


async def node_check_path_session(state: dict) -> dict:
    """Kiểm tra path_list trong state để routing. Pass-through node."""
    path_list = state.get("path_list", [])
    if path_list:
        await _push_sse(state, title="Đã nhận danh sách file từ người dùng...")
        logger.info("[CHECK_PATH] Có %d paths từ user", len(path_list))
    else:
        await _push_sse(state, title="Đang tìm kiếm tài liệu tự động...")
        logger.info("[CHECK_PATH] Không có path_list, chạy pipeline tự động")
    return state


async def node_search_path_user_chose(state: dict) -> dict:
    """Đã có path_list — search + rerank theo các file user chọn."""
    await _push_sse(state, title="Đang tìm kiếm theo file đã chọn...")
    return await node_search_path_user_chose_logic(state)


async def node_web_coordinator(state: dict) -> dict:
    """Coordinator: phân tích intent + tạo search plan cho web search."""
    await _push_sse(state, title="Coordinator đang phân tích yêu cầu web search...")
    return await node_web_coordinator_logic(state)


async def node_web_domain_mapper(state: dict) -> dict:
    """Map domain -> candidate URLs (sitemap/homepage/cached)."""
    await _push_sse(state, title="Đang lập bản đồ URL theo domain...")
    return await node_web_domain_mapper_logic(state)


async def node_web_url_selector(state: dict) -> dict:
    """Chọn top URLs phù hợp nhất trước khi fetch sâu."""
    await _push_sse(state, title="Đang chọn URL phù hợp nhất với câu hỏi...")
    return await node_web_url_selector_logic(state)


async def node_web_fetch_clean(state: dict) -> dict:
    """Fetch và làm sạch nội dung web."""
    await _push_sse(state, title="Đang tải và làm sạch nội dung web...")
    return await node_web_fetch_clean_logic(state)


async def node_web_rerank(state: dict) -> dict:
    """Rerank evidence từ các URL đã fetch."""
    await _push_sse(state, title="Đang xếp hạng bằng chứng từ web...")
    return await node_web_rerank_logic(state)


async def node_web_summarize(state: dict) -> dict:
    """Tóm tắt/lọc nhiễu evidence theo từng câu hỏi nghiên cứu."""
    await _push_sse(state, title="Đang lọc nhiễu và tóm tắt bằng chứng web...")
    return await node_web_summarize_logic(state)


async def node_web_synthesize(state: dict) -> dict:
    """Tổng hợp câu trả lời có trích dẫn nguồn web."""
    await _push_sse(state, title="Đang tổng hợp câu trả lời từ nguồn web...")
    return await node_web_synthesize_logic(state)


async def node_web_verify(state: dict) -> dict:
    """Kiểm định nhanh độ tin cậy đầu ra."""
    await _push_sse(state, title="Đang kiểm định độ tin cậy...")
    return await node_web_verify_logic(state)
