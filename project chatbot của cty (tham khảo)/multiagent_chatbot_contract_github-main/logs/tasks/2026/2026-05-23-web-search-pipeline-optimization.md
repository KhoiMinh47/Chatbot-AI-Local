# Log task: web-search-pipeline-optimization

- Bắt đầu: 2026-05-23 22:39
- Plan: `plans/plan-web-search-pipeline-optimization.md`
- Doc: `docs/reports/web-search-pipeline-optimization.md`
- Trạng thái: completed

## Mục tiêu
Rà soát và tối ưu luồng web search theo hướng pipeline/prompt/tool tổng quát, sau đó kiểm thử thực tế bằng 10 câu hỏi và lưu evidence trong `tests/test-websearch`.

## Ghi nhận ban đầu
- Đã đọc `rag_graph`, `rag_query_pipeline`, `rag_query_util`, `search_broker_service`, `rag_service`, prompt seed trong `backend/main.py`.
- Worktree đã có nhiều thay đổi trước phiên này trong `.codex`, `.github` và một số file frontend. Không đụng/chỉnh các thay đổi đó nếu không liên quan.

## Phase Log
- 2026-05-23 22:39: Bắt đầu phase 1 đọc source và xác định điểm yếu.
- 2026-05-23 22:58: Hoàn tất phase 1. Điểm yếu chính:
  - Allowlist domain trong DB đang bị coordinator biến thành `target_domains` bắt buộc dù `strict_source_filter=false`, làm open-web bị bóp còn vài domain.
  - `web_search_debug`, `web_fetch_debug`, `web_summary_debug`, `web_verify_debug` chưa khai báo trong `RagWebSearchState`, nên LangGraph có thể bỏ metadata giữa node.
  - Search broker thử `brave`/`bing` dù chưa có key, gây log nhiễu và tốn lượt retry trước khi tới SearxNG.
  - Verifier yêu cầu tối thiểu 2 domain ngay cả khi query explicit domain hoặc strict source scope, khiến agent review dễ đánh fail các câu hỏi một nguồn chính thức.
- 2026-05-23 22:58: Bắt đầu phase 2 thiết kế và implement sửa pipeline tổng quát.
- 2026-05-23 23:04: Đọc README xác nhận backend chuẩn chạy trong `rag-chat-code:backend`. Port 9000 do pane này phục vụ.
- 2026-05-23 23:04: Bổ sung `security-skill` trước khi chỉnh `.env`; không ghi secret vào log/report.
- 2026-05-23 23:18: Sửa `.env` để `SEARXNG_BASE_URL` trỏ localhost đang chạy. Implement:
  - `RagWebSearchState` giữ debug fields qua LangGraph.
  - Search broker skip provider chưa cấu hình thay vì coi là lỗi.
  - Coordinator phân biệt `preferred_domains` và `target_domains` bắt buộc.
  - Mapper search preferred domains song song với open-web khi strict tắt.
  - Selector/rerank boost host/domain match và official source.
  - Verifier cho phép single official source mạnh với câu hỏi định danh.
  - Seed prompt web search được nâng cấp; DB active prompt web đã cập nhật 2 prompt và xóa cache.
- 2026-05-23 23:16: Chạy test chính thức `tests/test-websearch/run_websearch_eval.py`: `PASS 10/10`.
- 2026-05-23 23:16: Tối ưu thêm chọn `preferred_domains` theo domain root khớp query và rerun: `PASS 10/10`, evidence `tests/test-websearch/evidence/20260523-231857/`.
- 2026-05-23 23:16: Xác nhận cleanup domain tạm: còn `0` rule test.
- 2026-05-23 23:16: Reload backend đúng tmux `rag-chat-code:backend`; `/docs` port 9000 trả HTML, pane PID `1524860`.
- 2026-05-23 23:46: User phát hiện khóa domain bị nới quá rộng. Sửa lại source policy: allowlist active là khóa nguồn bắt buộc dù `strict_source_filter=false`.
- 2026-05-23 23:46: Rerun `tests/test-websearch/run_websearch_eval.py`: `PASS 10/10`, cleanup `0` rule tạm, kiểm domain evidence `outside_count=0`, evidence `tests/test-websearch/evidence/20260523-234623/`.

## Verification
- `backend/venv/bin/python -m py_compile backend/main.py backend/agent_chatbot/agent_state/agent_state.py backend/service/search_broker_service.py backend/agent_chatbot/node/util/rag_query_util.py tests/test-websearch/run_websearch_eval.py`: đạt.
- `backend/venv/bin/python tests/test-websearch/run_websearch_eval.py`: `PASS 10/10`.
- Evidence: `tests/test-websearch/latest-evidence.png`.

## Rủi ro
- Test thực tế phụ thuộc SearxNG/vLLM local và trạng thái nguồn web tại thời điểm chạy.
- Một số câu pass với confidence `low`, nên UI/API nên truyền confidence nếu cần phân biệt mức chắc chắn.
