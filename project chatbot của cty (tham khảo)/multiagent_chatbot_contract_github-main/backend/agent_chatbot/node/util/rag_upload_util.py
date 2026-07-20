"""
Module tiện ích cho pipeline upload tài liệu RAG.

Bao gồm các chức năng:
    - docling_convert: Gọi Docling API (parse-data service) để parse file.
    - process_document_from_file: Quy trình parse file trọn gói.
    - fix_vietnamese_ocr_spacing: Sửa lỗi OCR khoảng trắng tiếng Việt.
    - chunk_by_heading: Cắt markdown thành chunks theo heading.
    - embed_chunks: Gọi BGE embedding API để tạo vector cho chunks.
"""

import logging
import os
import re

import httpx

logger = logging.getLogger(__name__)

# --- Hằng số cấu hình Docling API ---
DOCLING_URL = os.getenv("MARKER_URL")
DOCLING_REQUEST_TIMEOUT = 300.0
DOCLING_CONNECT_TIMEOUT = 10.0

# --- Hằng số cấu hình BGE Embedding API ---
BGE_BASE_URL = os.getenv("BGE_BASE_URL")
BGE_EMBED_PATH = os.getenv("BGE_EMBED_PATH")
BGE_EMBED_TIMEOUT = 120.0

# --- Hằng số chunking ---
CHUNK_MIN_WORDS = 100
CHUNK_MAX_WORDS = 300


# =============================================================================
# GỌI DOCLING API
# =============================================================================


async def docling_convert(file):
    """
    Gọi Docling (parse-data service) để trích xuất markdown từ file.

    Input:
        file (dict): File data dạng {"files": (filename, content, content_type)}.

    Output:
        dict: Response JSON từ Docling API.

    Raises:
        httpx.HTTPStatusError: Nếu Docling API trả về lỗi.
    """

    logger.info("[DOCLING] Gọi API: %s", DOCLING_URL)

    timeout_config = httpx.Timeout(
        DOCLING_REQUEST_TIMEOUT,
        connect=DOCLING_CONNECT_TIMEOUT,
    )

    # Đẩy thêm languages="vi" vào payload (form data) để tối ưu OCR tiếng Việt
    data_payload = {
        "languages": "vi",
        "force_ocr": "False",
    }

    async with httpx.AsyncClient(timeout=timeout_config) as client:
        response = await client.post(
            DOCLING_URL,
            files=file,
            data=data_payload
        )
        response.raise_for_status()

        logger.info("[DOCLING] HTTP status: %d", response.status_code)

        return response.json()


# =============================================================================
# CHUỖI XỬ LÝ FILE (PARSE -> MÀI GIŨA TEXT)
# =============================================================================

async def process_document_from_file(file) -> str:
    """
    Xử lý trọn gói quy trình đọc text từ file:
    1. Gọi Docling API trích xuất raw markdown
    2. Sửa lỗi OCR tiếng Việt bằng Regex
    3. Nhúng qua ViT5 để dịch ngữ nghĩa chuẩn xác lỗi chính tả

    Input:
        file: Dictionary input_file chứa ("files": (tên_file, nội_dung, type)).

    Output:
        str: Đoạn markdown string đã hoàn toàn trong sạch.
    """
    logger.info("[PROCESS] Bắt đầu xử lý file qua Docling API...")
    docling_response = await docling_convert(file)
    
    raw_content = docling_response["result"][0]["content"]
    file_name = docling_response["result"][0].get("file_name", "unknown")
    logger.info("[PROCESS] File: %s | OCR gốc nhận về: %d ký tự", file_name, len(raw_content))

    return raw_content


# =============================================================================
# CHUNKING THEO HEADING
# =============================================================================


