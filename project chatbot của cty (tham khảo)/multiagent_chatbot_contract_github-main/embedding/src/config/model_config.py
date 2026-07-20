"""
Module cấu hình và load 2 model AI lên GPU.

- Qwen3-Embedding-0.6B: model embedding text → vector
- bge-reranker-v2-m3: model reranking query-document pairs

Cả 2 model đều chạy fp16 trên CUDA để tối ưu VRAM và tốc độ.
"""

import logging

import torch
from transformers import AutoTokenizer, AutoModel, AutoModelForSequenceClassification


logger = logging.getLogger(__name__)

# ================================================
# HẰNG SỐ CẤU HÌNH
# ================================================

# Tên model trên HuggingFace
EMBEDDING_MODEL_NAME = "nvidia/llama-nemotron-embed-1b-v2"
RERANKER_MODEL_NAME = "nvidia/llama-nemotron-rerank-1b-v2"

# Chọn device: CUDA nếu có GPU, fallback CPU
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# Dùng float16 trên GPU để tiết kiệm VRAM, float32 trên CPU
DTYPE = torch.float16 if DEVICE == "cuda" else torch.float32

torch.set_float32_matmul_precision('high')

def load_embedding_model():
    """
    Load Llama-Nemotron-Embed lên GPU.

    Input: Không có
    Output:
        tuple(AutoTokenizer, AutoModel) - tokenizer và model đã load

    Dùng sdpa + fp16 để tối ưu tốc độ inference trên GPU.
    Bật torch.compile để đẩy TFLOPS tối đa.
    """

    logger.info("Loading embedding model: %s", EMBEDDING_MODEL_NAME)

    try:
        tokenizer = AutoTokenizer.from_pretrained(
            EMBEDDING_MODEL_NAME,
            padding_side="left",
            trust_remote_code=True
        )
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
    except Exception as tokenizer_error:
        logger.error("Failed to load embedding tokenizer: %s", tokenizer_error)
        raise RuntimeError(f"Load embedding tokenizer thất bại: {tokenizer_error}") from tokenizer_error

    try:
        model = AutoModel.from_pretrained(
            EMBEDDING_MODEL_NAME,
            attn_implementation="sdpa",
            torch_dtype=DTYPE,
            low_cpu_mem_usage=True,
            trust_remote_code=True
        ).to(DEVICE)
        model.eval()
    except Exception as model_error:
        logger.error("Failed to load embedding model: %s", model_error)
        raise RuntimeError(f"Load embedding model thất bại: {model_error}") from model_error

    logger.info("Embedding model ready on %s (%s)", DEVICE, DTYPE)

    return tokenizer, model


def load_reranker_model():
    """
    Load Llama-Nemotron-Rerank lên GPU.

    Input: Không có
    Output:
        tuple(AutoTokenizer, AutoModelForSequenceClassification) - tokenizer và model
    """

    logger.info("Loading reranker model: %s", RERANKER_MODEL_NAME)

    try:
        tokenizer = AutoTokenizer.from_pretrained(
            RERANKER_MODEL_NAME,
            trust_remote_code=True
        )
        if tokenizer.pad_token is None:
            tokenizer.pad_token = tokenizer.eos_token
    except Exception as tokenizer_error:
        logger.error("Failed to load reranker tokenizer: %s", tokenizer_error)
        raise RuntimeError(f"Load reranker tokenizer thất bại: {tokenizer_error}") from tokenizer_error

    try:
        model = AutoModelForSequenceClassification.from_pretrained(
            RERANKER_MODEL_NAME,
            attn_implementation="sdpa",
            torch_dtype=DTYPE,
            low_cpu_mem_usage=True,
            trust_remote_code=True
        ).to(DEVICE)
        model.eval()
    except Exception as model_error:
        logger.error("Failed to load reranker model: %s", model_error)
        raise RuntimeError(f"Load reranker model thất bại: {model_error}") from model_error

    logger.info("Reranker model ready on %s (%s)", DEVICE, DTYPE)

    return tokenizer, model


# ── Singleton: load 1 lần khi import ─────────────────────────────────────────
embedding_tokenizer, embedding_model = load_embedding_model()
reranker_tokenizer, reranker_model = load_reranker_model()
logger.info("All models ready.")
