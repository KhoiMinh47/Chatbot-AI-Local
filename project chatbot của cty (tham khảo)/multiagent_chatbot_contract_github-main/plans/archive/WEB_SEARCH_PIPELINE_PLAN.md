# WEB SEARCH PIPELINE PLAN (Production-Ready, Code-Aligned)

## 1) Mục tiêu
- Vận hành web_search theo open-web 100%, ổn định production, đo lường được hiệu quả thực tế.
- Giữ session/history dùng chung với fast flow, không tách hệ lưu trữ.
- Tối ưu chất lượng retrieval và chất lượng citation, giảm hallucination.
- Thiết kế roadmap đủ rõ để có thể code lại lâu dài theo từng phase, có rollback.

## 2) Phạm vi và ràng buộc
- Không thêm model embedding/rerank mới trong phase hiện tại.
- Dùng lại endpoint embedding/rerank hiện có.
- Không khôi phục cơ chế default domain allowlist cũ.
- Pipeline deterministic theo LangGraph, có SSE stage rõ ràng.

## 3) Pipeline hiện tại (AS-IS, khớp code)
Luồng workflow web_search đang chạy:
1. node_web_coordinator
- Nhận user_input, chuẩn hóa web_urls user gửi vào.
- Rewrite query thành keyword query bằng _rewrite_query_keywords.
- Decompose truy vấn thành 1-3 sub-query deterministic (intent/entity/time) để search đa nhánh.
- Load và merge source policy từ env + DB rule (allow/block domain/url_prefix) vào search_plan.
- Ghi rewritten_query, sub_queries và source_policy vào search_plan.

2. node_web_domain_mapper
- Gọi SearxNG theo từng sub-query (format=json, engines theo env).
- Hợp nhất candidate với URL user gửi.
- Nếu thiếu candidate và có domain seed: fallback cache/index/discover.
- Lọc nguồn theo source policy (allow/block) trước khi đưa vào selector.
- Ghi web_search_debug gồm sub_queries, search_issue và policy counters.

3. node_web_url_selector
- Heuristic score theo URL path + noise penalty.
- Prefetch title và title-aware rerank bằng endpoint rerank hiện có.
- Chọn top N selected_urls và ghi lại selected_url_titles.

4. node_web_fetch_clean
- Fetch song song selected_urls với timeout.
- Trích nội dung theo chain: trafilatura -> readability-lxml -> strip fallback.
- Loại nội dung quá ngắn hoặc trang challenge/noise.

5. node_web_rerank
- Rerank snippet content bằng endpoint rerank hiện có.
- Sinh reranked_evidence (url, title, score, snippet).
- Nếu top rerank thấp hoặc docs rỗng: adaptive fallback tự nới budget fetch từ candidate_urls, fetch bổ sung rồi rerank lại.

6. node_fetch_history
- Lấy lịch sử hội thoại gần đây (chung cơ chế với flow khác).

7. node_web_synthesize
- Dùng prompt synthesizer active trong DB.
- Đầu vào context có nhãn nguồn [S1], [S2], ...
- Yêu cầu output có source tag theo từng đoạn và mục Nguồn tham khảo.

8. node_web_verify
- Tính confidence nội bộ high/medium/low theo evidence score.
- Không append confidence vào text trả user (chỉ lưu state/audit).

## 4) Gap production cần xử lý thêm (TO-BE)
1. Citation reliability chưa có validator hậu kiểm.
- Hiện prompt yêu cầu [Sx], nhưng chưa có bước xác thực Sx tồn tại thật.

2. Query rewrite mới dừng ở heuristic tokenization.
- Đã có decomposition bản đầu deterministic; chưa có decomposition bằng planner LLM.

3. Chưa có source diversity constraint.
- Có thể top evidence tập trung 1 domain.

4. Chưa có adaptive budget.
- Đã có adaptive fallback ở rerank node; chưa có vòng lặp nhiều cấp theo KPI dài hạn.

5. Quan sát chất lượng còn mỏng.
- Có debug nội bộ, nhưng chưa chuẩn KPI retrieval/citation để theo dõi theo ngày.

## 5) Thiết kế production đề xuất
### 5.1 Retrieval quality
1. Query decomposition (P1)
- Tách user query thành 1-3 sub-query ngắn (intent/time/entity).
- Chạy SearxNG theo sub-query, merge + dedup theo canonical URL.

2. Adaptive candidate/fetch budget (P1)
- Nếu tỉ lệ fetch_fail cao hoặc rerank top score thấp, tự tăng URL budget trong ngưỡng an toàn.

3. Source diversity re-balance (P1)
- Khi chọn final evidence, ưu tiên ít nhất 2 domain độc lập nếu có.

4. Freshness boost theo intent thời gian (P2)
- Nếu query chứa hôm nay/mới nhất/ngày cụ thể, boost URL có dấu hiệu mới.

### 5.2 Citation quality
1. Citation validator sau synthesize (P0)
- Parse toàn bộ [Sx] trong output.
- Reject/regenerate nếu có Sx ngoài phạm vi evidence.

2. Evidence-grounding check (P1)
- Rule đơn giản: đoạn nào không có [Sx] thì auto bổ sung hoặc regenerate.

### 5.3 Reliability and ops
1. Circuit breaker cho SearxNG (P1)
- Khi lỗi liên tiếp vượt ngưỡng, giảm tải tạm thời và trả thông báo rõ nguyên nhân.

