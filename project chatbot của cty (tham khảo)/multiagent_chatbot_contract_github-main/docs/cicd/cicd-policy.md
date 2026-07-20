# Chính sách CI/CD nghiêm ngặt

Cập nhật lần cuối: 2026-05-13

## 1. Mục tiêu

- Chặn lỗi chất lượng trước khi merge.
- Tăng mức bảo mật chuỗi cung ứng phần mềm.
- Đảm bảo artifact release có thể truy vết và kiểm chứng.

## 2. CI bắt buộc trên pull request và push

1. Workflow lint bằng `actionlint`.
2. Markdown lint cho tài liệu.
3. Secret scan với `gitleaks`.
4. Backend quality:
   - `python -m compileall`.
   - `pip check`.
   - `bandit` mức high severity/high confidence.
   - `pip-audit`.
5. Frontend quality:
   - `npm ci`.
   - `npm run lint`.
   - `npm run build`.
   - `npm audit --omit=dev --audit-level=high`.
6. Validate `docker compose config` cho các file compose chính.

## 3. CD và release

- Release backend theo tag `backend-v*`.
- Release frontend theo tag `frontend-v*`.
- Chỉ build/push artifact sau khi các job kiểm tra trong workflow release pass.
- Artifact release phải gắn tag rõ ràng theo version và SHA.

## 4. Quy định branch protection (khuyến nghị áp dụng trên GitHub)

1. Bật required checks cho toàn bộ job CI.
2. Chặn merge khi chưa pass CI.
3. Bật `dismiss stale approvals` khi có commit mới.
4. Bật secret scanning và Dependabot alerts ở repo settings.

## 5. Tối ưu hiệu năng pipeline

- Dùng cache dependency (pip, npm).
- Dùng concurrency để cancel run cũ trên cùng branch.
- Tách job theo nhóm để chạy song song.
