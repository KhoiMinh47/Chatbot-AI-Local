"""
Module xử lý reranking bằng bge-reranker-v2-m3.

Nhận query + danh sách documents, tính relevance score cho từng cặp,
trả về kết quả sắp xếp theo score giảm dần.
"""

import gc
import logging
from typing import List, Dict, Any

import torch

from src.config.model_config import (
    reranker_tokenizer,
    reranker_model,
    DEVICE
)

logger = logging.getLogger(__name__)

def rerank_documents(query: str, documents: List[str]) -> List[Dict[str, Any]]:
    """
    Tính relevance score cho từng document so với query, sắp xếp giảm dần.

    Input:
        query (str): Câu truy vấn.
        documents (List[str]): Danh sách document cần xếp hạng.

    Output:
        List[Dict[str, Any]]: Danh sách kết quả, mỗi item gồm:
            - index (int): Vị trí gốc của document
            - document (str): Nội dung document
            - score (float): Relevance score (cao = liên quan hơn)

    Raises:
        RuntimeError: Khi tokenize hoặc inference thất bại.
    """

    pairs = [[query, doc] for doc in documents]

    try:
        inputs = reranker_tokenizer(
            pairs,
            padding=True,
            truncation=True,
            max_length=2048,
            return_tensors="pt"
        )
        inputs = {k: v.to(DEVICE) for k, v in inputs.items()}
    except Exception as tokenize_error:
        logger.error("Reranker tokenize failed: %s", tokenize_error)
        raise RuntimeError(f"Tokenize thất bại: {tokenize_error}") from tokenize_error

    try:
        with torch.no_grad():
            outputs = reranker_model(**inputs, return_dict=True)
            scores = outputs.logits.view(-1).float().cpu().tolist()
    except Exception as inference_error:
        logger.error("Reranker inference failed: %s", inference_error)
        raise RuntimeError(f"Inference thất bại: {inference_error}") from inference_error

    results = [
        {"index": idx, "document": doc, "score": round(score, 6)}
        for idx, (doc, score) in enumerate(zip(documents, scores))
    ]
    results.sort(key=lambda x: x["score"], reverse=True)

    # Giải phóng tensors trung gian
    del inputs, outputs
    if DEVICE == "cuda":
        torch.cuda.empty_cache()
    gc.collect()

    return results
