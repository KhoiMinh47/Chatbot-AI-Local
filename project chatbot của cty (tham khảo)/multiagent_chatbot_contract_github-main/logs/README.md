# Chỉ mục logs dự án

Cập nhật: 2026-05-23 18:27

Thư mục này lưu log phiên làm việc của dự án, không phải log debug runtime của ứng dụng.

## Cấu trúc

- `tasks/YYYY/`: log theo từng task phát triển, sửa lỗi, tối ưu.
- `testing/YYYY/`: log kiểm thử thủ công/tự động, ảnh chụp, kết quả smoke test.
- `cleanup/YYYY/`: log các lần dọn cache, dữ liệu tạm, source artifact.

## Quy tắc ghi log

- Mỗi log cần có thời gian, mục tiêu, việc đã làm, kết quả verify và blocker nếu có.
- Không copy output dài; chỉ ghi kết luận và đường dẫn evidence.
- Không ghi secret thật vào log.

## Log đang hoạt động

- `tasks/2026/2026-05-23-toi-uu-vllm-rag-env-cleanup-docs.md`
