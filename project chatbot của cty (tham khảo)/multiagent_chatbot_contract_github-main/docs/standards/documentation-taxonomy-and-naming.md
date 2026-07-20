# Chuẩn taxonomy và đặt tên tài liệu

Cập nhật lần cuối: 2026-05-13

## 1. Cấu trúc chuẩn

- `docs/overview/`: tài liệu giới thiệu dự án.
- `docs/architecture/`: kiến trúc tổng thể và chi tiết.
- `docs/backend/`: tài liệu backend.
- `docs/frontend/`: tài liệu frontend.
- `docs/pipeline/`: tài liệu pipeline nghiệp vụ.
- `docs/deployment/`: hướng dẫn triển khai.
- `docs/operations/`: runbook vận hành và sự cố.
- `docs/api/`: tham chiếu endpoint.
- `docs/history/`: lịch sử và tổng hợp kế hoạch.
- `docs/cicd/`: chính sách và runbook CI/CD.
- `docs/reports/`: báo cáo theo task.

## 2. Quy tắc đặt tên file

- Dùng `lowercase-kebab-case.md`.
- Tên ngắn, mô tả đúng mục đích.
- Tránh tên chung chung như `new.md`, `temp.md`, `update.md`.

## 3. Quy tắc nội dung

- Mỗi file phải có dòng `Cập nhật lần cuối`.
- Ưu tiên tiếng Việt rõ ràng, ngắn gọn, dễ hiểu.
- Nếu tài liệu dài, có mục lục hoặc phân đoạn rõ.
- Không trùng nội dung giữa nhiều file; nếu cần, dùng link tham chiếu.

## 4. Vòng đời tài liệu

1. Tạo plan trước khi làm task lớn.
2. Sau mỗi phase, cập nhật doc liên quan.
3. Sau khi hoàn thành, tạo báo cáo ở `docs/reports/`.
4. Ghi log triển khai tại `logs/tasks/`.