def chunk_by_heading(markdown, min_words=CHUNK_MIN_WORDS, max_words=CHUNK_MAX_WORDS):
    """
    Cắt markdown thành chunks theo heading.

    Logic:
        1. Split theo heading regex (# ... ######).
        2. Section < min_words → merge với section tiếp theo.
        3. Section > max_words → chia nhỏ, giữ heading_group_id chung.
        4. Gán chunk_index theo thứ tự.

    Input:
        markdown (str): Markdown đã chuẩn hóa.
        min_words (int): Số chữ tối thiểu mỗi chunk (default: 100).
        max_words (int): Số chữ tối đa mỗi chunk (default: 500).

    Output:
        list[dict]: Danh sách chunks, mỗi chunk gồm:
            chunk_index, heading, content, heading_group_id,
            split_part, total_parts.
    """

    # --- Bước 1: Split markdown theo heading ---
    heading_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
    sections = []
    last_end = 0

    for match in heading_pattern.finditer(markdown):
        # Lưu đoạn text trước heading (nếu có)
        if match.start() > last_end:
            pre_text = markdown[last_end:match.start()].strip()
            if pre_text and sections:
                # Append vào section trước đó
                sections[-1]["content"] += "\n\n" + pre_text
            elif pre_text:
                # Đoạn text đầu file, trước heading đầu tiên
                sections.append({
                    "heading": "",
                    "content": pre_text,
                })

        sections.append({
            "heading": match.group(0).strip(),
            "content": "",
        })
        last_end = match.end()

    # Đoạn text sau heading cuối cùng
    if last_end < len(markdown):
        trailing_text = markdown[last_end:].strip()
        if trailing_text and sections:
            sections[-1]["content"] += "\n\n" + trailing_text
        elif trailing_text:
            sections.append({"heading": "", "content": trailing_text})

    # Nếu không có heading nào → coi toàn bộ là 1 section
    if not sections:
        sections.append({"heading": "", "content": markdown.strip()})

    # Xóa khoảng trắng thừa ở đầu content
    for sec in sections:
        sec["content"] = sec["content"].strip()

    # --- Bước 2: Merge sections nhỏ (< min_words) ---
    merged_sections = []
    buffer_heading = ""
    buffer_content = ""

    for sec in sections:
        full_text = (sec["heading"] + "\n" + sec["content"]).strip()
        word_count = len(full_text.split())

        if buffer_content:
            # Đang có buffer → gộp vào
            buffer_content += "\n\n" + full_text
            combined_words = len(buffer_content.split())

            if combined_words >= min_words:
                # Đủ lớn → flush buffer
                merged_sections.append({
                    "heading": buffer_heading,
                    "content": buffer_content,
                })
                buffer_heading = ""
                buffer_content = ""
        elif word_count < min_words:
            # Section quá nhỏ → bắt đầu buffer
            buffer_heading = sec["heading"]
            buffer_content = full_text
        else:
            # Section đủ lớn → giữ nguyên
            merged_sections.append({
                "heading": sec["heading"],
                "content": full_text,
            })

    # Flush buffer còn lại
    if buffer_content:
        if merged_sections:
            # Gộp vào section cuối cùng
            merged_sections[-1]["content"] += "\n\n" + buffer_content
        else:
            merged_sections.append({
                "heading": buffer_heading,
                "content": buffer_content,
            })

    # --- Bước 3: Chia sections lớn (> max_words) ---
    chunks = []
    heading_group_counter = 0

    for sec in merged_sections:
        content = sec["content"]
        word_count = len(content.split())
        heading_gid = f"h_{heading_group_counter}"

        if word_count <= max_words:
            # Vừa đủ → 1 chunk
            chunks.append({
                "heading": sec["heading"],
                "content": content,
                "heading_group_id": heading_gid,
                "split_part": 0,
                "total_parts": 1,
            })
        else:
            # Quá lớn → chia nhỏ theo câu/paragraph
            sub_chunks = _split_large_section(content, max_words)

            for part_idx, sub_content in enumerate(sub_chunks):
                chunks.append({
                    "heading": sec["heading"],
                    "content": sub_content,
                    "heading_group_id": heading_gid,
                    "split_part": part_idx,
                    "total_parts": len(sub_chunks),
                })

        heading_group_counter += 1

    # --- Bước 4: Gán chunk_index ---
    for idx, chunk in enumerate(chunks):
        chunk["chunk_index"] = idx

    logger.info(
        "[CHUNKING] Tạo %d chunks từ %d sections | min=%d max=%d words",
        len(chunks), len(merged_sections), min_words, max_words,
    )

    return chunks


def _split_large_section(text, max_words):
    """
    Chia 1 đoạn text lớn thành nhiều phần ≤ max_words.

    Chia theo paragraph (\n\n) trước, fallback theo câu,
    cuối cùng fallback theo từ.

    Input:
        text (str): Đoạn text cần chia.
        max_words (int): Số từ tối đa mỗi phần.

    Output:
        list[str]: Danh sách các phần đã chia.
    """

    paragraphs = re.split(r'\n{2,}', text)
    parts = []
    current_part = ""

    for para in paragraphs:
        candidate = (current_part + "\n\n" + para).strip() if current_part else para

        if len(candidate.split()) <= max_words:
            current_part = candidate
        else:
            if current_part:
                parts.append(current_part)
            # Nếu paragraph đơn lẻ vẫn > max_words → cắt cứng theo từ
            if len(para.split()) > max_words:
                words = para.split()
                for i in range(0, len(words), max_words):
                    parts.append(" ".join(words[i:i + max_words]))
                current_part = ""
            else:
                current_part = para

    if current_part:
        parts.append(current_part)

    return parts if parts else [text]


# =============================================================================
# GỌI BGE EMBEDDING API
# =============================================================================


async def embed_chunks(chunks):
    """
    Gọi BGE embedding API để tạo vector cho danh sách chunks.

    Input:
        chunks (list[dict]): Danh sách chunks, mỗi chunk có key "content".

    Output:
        list[dict]: Chunks đã bổ sung key "embedding" (list[float]).

    Raises:
        httpx.HTTPStatusError: Nếu embedding API trả về lỗi.
    """

    if not chunks:
        return chunks

    bge_embed_url = f"{BGE_BASE_URL}{BGE_EMBED_PATH}"
    texts = [chunk["content"] for chunk in chunks]

    logger.info(
        "[EMBEDDING] Gọi API: %s | %d chunks", bge_embed_url, len(texts)
    )

    timeout_config = httpx.Timeout(BGE_EMBED_TIMEOUT, connect=10.0)

    async with httpx.AsyncClient(timeout=timeout_config) as client:
        response = await client.post(bge_embed_url, json={"texts": texts})
        response.raise_for_status()
        data = response.json()

    embeddings = data["result"]

    logger.info(
        "[EMBEDDING] Nhận %d vectors, dim=%d",
        len(embeddings), len(embeddings[0]) if embeddings else 0,
    )
    

    # Gắn embedding vào từng chunk
    for idx, chunk in enumerate(chunks):
        chunk["embedding"] = embeddings[idx]

    return chunks
