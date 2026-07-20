"""
Module xử lý embedding text bằng Qwen3-Embedding-0.6B.

Nhận danh sách text, tokenize, chạy model, trả về vector embedding
đã normalize (L2 norm = 1).
"""

import gc
import logging
from typing import List

import torch
import torch.nn.functional as F
from torch import Tensor

from src.config.model_config import (
    embedding_tokenizer,
    embedding_model,
    DEVICE
)

logger = logging.getLogger(__name__)

def last_token_pool(last_hidden_states: Tensor, attention_mask: Tensor) -> Tensor:
    """
    Lấy embedding từ token cuối cùng.

    Input:
        last_hidden_states (Tensor): Hidden states từ model, shape [batch, seq_len, hidden_dim].
        attention_mask (Tensor): Mask cho padding tokens, shape [batch, seq_len].

    Output:
        Tensor: Embedding vectors, shape [batch, hidden_dim].
    """

    # Tìm vị trí token thực cuối cùng
    sequence_lengths = attention_mask.sum(dim=1) - 1
    batch_size = last_hidden_states.shape[0]

    return last_hidden_states[
        torch.arange(batch_size, device=last_hidden_states.device),
        sequence_lengths
    ]

def embed_texts(texts: List[str]) -> List[List[float]]:
    """
    Tạo embedding vectors cho danh sách text.

    Input:
        texts (List[str]): Danh sách text cần embedding.

    Output:
        List[List[float]]: Danh sách embedding vectors đã normalize.

    Raises:
        RuntimeError: Khi tokenize hoặc inference thất bại.
    """

    # Bước 1: Tokenize
    try:
        batch_dict = embedding_tokenizer(
            texts,
            padding=True,
            truncation=True,
            max_length=4096,
            return_tensors="pt"
        )

        batch_dict = {k: v.to(DEVICE) for k, v in batch_dict.items()}
    except Exception as tokenize_error:
        logger.error("Embedding tokenize failed: %s", tokenize_error)
        raise RuntimeError(f"Tokenize thất bại: {tokenize_error}") from tokenize_error

    # Bước 2: Chạy model inference (tắt gradient để tiết kiệm VRAM)
    try:
        with torch.no_grad():
            outputs = embedding_model(**batch_dict)
    except Exception as inference_error:
        logger.error("Embedding inference failed: %s", inference_error)
        raise RuntimeError(f"Inference thất bại: {inference_error}") from inference_error

    # Bước 3: Trích xuất embedding từ token cuối + normalize L2
    try:
        embeddings = last_token_pool(
            outputs.last_hidden_state,
            batch_dict["attention_mask"]
        )
        embeddings = F.normalize(embeddings, p=2, dim=1)
        result = embeddings.cpu().tolist()
    except Exception as postprocess_error:
        logger.error("Embedding post-process failed: %s", postprocess_error)
        raise RuntimeError(f"Post-process thất bại: {postprocess_error}") from postprocess_error

    logger.info(f"Embedding thành công {len(texts)} texts, dim={len(result[0])}")

    # Giải phóng tensors trung gian để tránh tích lũy VRAM/RAM
    del batch_dict, outputs, embeddings
    if DEVICE == "cuda":
        torch.cuda.empty_cache()
    gc.collect()

    # Debug: tính cosine similarity nếu có >= 2 texts (text đầu tiên là câu hỏi)
    if len(result) >= 2:
        debug_cosine_similarity(result, texts)

    return result


def debug_cosine_similarity(
    embeddings: List[List[float]],
    texts: List[str]
) -> None:
    """
    Debug: tính cosine similarity giữa vector đầu tiên (câu hỏi) và các vector còn lại.

    Input:
        embeddings (List[List[float]]): Danh sách embedding vectors đã normalize L2.
        texts (List[str]): Danh sách text tương ứng với các vectors.

    Output:
        None - Kết quả được log ra console.

    Vì vectors đã normalize (L2 norm = 1), cosine similarity = dot product.
    Text đầu tiên trong list luôn là câu hỏi cần so sánh.
    """

    # Chuyển sang tensor để tính dot product nhanh hơn
    try:
        query_vector = torch.tensor(embeddings[0], dtype=torch.float32)
        document_vectors = torch.tensor(embeddings[1:], dtype=torch.float32)
    except Exception as convert_error:
        logger.error(f"[DEBUG] Lỗi chuyển đổi vector sang tensor: {convert_error}")
        return

    # Tính cosine similarity = dot product (vì vectors đã normalize L2)
    try:
        cosine_scores = torch.matmul(document_vectors, query_vector)
    except Exception as matmul_error:
        logger.error(f"[DEBUG] Lỗi tính dot product: {matmul_error}")
        return

    # Ghép score với text tương ứng, sắp xếp giảm dần theo score
    score_text_pairs = []

    for idx, score in enumerate(cosine_scores.tolist()):
        score_text_pairs.append((score, texts[idx + 1]))

    # Sắp xếp theo score giảm dần để thấy text nào liên quan nhất
    score_text_pairs.sort(key=lambda pair: pair[0], reverse=True)

    # Log kết quả debug
    logger.info("=" * 60)
    logger.info(f"[DEBUG COSINE] Câu hỏi: \"{texts[0]}\"")
    logger.info("-" * 60)

    for rank, (score, text) in enumerate(score_text_pairs, start=1):
        logger.info(f"  #{rank} | Score: {score:.4f} | Text: \"{text}\"")

    logger.info("=" * 60)
