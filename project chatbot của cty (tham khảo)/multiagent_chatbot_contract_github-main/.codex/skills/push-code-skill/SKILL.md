---
name: push-code-skill
description: 'Những quy tắt bắt buộc khi push dự án.'
argument-hint: 'tuân thủ các quy tắc đã đề ra.'
user-invocable: true
---

# Những quy tắt bắt buộc khi push dự án:

## CI/CD
- Mỗi task phải quét lại hết Ci/CD xem có gì cần cập nhật hay thêm không.
- Phải đảm bảo có nhiều bài test nghiêm ngặt, chi tiết cho từng phần của dự án.
- Phải đầy đủ chuẩn một production, tets nghiêm ngặt và có các bài tets gắt gao nhất.

## Quy tắt push
- Ghi commit rõ ràng có thời gian.
- Có decription rõ ràng chi tiết.

## Setup
- Setup gitignore, .env, .env.example nếu chưa có.
- Tạo CI/CD khời đầu nếu chưa có.

## Quy tắt viết readme.
- Dùng skill readme-style để viết readme
- Nếu chưa có ảnh banner thì ưu tiên chụp ảnh frontend không thì tự tạo.

## Quản lý version dự án rõ ràng.
- Quản lý version rõ ràng chuyên nghiệp..