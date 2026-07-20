"""
Module định nghĩa các State (trạng thái) cho từng Agent trong hệ thống multi-agent.

Mỗi TypedDict đại diện cho cấu trúc dữ liệu được truyền qua các node
trong LangGraph, giúp kiểm soát luồng dữ liệu giữa các bước xử lý.
"""

from typing import TypedDict, List, Optional, Annotated, Dict, Any, Set
import operator


class ContractState(TypedDict):
    """
    State cho Agent xử lý hợp đồng (Contract).

    Attributes:
        user_input (str): Câu hỏi / yêu cầu của người dùng.
        template_content (str): Nội dung markdown của template (từ PostgreSQL).
        contract_name (str): Tên file hợp đồng (clean, không đuôi).
        llm_response (str): Câu trả lời từ LLM.
        mess (str): Tin nhắn phản hồi cho người dùng.
        status (str): Trạng thái xử lý (ok/error).
        path_name (str): Tên file hợp đồng đầu ra (với đuôi .docx).
    """

    user_input: str
    template_content: str
    contract_name: str
    model_name: str
    llm_response: str
    mess: str
    status: str
    path_name: str
    # Streaming SSE support
    user_id: str
    session_id: int
    sse_queue: Any   # asyncio.Queue để stream SSE events, None nếu không dùng streaming


class UploadTemplateState(TypedDict):
    """
    State cho pipeline upload template hợp đồng.

    Quản lý quá trình parse file bằng Docling và lưu trữ.

    Attributes:
        filename (str): Tên file template.
        file_content (bytes): Nội dung file template.
        file_path (str): Đường dẫn file đã lưu trên server.
        minio_path (str): Đường dẫn file trên MinIO (bucket/filename).
        status (str): Trạng thái xử lý (ok/error).
        mess (str): Thông báo lỗi nếu có.
        parsed_content (str): Nội dung markdown sau khi Docling parse.
    """

    filename: str
    file_content: bytes
    file_path: str
    minio_path: str
    status: str
    mess: str
    parsed_content: str


class UploadState(TypedDict):
    """
    State cho Agent xử lý upload và phân tích tài liệu.

    Quản lý quá trình upload file, trích xuất nội dung bằng Docling,
    cắt chunk, tạo embedding, và lưu database.

    Attributes:
        input_file (Dict): Thông tin file upload (tên, content, content_type).
        status (str): Trạng thái xử lý hiện tại.
        document_path (str): Đường dẫn lưu trữ tài liệu trên server.
        docling_markdown (str): Markdown đã chuẩn hóa từ Docling.
        document_id (int): ID record trong PostgreSQL (document_fulltext).
        chunks (List[Dict]): Danh sách chunks sau khi cắt + embedding.
    """

    input_file: Dict
    status: str
    document_path: str

    # Markdown sau khi Docling trích xuất và chuẩn hóa từ file gốc
    docling_markdown: str

    # Tóm tắt thực thể của tài liệu (Bên A, Bên B, Địa điểm, Gói thầu, Giá trị...)
    document_summary: str

    # ID record trong PostgreSQL (document_fulltext) — liên kết chunk → file gốc
    document_id: int

    # Danh sách chunks, mỗi chunk là dict chứa:
    #   chunk_index, heading, content, heading_group_id,
    #   split_part, total_parts, embedding (list[float])
    chunks: List[Dict]


class RagContractFastState(TypedDict):
    """
    State cho Agent xử lý truy vấn RAG Fast.
    
    Attributes:
        user_id (str): ID định danh người dùng.
        session_id (int): ID phiên làm việc hiện tại.
        user_input (str): Câu hỏi của người dùng.
        rewritten_query (str): Câu hỏi đã được LLM viết lại để tối ưu thực thể.
        intent (str): Phân loại mục đích (statistical, deep_search, greeting).
        model_name (str): Tên model LLM để sử dụng.
        path_list (List[str]): Danh sách file paths do user chọn (rỗng = tự động tìm).
        search_results (List[Dict]): Danh sách các paths từ Qdrant (mỗi item dạng {"path": str, "score": float}).
        document_summaries (List[Dict]): Danh sách các bản tóm tắt tài liệu tìm được.
        context_with_path (str): Chuỗi đoạn văn bản ngữ cảnh hoàn chỉnh ghép nối tất cả các chunk thu thập được từ Qdrant.
        chat_history (str): Tiền sử trò chuyện của user và bot trong phiên.
        assistant_response (str): Câu trả lời cuối cùng từ trợ lý.
        sse_queue (Any): asyncio.Queue để stream SSE events ra controller (optional).
    """
    
    user_id: str
    session_id: int
    user_input: str
    rewritten_query: str
    intent: str
    model_name: str
    path_list: List[str]
    search_results: List[Dict]
    document_summaries: List[Dict]
    context_with_path: str
    chat_history: str
    assistant_response: str
    sse_queue: Any


class RagWebSearchState(TypedDict):
    """
    State cho pipeline Web Search (nhánh riêng trong mode Query).

    Lưu ý: Session/history vẫn dùng chung với pipeline RAG fast ở service layer.
    """

    user_id: str
    session_id: int
    user_input: str
    model_name: str
    query_flow: str
    web_urls: List[str]
    web_mode: str

    rewritten_query: str
    search_plan: Dict[str, Any]
    candidate_urls: List[str]
    selected_urls: List[str]
    selected_url_titles: Dict[str, str]
    web_documents: List[Dict[str, Any]]
    reranked_evidence: List[Dict[str, Any]]
    web_loop_iteration: int
    web_should_retry: bool
    web_retry_reasons: List[str]
    web_answer_streamed: bool
    chat_history: str
    assistant_response: str
    confidence: str
    sse_queue: Any
    web_search_debug: Dict[str, Any]
    web_fetch_debug: Dict[str, Any]
    web_adaptive_debug: Dict[str, Any]
    web_summary_debug: Dict[str, Any]
    web_verify_debug: Dict[str, Any]
