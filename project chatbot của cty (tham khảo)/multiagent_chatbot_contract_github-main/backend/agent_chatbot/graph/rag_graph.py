"""
Module xây dựng workflow LangGraph cho các Agent xử lý RAG.

Upload Workflow:
    docling_parse_node → chunking_node → embedding_node → END
"""

from langgraph.graph import StateGraph, END
from agent_chatbot.agent_state.agent_state import UploadState
from agent_chatbot.node.rag_upload_pipeline import (
    docling_parse_node,
    chunking_node,
    embedding_node,
)


# =============================================================================
# UPLOAD WORKFLOW - Xử lý upload và phân tích tài liệu
# =============================================================================

workflow = StateGraph(UploadState)

# Đăng ký các node
workflow.add_node("docling_parse_node", docling_parse_node)
workflow.add_node("chunking_node", chunking_node)
workflow.add_node("embedding_node", embedding_node)

# Luồng: Docling parse → Chunking → Embedding → END
workflow.set_entry_point("docling_parse_node")
workflow.add_edge("docling_parse_node", "chunking_node")
workflow.add_edge("chunking_node", "embedding_node")
workflow.add_edge("embedding_node", END)

app_upload_workflow = workflow.compile()


# =============================================================================
# RAG CONTRACT FAST WORKFLOW - Tìm nhanh top hợp đồng
# =============================================================================

from agent_chatbot.agent_state.agent_state import RagContractFastState, RagWebSearchState
from agent_chatbot.node.rag_query_pipeline import (
    node_search,
    node_seach_with_path,
    node_asisstant,
    node_check_path_session,
    node_search_path_user_chose,
    node_fetch_history,
    node_web_coordinator,
    node_web_domain_mapper,
    node_web_url_selector,
    node_web_fetch_clean,
    node_web_rerank,
    node_web_summarize,
    node_web_synthesize,
    node_web_verify,
)

rag_fast_workflow = StateGraph(RagContractFastState)

# Đăng ký các node
rag_fast_workflow.add_node("node_check_path_session", node_check_path_session)
rag_fast_workflow.add_node("node_search", node_search)
rag_fast_workflow.add_node("node_seach_with_path", node_seach_with_path)
rag_fast_workflow.add_node("node_search_path_user_chose", node_search_path_user_chose)
rag_fast_workflow.add_node("node_fetch_history", node_fetch_history)
rag_fast_workflow.add_node("node_asisstant", node_asisstant)


def _route_by_path_list(state: dict) -> str:
    """Router: nếu có path_list → luồng user chọn file, không có → luồng tự động."""
    path_list = state.get("path_list", [])
    if path_list:
        return "node_search_path_user_chose"
    return "node_search"


# Entry point: kiểm tra path_list
rag_fast_workflow.set_entry_point("node_check_path_session")

# Conditional edge từ node_check_path_session
rag_fast_workflow.add_conditional_edges(
    "node_check_path_session",
    _route_by_path_list,
    {
        "node_search": "node_search",
        "node_search_path_user_chose": "node_search_path_user_chose",
    },
)

# Luồng tự động (không có path_list): node_search → node_seach_with_path → node_fetch_history → node_asisstant
rag_fast_workflow.add_edge("node_search", "node_seach_with_path")
rag_fast_workflow.add_edge("node_seach_with_path", "node_fetch_history")

# Luồng user chọn file: node_search_path_user_chose → node_fetch_history
rag_fast_workflow.add_edge("node_search_path_user_chose", "node_fetch_history")

# Bước gọi LLM cuối cùng
rag_fast_workflow.add_edge("node_fetch_history", "node_asisstant")

# Kết thúc
rag_fast_workflow.add_edge("node_asisstant", END)

app_rag_contract_fast_workflow = rag_fast_workflow.compile()


# =============================================================================
# RAG WEB SEARCH WORKFLOW - Tra cứu web có điều phối
# =============================================================================

rag_web_workflow = StateGraph(RagWebSearchState)

rag_web_workflow.add_node("node_web_coordinator", node_web_coordinator)
rag_web_workflow.add_node("node_web_domain_mapper", node_web_domain_mapper)
rag_web_workflow.add_node("node_web_url_selector", node_web_url_selector)
rag_web_workflow.add_node("node_web_fetch_clean", node_web_fetch_clean)
rag_web_workflow.add_node("node_web_rerank", node_web_rerank)
rag_web_workflow.add_node("node_web_summarize", node_web_summarize)
rag_web_workflow.add_node("node_fetch_history", node_fetch_history)
rag_web_workflow.add_node("node_web_synthesize", node_web_synthesize)
rag_web_workflow.add_node("node_web_verify", node_web_verify)


def _route_web_verify(state: dict) -> str:
    """Retry research loop khi verifier thấy evidence/answer chưa đủ tin cậy."""
    if state.get("web_should_retry"):
        return "node_web_coordinator"
    return END


rag_web_workflow.set_entry_point("node_web_coordinator")
rag_web_workflow.add_edge("node_web_coordinator", "node_web_domain_mapper")
rag_web_workflow.add_edge("node_web_domain_mapper", "node_web_url_selector")
rag_web_workflow.add_edge("node_web_url_selector", "node_web_fetch_clean")
rag_web_workflow.add_edge("node_web_fetch_clean", "node_web_rerank")
rag_web_workflow.add_edge("node_web_rerank", "node_web_summarize")
rag_web_workflow.add_edge("node_web_summarize", "node_fetch_history")
rag_web_workflow.add_edge("node_fetch_history", "node_web_synthesize")
rag_web_workflow.add_edge("node_web_synthesize", "node_web_verify")
rag_web_workflow.add_conditional_edges(
    "node_web_verify",
    _route_web_verify,
    {
        "node_web_coordinator": "node_web_coordinator",
        END: END,
    },
)

app_rag_web_search_workflow = rag_web_workflow.compile()
