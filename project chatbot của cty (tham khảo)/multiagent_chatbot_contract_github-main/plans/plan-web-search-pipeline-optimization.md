# Plan: web-search-pipeline-optimization

- Created: 2026-05-23 22:39
- Updated: 2026-05-23 23:46
- Status: closed
- Related log: logs/tasks/2026/2026-05-23-web-search-pipeline-optimization.md
- Related doc: docs/reports/web-search-pipeline-optimization.md

## Goal
Rà soát toàn bộ luồng web search, xác định điểm kém thực tế trong pipeline agent/planner/tool/evidence, tối ưu prompt và pipeline theo hướng tổng quát, sau đó kiểm thử bằng 10 câu hỏi thực tế có báo cáo, evidence ảnh và README trong `tests/test-websearch`.

## Scope
- In: backend web search pipeline, prompt mặc định/seed, search broker/domain policy behavior, test harness và tài liệu kiểm thử.
- Out: không refactor unrelated frontend/UI, không thay đổi secret/env thật, không push code.

## Skills
- `plan-skill`: quản lý phase, plan/log/doc.
- `backend-skill`: chỉnh pipeline service/node/agent boundary.
- `testing-skill`: thiết kế regression + test report + evidence ảnh.
- `documentation-skill`: cập nhật doc task và README test.
- `logging-skill`: ghi log phiên làm việc.
- `security-skill`: kiểm soát khi chỉnh `.env`/provider URL, không ghi secret vào report/log.

## Phases
| Phase | Goal | Status | Evidence |
| --- | --- | --- | --- |
| 1 | Đọc source, docs, cấu hình và xác định điểm yếu luồng web search | done | Xác định allowlist bị dùng như hard scope, debug state bị rơi, broker thử provider chưa cấu hình, verifier quá cứng |
| 2 | Thiết kế sửa pipeline/prompt/tool theo hướng tối ưu tổng quát | done | Tách preferred/restricted domains, giữ debug, tối ưu provider skip, evaluator thích nghi theo scope/official source |
| 3 | Implement thay đổi backend + test harness/report | done | Đã sửa state schema, broker, coordinator/mapper/verifier/scoring/prompt seed và tạo `tests/test-websearch` |
| 4 | Chạy unit/integration/manual test 10 câu hỏi, thêm domain test rồi cleanup | done | `PASS 10/10`, cleanup còn 0 rule test, domain evidence ngoài allowlist = 0 |
| 5 | Tạo ảnh evidence, cập nhật docs/log, đóng plan | done | `tests/test-websearch/latest-evidence.png`, doc/log đã cập nhật lại sau khi khôi phục khóa domain |

## Verification
- `python3 -m py_compile` cho các file backend/script mới hoặc đã sửa.
- Test tự động cho các helper/pipeline search nếu khả thi.
- Chạy 10 câu hỏi web search thực tế qua harness, ghi câu hỏi, answer, nguồn, debug và trạng thái pass/fail.
- Có ảnh evidence thể hiện test đã chạy tốt và có README cho `tests/test-websearch`.
- Kiểm tra domain rule test đã được dọn sau khi chạy.
- Reload backend đúng tmux `rag-chat-code:backend`.

## Close Criteria
- Đạt: pipeline không còn trả fallback cứng khi vẫn có khả năng tìm/đọc nguồn phù hợp.
- Đạt: tối ưu nằm ở planner/query/tool/evidence gate, không hard-code theo một câu hỏi.
- Đạt: khi có allowlist active, pipeline không lấy nguồn ngoài danh sách allow.
- Đạt: báo cáo test có 10 câu hỏi-câu trả lời, nguồn và kết luận.
- Đạt: plan chuyển sang `plans/plan-web-search-pipeline-optimization.md`, log/doc cập nhật trạng thái hoàn tất.
