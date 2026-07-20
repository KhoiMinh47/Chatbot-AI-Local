"""
Module chứa các node xử lý trong pipeline upload tài liệu RAG.

Pipeline:
    1. docling_parse_node: Gọi Docling → trích xuất + chuẩn hóa markdown.
    2. chunking_node: Cắt markdown thành chunks theo heading (100-500 chữ).
    3. embedding_node: Tạo vector embedding cho từng chunk (BGE API).
"""

import logging

from agent_chatbot.agent_state.agent_state import UploadState
from agent_chatbot.node.util.rag_upload_util import (
    process_document_from_file,
    chunk_by_heading,
    embed_chunks,
)

logger = logging.getLogger(__name__)


# =============================================================================
# NODE 1: DOCLING PARSE
# =============================================================================


async def docling_parse_node(state: UploadState):
    """
    Node gọi Docling để trích xuất markdown từ file và chuẩn hóa output.

    Input:
        state (UploadState): State chứa input_file.

    Output:
        dict: Cập nhật status, docling_markdown.
    """

    logger.info("=" * 60)
    logger.info("[NODE] docling_parse_node — BẮT ĐẦU")
    logger.info("=" * 60)

    # Bước 1 & 2: Parse, Regex Fixing, AI Grammar Fixing (Gộp chung trong Util)
    logger.info("[STEP 1] Xử lý nội dung file...")

    docling_markdown = await process_document_from_file(state.get("input_file"))

    logger.info("[STEP 1] Trích xuất Text hoàn chỉnh")

    # Debug preview
    preview = docling_markdown[:500]
    logger.info("[DEBUG] Preview:\n%s", preview)

    logger.info("[NODE] docling_parse_node — HOÀN THÀNH ✓")

    return {
        "status": "pending",
        "docling_markdown": docling_markdown,
    }


# =============================================================================
# NODE 2: CHUNKING
# =============================================================================


async def chunking_node(state: UploadState):
    """
    Node cắt markdown thành chunks theo heading.

    Đảm bảo mỗi chunk 100-500 chữ. Chunks cùng heading bị tách
    sẽ chia sẻ heading_group_id để tìm nhau.

    Input:
        state (UploadState): State chứa docling_markdown.

    Output:
        dict: Cập nhật status, chunks.
    """

    logger.info("=" * 60)
    logger.info("[NODE] chunking_node — BẮT ĐẦU")
    logger.info("=" * 60)

    markdown = state.get("docling_markdown", "")
    chunks = chunk_by_heading(markdown)

    # Log thống kê
    word_counts = [len(c["content"].split()) for c in chunks]
    logger.info(
        "[CHUNK] Tổng: %d chunks | Min: %d words | Max: %d words | Avg: %d words",
        len(chunks),
        min(word_counts) if word_counts else 0,
        max(word_counts) if word_counts else 0,
        sum(word_counts) // len(word_counts) if word_counts else 0,
    )

    # Log chi tiết từng chunk
    for chunk in chunks:
        logger.info(
            "[CHUNK #%d] heading_group=%s | part=%d/%d | words=%d | heading=%s",
            chunk["chunk_index"],
            chunk["heading_group_id"],
            chunk["split_part"] + 1,
            chunk["total_parts"],
            len(chunk["content"].split()),
            chunk["heading"][:60] if chunk["heading"] else "(no heading)",
        )

    logger.info("[NODE] chunking_node — HOÀN THÀNH ✓")

    return {
        "status": "pending",
        "chunks": chunks,
    }


# =============================================================================
# NODE 3: EMBEDDING
# =============================================================================


async def embedding_node(state: UploadState):
    """
    Node tạo vector embedding cho từng chunk qua BGE API.

    Input:
        state (UploadState): State chứa chunks.

    Output:
        dict: Cập nhật status, chunks (bổ sung key "embedding").
    """

    logger.info("=" * 60)
    logger.info("[NODE] embedding_node — BẮT ĐẦU")
    logger.info("=" * 60)

    chunks = state.get("chunks", [])

    logger.info("[EMBEDDING] Bắt đầu embed %d chunks...", len(chunks))

    chunks_with_embeddings = await embed_chunks(chunks)

    # Verify
    embedded_count = sum(1 for c in chunks_with_embeddings if c.get("embedding"))
    logger.info(
        "[EMBEDDING] Đã embed %d/%d chunks thành công",
        embedded_count, len(chunks_with_embeddings),
    )

    logger.info("[NODE] embedding_node — HOÀN THÀNH ✓")

    return {
        "status": "pending",
        "chunks": chunks_with_embeddings,
    }
