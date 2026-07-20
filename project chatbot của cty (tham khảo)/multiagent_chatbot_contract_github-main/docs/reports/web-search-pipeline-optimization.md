# Báo cáo task: web-search-pipeline-optimization

- Thời gian bắt đầu: 2026-05-23 22:39
- Plan: `plans/plan-web-search-pipeline-optimization.md`
- Log: `logs/tasks/2026/2026-05-23-web-search-pipeline-optimization.md`
- Trạng thái: hoàn tất

## Mục tiêu
Tối ưu luồng web search theo hướng cải thiện planner, agent pipeline, evidence selection và tool usage. Không sửa cứng cho một lỗi đơn lẻ, không thêm fallback để che lỗi.

## Phạm vi đọc source
- Backend graph và node wrapper web search.
- Utility pipeline web search: query rewrite, planner, domain mapper, URL selector, fetch clean, rerank, summarizer, synthesizer, verifier.
- Search broker đa provider và policy nguồn web.
- Prompt seed/runtime config.
- API service SSE web search.

## Ghi nhận sơ bộ
- Web search hiện có planner LLM, broker đa provider, domain policy, summarizer, synthesizer và verifier loop.
- Rủi ro chính cần kiểm chứng: domain scope có thể bị bóp quá sớm bởi allowlist, mapper chỉ thử một chiến lược search trong vài trường hợp, selected URL budget thấp, verifier yêu cầu evidence/domain diversity cứng có thể làm câu trả lời bị giữ lại hoặc loop không hiệu quả.

## Chẩn đoán chi tiết
- Source policy có 3 domain allow active, nhưng `strict_source_filter=false`. Luồng hiện tại vẫn đưa toàn bộ allowlist vào `target_domains`, nên các câu hỏi open-web bị giới hạn ngoài ý muốn.
- Debug state chưa được khai báo trong TypedDict nên dữ liệu mapper/fetch/summary/verify không ổn định khi qua LangGraph.
- Broker coi provider chưa cấu hình như lỗi runtime. Đây không phải lỗi upstream, chỉ là provider không khả dụng và nên skip có trace rõ.
- Reviewer/evaluator đang dùng ngưỡng evidence/domain giống nhau cho mọi query, kể cả câu hỏi chỉ định domain hoặc cần nguồn chính thức duy nhất.

## Kết quả
Hoàn tất tối ưu pipeline và test thực tế.

## Thay đổi chính
- Khôi phục khóa nguồn: khi có allowlist active, pipeline chỉ search/fetch nguồn thuộc allow domain/url_prefix; open-web chỉ dùng khi không có allowlist.
- Giữ các trường debug web search trong `RagWebSearchState` để report không bị mất metadata qua LangGraph.
- Search broker bỏ qua provider chưa cấu hình thay vì ghi lỗi lặp.
- URL selector/rerank cộng điểm nguồn chính thức khi entity trong query khớp domain.
- Verifier thích nghi: chấp nhận một nguồn chính thức mạnh cho câu hỏi định danh tổ chức/sản phẩm.
- Thêm explicit domain probe cho trường hợp user đưa domain trực tiếp nhưng provider không trả kết quả `site:domain`.
- Cập nhật prompt coordinator/synthesizer mặc định và DB active prompt tương ứng.
- Sửa `SEARXNG_BASE_URL` trong `.env` về SearxNG local đang chạy.

## Verification
- `backend/venv/bin/python -m py_compile` đạt cho các file backend/script đã sửa.
- Chạy `tests/test-websearch/run_websearch_eval.py`: `PASS 10/10`.
- Kiểm tra domain evidence: `outside_count=0`, toàn bộ source nằm trong domain admin có sẵn hoặc domain tạm do script add.
- Domain tạm trong test đã cleanup, còn lại `0` rule có note `temporary web_search evaluation domain`.
- Backend đã reload trong tmux `rag-chat-code:backend`, endpoint `http://127.0.0.1:9000/docs` trả HTML.

## Evidence
- Report mới nhất: `tests/test-websearch/latest-report.md`
- JSON mới nhất: `tests/test-websearch/latest-results.json`
- Ảnh chứng minh: `tests/test-websearch/latest-evidence.png`
- Bản lưu timestamp: `tests/test-websearch/evidence/20260523-234623/`

## Rủi ro còn lại
- Kết quả open-web vẫn phụ thuộc provider và trạng thái nội dung web tại thời điểm chạy.
- Một số câu có confidence `low` nhưng vẫn pass do có evidence/citation hợp lệ; nên dùng confidence để hiển thị mức chắc chắn cho người dùng nếu frontend cần.
