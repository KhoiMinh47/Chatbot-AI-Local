"""
Module định nghĩa các endpoint cho embedding và reranking.

- POST /embed: embedding text → vectors
- POST /rerank: xếp hạng documents theo query
"""

import logging
import asyncio

from fastapi import APIRouter

from src.model.request_response_model import EmbeddingRequest, RerankRequest, ApiResponse
from src.service.embedding_service import embed_texts
from src.service.rerank_service import rerank_documents


logger = logging.getLogger(__name__)

# Giới hạn số lượng text / document tối đa mỗi request
MAX_TEXTS_PER_REQUEST = 1000
MAX_DOCUMENTS_PER_REQUEST = 1000

router = APIRouter()


@router.post("/embed", response_model=ApiResponse)
async def embed_endpoint(request: EmbeddingRequest):
    """
    Endpoint tạo embedding vectors cho danh sách text.

    Input:
        request (EmbeddingRequest): { texts: ["text1", "text2", ...] }

    Output:
        ApiResponse: { status: 200, result: [[0.1, ...], [...]], description: "" }
    """

    # --- Validate: danh sách texts không rỗng ---
    try:
        if not request.texts or len(request.texts) == 0:
            logger.warning("Client gửi danh sách texts rỗng")

            return ApiResponse(
                status=400,
                result="",
                description="Vui lòng gửi ít nhất 1 text."
            )
    except Exception as validate_error:
        logger.error(f"Lỗi validate texts: {validate_error}")

        return ApiResponse(
            status=400,
            result="",
            description=f"Lỗi validate: {str(validate_error)}"
        )

    # --- Validate: số lượng texts ---
    try:
        if len(request.texts) > MAX_TEXTS_PER_REQUEST:
            logger.warning(f"Client gửi quá {MAX_TEXTS_PER_REQUEST} texts: {len(request.texts)}")

            return ApiResponse(
                status=400,
                result="",
                description=f"Tối đa {MAX_TEXTS_PER_REQUEST} texts mỗi request. Bạn đã gửi {len(request.texts)}."
            )
    except Exception as count_error:
        logger.error(f"Lỗi kiểm tra số lượng: {count_error}")

        return ApiResponse(
            status=400,
            result="",
            description=f"Lỗi kiểm tra số lượng: {str(count_error)}"
        )

    # --- Xử lý: embedding ---
    try:
        embeddings = await asyncio.to_thread(embed_texts, request.texts)

        logger.info(f"Embed thành công {len(request.texts)} texts")

        return ApiResponse(
            status=200,
            result=embeddings,
            description=""
        )
    except RuntimeError as runtime_error:
        logger.error(f"Lỗi embedding: {runtime_error}")

        return ApiResponse(
            status=500,
            result="",
            description=f"Lỗi embedding: {str(runtime_error)}"
        )
    except Exception as unexpected_error:
        logger.exception(f"Lỗi không xác định khi embedding: {unexpected_error}")

        return ApiResponse(
            status=500,
            result="",
            description=f"Lỗi server: {str(unexpected_error)}"
        )


@router.post("/rerank", response_model=ApiResponse)
async def rerank_endpoint(request: RerankRequest):
    """
    Endpoint xếp hạng documents theo mức độ liên quan với query.

    Input:
        request (RerankRequest): { query: "...", documents: ["doc1", "doc2", ...] }

    Output:
        ApiResponse: { status: 200, result: [{index, document, score}, ...], description: "" }
    """

    # --- Validate: query không rỗng ---
    try:
        if not request.query or request.query.strip() == "":
            logger.warning("Client gửi query rỗng")

            return ApiResponse(
                status=400,
                result="",
                description="Query không được để trống."
            )
    except Exception as query_error:
        logger.error(f"Lỗi validate query: {query_error}")

        return ApiResponse(
            status=400,
            result="",
            description=f"Lỗi validate query: {str(query_error)}"
        )

    # --- Validate: documents không rỗng ---
    try:
        if not request.documents or len(request.documents) == 0:
            logger.warning("Client gửi danh sách documents rỗng")

            return ApiResponse(
                status=400,
                result="",
                description="Vui lòng gửi ít nhất 1 document."
            )
    except Exception as doc_error:
        logger.error(f"Lỗi validate documents: {doc_error}")

        return ApiResponse(
            status=400,
            result="",
            description=f"Lỗi validate documents: {str(doc_error)}"
        )

    # --- Validate: số lượng documents ---
    try:
        if len(request.documents) > MAX_DOCUMENTS_PER_REQUEST:
            logger.warning(f"Client gửi quá {MAX_DOCUMENTS_PER_REQUEST} documents: {len(request.documents)}")

            return ApiResponse(
                status=400,
                result="",
                description=f"Tối đa {MAX_DOCUMENTS_PER_REQUEST} documents mỗi request. Bạn đã gửi {len(request.documents)}."
            )
    except Exception as count_error:
        logger.error(f"Lỗi kiểm tra số lượng documents: {count_error}")

        return ApiResponse(
            status=400,
            result="",
            description=f"Lỗi kiểm tra số lượng: {str(count_error)}"
        )

    # --- Xử lý: reranking ---
    try:
        results = await asyncio.to_thread(rerank_documents, request.query, request.documents)

        logger.info(f"Rerank thành công {len(request.documents)} documents")

        return ApiResponse(
            status=200,
            result=results,
            description=""
        )
    except RuntimeError as runtime_error:
        logger.error(f"Lỗi reranking: {runtime_error}")

        return ApiResponse(
            status=500,
            result="",
            description=f"Lỗi reranking: {str(runtime_error)}"
        )
    except Exception as unexpected_error:
        logger.exception(f"Lỗi không xác định khi reranking: {unexpected_error}")

        return ApiResponse(
            status=500,
            result="",
            description=f"Lỗi server: {str(unexpected_error)}"
        )
