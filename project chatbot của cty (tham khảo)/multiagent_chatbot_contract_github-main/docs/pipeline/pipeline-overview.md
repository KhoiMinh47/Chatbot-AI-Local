# Tổng quan pipeline

Cập nhật lần cuối: 2026-05-13

## 1. Các pipeline trọng yếu

- RAG pipeline: truy xuất tri thức nội bộ + tổng hợp phản hồi.
- Contract pipeline: sinh và quản lý hợp đồng.
- Upload/index pipeline: parse, chunk, embedding, lưu vector.
- Web search pipeline: mở rộng evidence từ nguồn open-web.

## 2. RAG pipeline

Luồng cơ bản:

1. Nhận query.
2. Nạp history ngắn hạn + semantic.
3. Retrieval nội bộ (và web nếu cần).
4. Compose prompt.
5. Gọi vLLM.
6. Lưu kết quả và cập nhật cache.

Tài liệu tham khảo chi tiết cũ:

- `pipeline/rag_pipeline.md`

## 3. Contract pipeline

Luồng cơ bản:

1. Nhận dữ liệu hợp đồng.
2. Chọn template hoặc LLM generation.
3. Xuất file.
4. Lưu file và metadata.
5. Trả về cho người dùng.

Tài liệu tham khảo chi tiết cũ:

- `pipeline/contract_pipeline.md`

## 4. Upload/index pipeline

Luồng cơ bản:

1. Upload file.
2. Parse document.
3. Chunking theo heading.
4. Embedding + ghi vector vào Qdrant.
5. Lưu fulltext/metadata cho truy xuất.

## 5. Web search pipeline (hardened)

Luồng hiện tại:

1. Coordinator rewrite + decomposition query.
2. Domain mapper gọi broker/provider.
3. URL selector + prefetch title.
4. Fetch clean + rerank evidence.
5. Synthesize có citation.
6. Verify confidence và lưu debug state.

Tài liệu tham khảo chi tiết cũ:

- `docs/WEB_SEARCH_PIPELINE_PRODUCTION.md`
- `plan/WEB_SEARCH_PIPELINE_PLAN.md`
- `plan/WEB_SEARCH_PRODUCTION_HARDENING_MASTER_PLAN.md`