2. Retry policy có jitter (P2)
- Retry ngắn cho lỗi mạng transient ở search/fetch.

3. Log and storage control (P0)
- Đã có Docker log rotation toàn stack.
- Duy trì policy này ở local và compose-all.

## 6) Chỉ số vận hành bắt buộc (SLO/KPI)
### 6.1 SLO hệ thống
- P95 latency web_search end-to-end <= 12s (mục tiêu nội bộ).
- Tỉ lệ request lỗi hệ thống <= 2%.

### 6.2 KPI chất lượng retrieval
- Candidate non-empty rate.
- Fetch success rate.
- Evidence_count trung bình.
- Domain diversity trên mỗi câu trả lời.

### 6.3 KPI citation
- Citation valid rate ([Sx] hợp lệ).
- Citation coverage rate (tỉ lệ đoạn có ít nhất 1 [Sx]).

## 7) Cấu hình production baseline
### 7.1 Bắt buộc
- SEARXNG_BASE_URL
- SEARXNG_ENGINES
- WEB_SEARXNG_TOPK
- WEB_MAX_URLS_PER_QUERY
- WEB_SEARCH_TIMEOUT_SEC
- WEB_FETCH_TIMEOUT_SEC

### 7.2 Khuyến nghị thêm
- WEB_MAX_CANDIDATE_URLS
- WEB_URL_SELECTOR_PREFETCH_MULTIPLIER
- WEB_MIN_CONTENT_CHARS_PER_URL
- WEB_MAX_TOTAL_WEB_CONTEXT
- WEB_SEARCH_RATE_LIMIT_PER_MIN
- WEB_QUERY_DECOMPOSITION_ENABLED
- WEB_QUERY_DECOMPOSITION_MAX_SUBQUERIES
- WEB_ADAPTIVE_BUDGET_ENABLED
- WEB_ADAPTIVE_LOW_RERANK_THRESHOLD
- WEB_ADAPTIVE_EXTRA_FETCH_URLS
- WEB_SEARCH_STRICT_SOURCE_FILTER
- WEB_SEARCH_ALLOWED_DOMAINS
- WEB_SEARCH_BLOCKED_DOMAINS
- WEB_SEARCH_ALLOWED_URL_PREFIXES
- WEB_SEARCH_BLOCKED_URL_PREFIXES

## 8) Kế hoạch triển khai dài hạn (phased)
### Phase A (P0) - Ổn định production
1. Giữ pipeline hiện tại, chốt cấu hình env chuẩn từng môi trường.
2. Bổ sung citation validator hậu kiểm trong node_web_synthesize/node_web_verify.
3. Dashboard KPI tối thiểu cho retrieval + citation.

### Phase B (P1) - Tăng hiệu quả thực tế
1. Query decomposition cho truy vấn phức hợp.
2. Adaptive budget + source diversity re-balance.
3. Tối ưu selector theo dữ liệu thực tế (ablation title-rerank vs heuristic).

### Phase C (P2) - Tối ưu chi phí và mở rộng
1. Retry + circuit breaker hoàn chỉnh.
2. Freshness boost theo intent thời gian.
3. Bộ regression test cho web_search theo tập câu hỏi chuẩn.

## 9) Tiêu chí nghiệm thu production
1. Pipeline chạy ổn định với SearxNG và không còn lỗi cấu hình runtime.
2. Câu trả lời có citation theo đoạn và mapping Nguồn tham khảo hợp lệ.
3. Có số liệu KPI tối thiểu để theo dõi chất lượng theo ngày.
4. Có cơ chế rollback cấu hình (feature flag) cho các tối ưu mới.

## 10) Rollback và an toàn triển khai
1. Mọi tối ưu mới đi sau feature flag env.
2. Nếu KPI xấu đi, fallback về pipeline baseline trong cùng release.
3. Giữ backward-compatible API contract cho frontend hiện tại.

## 11) Trạng thái hiện tại và bước kế tiếp
### Đã có
- Open-web flow tách core workflow, dùng chung session/history.
- Query rewrite keyword + decomposition 1-3 sub-query ở coordinator.
- Selector title-rerank + fetch clean chain + evidence rerank.
- Adaptive fallback nới budget khi top rerank thấp.
- Source policy merge env + DB rule và đã lọc trong retrieval path.
- Admin root có CRUD quản lý nguồn web (domain/url_prefix, allow/block).
- Prompt yêu cầu citation theo [Sx].

### Làm ngay tiếp theo
1. Implement citation validator hậu kiểm (P0).
2. Thêm đo lường KPI retrieval/citation (P0).
3. Nâng cấp decomposition từ heuristic sang planner prompt có kiểm thử (P1).

### Cập nhật triển khai mới
- Web search đã chuyển sang flow planner -> broad/domain search -> rerank -> summarizer lọc nhiễu -> synthesizer -> verifier.
- Verifier có thể loop về coordinator trong giới hạn `WEB_SEARCH_MAX_RESEARCH_LOOPS` khi thiếu evidence, thiếu domain diversity, score thấp, citation lỗi hoặc còn câu hỏi con chưa được cover.
- Khi không có domain scope và `WEB_BROAD_SEARCH_ENABLED=true`, mapper search open-web rộng thay vì trả `no_domain_scope`.
