# Web Search Test Suite

Folder này chứa harness kiểm thử luồng `web_search` thật của backend.

## Mục tiêu

- Chạy 10 câu hỏi thực tế qua LangGraph web search pipeline.
- Ghi lại câu hỏi, câu trả lời, evidence URL, debug search/fetch/verify.
- Test khóa domain bằng cách thêm domain allow tạm thời, xác nhận evidence chỉ đến từ domain đã allow, sau đó tự dọn đúng các rule đã tạo.
- Sinh ảnh evidence dạng PNG để chứng minh test đã chạy.

## Cách chạy

```bash
backend/venv/bin/python tests/test-websearch/run_websearch_eval.py
```

Artifact mới nhất:

- `tests/test-websearch/latest-report.md`
- `tests/test-websearch/latest-results.json`
- `tests/test-websearch/latest-evidence.png`

Mỗi lần chạy cũng tạo bản lưu theo timestamp trong `tests/test-websearch/evidence/`.

## Lưu ý

- Script dùng `.env` root và gọi workflow thật, nên cần SearxNG, vLLM, Redis, PostgreSQL, embedding/rerank service đang chạy.
- Script không ghi secret vào report.
- Khi trong DB có allowlist nguồn web, pipeline phải coi allowlist là khóa nguồn bắt buộc. Nếu report có domain ngoài danh sách admin/tạm thêm, test không đạt mục tiêu dù câu trả lời có nội dung.
- Nếu script bị ngắt giữa chừng, kiểm tra bảng `web_source_rule` và xóa các rule có note `temporary web_search evaluation domain`.
