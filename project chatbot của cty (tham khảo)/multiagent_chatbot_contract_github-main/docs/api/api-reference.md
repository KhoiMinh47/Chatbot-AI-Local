# API tham chiếu (tóm tắt)

Cập nhật lần cuối: 2026-05-13

Lưu ý: Danh sách dưới đây là nhóm endpoint chính để tra cứu nhanh. Chi tiết payload/response cần đối chiếu thêm trong controller và tài liệu thành phần.

## 1. Nhóm Auth/Admin

- Đăng nhập, đăng xuất, refresh token.
- Quản lý tài khoản, role, cấu hình hệ thống.
- Quản lý prompt/provider và các cấu hình runtime.

## 2. Nhóm RAG

- `POST /api/v1/rags/rag-upload`
- `POST /api/v1/rags/rag-contract`
- `POST /api/v1/rags/rag-contract-fast` (SSE)
- `GET /api/v1/rags/file`
- `DELETE /api/v1/rags/file`
- `GET /api/v1/rags/history`
- `GET /api/v1/rags/session*`

## 3. Nhóm Contract

- `POST /api/v1/contracts/upload-template`
- `POST /api/v1/contracts/upload-multiple-templates`
- `POST /api/v1/contracts/create-contract-templated`
- `POST /api/v1/contracts/create-contract-fast`
- `POST /api/v1/contracts/create-contract-reasoning`
- `GET /api/v1/contracts/download-contract/{filename}`
- `GET /api/v1/contracts/load-template`
- `GET /api/v1/contracts/load-contract`
- `DELETE /api/v1/contracts/delete-template/{id}`
- `DELETE /api/v1/contracts/delete-contract/{id}`

## 4. Nhóm service phụ trợ

- Parse-data service: `POST /api/v1/parse`, `GET /health`
- Embedding service: `POST /api/v1/embed`, `POST /api/v1/rerank`

## 5. Hướng dẫn dùng API

1. Dùng JWT cookie hoặc cơ chế auth đã cấu hình.
2. Với endpoint streaming, cần client hỗ trợ SSE.
3. Với upload file, đảm bảo đúng định dạng được hỗ trợ.
4. Theo dõi lỗi chi tiết ở backend logs khi response không như kỳ vọng.
