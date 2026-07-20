# Web Search Pipeline Production (Hardening + HA)

## 1) Mục tiêu hệ thống
Tài liệu này mô tả pipeline web search mới sau khi triển khai đầy đủ các phase hardening trong codebase:
- Cô lập rủi ro outbound search khỏi luồng ứng dụng chính.
- Không phụ thuộc 1 nguồn tìm kiếm duy nhất.
- Tự phục hồi khi provider lỗi/rate-limit/chặn.
- Tối ưu độ chính xác citation, hiệu năng và độ trễ.

Lưu ý kỹ thuật: với dữ liệu open-web, không thể cam kết tuyệt đối 100% không bao giờ bị provider block. Hệ thống hiện tại được thiết kế để đạt mức an toàn vận hành cao nhất trong phạm vi kiểm soát nội bộ (giảm blast radius về gần 0 và không ảnh hưởng hạ tầng core khi provider gặp sự cố).

## 2) Kiến trúc mới

### 2.1 Search Broker (đa provider)
Thay vì gọi thẳng SearxNG ở `domain_mapper`, pipeline gọi qua `SearchBrokerService`:
- File: `backend/service/search_broker_service.py`
- Chức năng:
  - Provider abstraction: `brave`, `bing`, `searxng`
  - Provider priority + failover theo thứ tự cấu hình
  - Circuit breaker theo từng provider
  - Retry có exponential backoff + jitter
  - Global throttling (RPS + concurrency)
  - Query cache trên Redis

### 2.2 Pipeline web search (LangGraph)
Luồng mới vẫn giữ deterministic, nhưng có thêm lớp agentic research loop có giới hạn:
1. `node_web_coordinator`
   - planner phân tích câu hỏi, tách `research_questions`, sinh nhiều `search_queries`.
   - nếu không có domain scope và `WEB_BROAD_SEARCH_ENABLED=true`, search open-web rộng rồi lọc theo source policy.
2. `node_web_domain_mapper`
3. `node_web_url_selector`
4. `node_web_fetch_clean`
5. `node_web_rerank`
6. `node_web_summarize`
   - summarizer lọc nhiễu theo từng câu hỏi con, giữ fact sạch/citation mapping.
7. `node_fetch_history`
8. `node_web_synthesize`
9. `node_web_verify`
   - evaluator chấm evidence/citation/diversity/missing questions.
   - nếu chưa đạt và còn budget, loop về `node_web_coordinator` để search bổ sung.

Điểm thay đổi chính:
- `node_web_domain_mapper` dùng broker, nhận provider trace/cache hit để debug.
- `url_selector` và `rerank` thêm quota đa dạng nguồn theo domain.
- `fetch_clean` có semaphore global + retry/backoff.
- `summarize` lọc nhiễu trước khi answer để giảm dùng nhầm đoạn web lan man.
- `synthesize` có citation validator hậu kiểm + self-repair 1 lần.
- `verify` dùng thêm chỉ số diversity, citation validity, coverage của câu hỏi con để chấm confidence và quyết định retry loop.

## 3) Cơ chế an toàn và chống ảnh hưởng IP nội bộ

### 3.1 Hạn chế phơi lộ SearxNG
- `docker-compose.yml` và `docker-compose.all.yml` đổi bind SearxNG thành localhost mặc định:
  - `SEARXNG_BIND_ADDR=127.0.0.1`
- Mục tiêu: không public service SearxNG trực tiếp ra mạng ngoài.

### 3.2 Limiter và Redis cho SearxNG
- Dùng file cấu hình mới: `config/searxng/settings.local.yml`
- Bật `server.limiter: true`
- Kết nối Redis cho limiter (`SEARXNG_REDIS_URL`)

### 3.3 Egress isolation readiness
- Broker và fetch hỗ trợ `WEB_SEARCH_EGRESS_PROXY_URL` / `WEB_FETCH_EGRESS_PROXY_URL`.
- Khuyến nghị production bắt buộc:
  1. Đặt proxy/egress gateway riêng.
  2. Chặn outbound trực tiếp từ app container qua firewall/network policy.
  3. Chỉ cho phép outbound qua gateway.

## 4) High Availability và fallback

### 4.1 Multi-provider failover
- Cấu hình thứ tự provider qua `WEB_SEARCH_PROVIDER_PRIORITY`.
- Mặc định: `brave,bing,searxng`.
- Nếu provider đang lỗi liên tiếp vượt ngưỡng, circuit breaker mở và bỏ qua provider đó tạm thời.

### 4.2 Cache nhiều tầng tại broker
- Cache query result trong Redis (`WEB_SEARCH_CACHE_TTL_SEC`).
- Giảm call lên upstream, giảm latency và giảm nguy cơ block.

### 4.3 Global protection
- Service layer thêm global rate-limit/phút (`WEB_SEARCH_GLOBAL_RATE_LIMIT_PER_MIN`).
- Vẫn giữ limit theo user (`WEB_SEARCH_RATE_LIMIT_PER_MIN`).

## 5) Tối ưu hiệu năng và độ trễ

### 5.1 Fetch pipeline
- `WEB_FETCH_MAX_CONCURRENCY`: giới hạn song song toàn cục.
- Retry có backoff (`WEB_FETCH_RETRY_MAX`, `WEB_FETCH_RETRY_BASE_MS`).
- Mục tiêu: giảm timeout dây chuyền khi nhiều URL kém ổn định.

### 5.2 Retrieval quality + diversity
- `WEB_MAX_EVIDENCE_PER_DOMAIN`: quota domain để tránh phụ thuộc 1 nguồn.
- Áp dụng ở cả URL selector và evidence rerank.

### 5.3 Search throttle
- Broker có `WEB_SEARCH_GLOBAL_CONCURRENCY` + `WEB_SEARCH_GLOBAL_RPS`.
- Giảm burst đến provider và ổn định P95 latency.

## 6) Tối ưu độ chính xác và chống hallucination

### 6.1 Citation validator
- `WEB_CITATION_VALIDATION_ENABLED=true` bật hậu kiểm:
  - Bắt buộc có `[Sx]` khi có evidence.
  - Không cho phép Sx ngoài phạm vi evidence.
  - Bắt buộc có mục `Nguồn tham khảo`.
- Nếu vi phạm, synthesize tự regenerate 1 lần để sửa citation.

### 6.2 Verify confidence theo nhiều tín hiệu
- `node_web_verify` đánh giá bằng:
  - top evidence score
  - số evidence
  - số domain độc lập
  - citation validity

## 7) Cấu hình mới quan trọng (env)

### 7.1 Broker / Provider
- `WEB_SEARCH_BROKER_ENABLED`
- `WEB_SEARCH_PROVIDER_PRIORITY`
- `BRAVE_SEARCH_API_KEY`, `BRAVE_SEARCH_BASE_URL`
- `BING_SEARCH_API_KEY`, `BING_SEARCH_BASE_URL`

### 7.2 Resilience
- `WEB_SEARCH_RETRY_MAX`, `WEB_SEARCH_RETRY_BASE_MS`
- `WEB_SEARCH_CB_FAIL_THRESHOLD`, `WEB_SEARCH_CB_OPEN_SEC`
- `WEB_SEARCH_CACHE_TTL_SEC`
- `WEB_SEARCH_GLOBAL_CONCURRENCY`, `WEB_SEARCH_GLOBAL_RPS`

### 7.3 Fetch
- `WEB_FETCH_MAX_CONCURRENCY`
- `WEB_FETCH_RETRY_MAX`, `WEB_FETCH_RETRY_BASE_MS`

### 7.4 Security / network
- `SEARXNG_BIND_ADDR`
- `SEARXNG_REDIS_URL`
- `WEB_SEARCH_EGRESS_PROXY_URL`
- `WEB_FETCH_EGRESS_PROXY_URL`

### 7.5 Quality
- `WEB_MAX_EVIDENCE_PER_DOMAIN`
- `WEB_CITATION_VALIDATION_ENABLED`
- `WEB_QUERY_PLANNER_LLM_ENABLED`
- `WEB_QUERY_DECOMPOSITION_MAX_SUBQUERIES`
- `WEB_BROAD_SEARCH_ENABLED`
- `WEB_EVIDENCE_SUMMARIZER_ENABLED`
- `WEB_SUMMARIZER_MIN_SCORE`
- `WEB_SEARCH_EVALUATOR_LOOP_ENABLED`
- `WEB_SEARCH_MAX_RESEARCH_LOOPS`
- `WEB_EVALUATOR_MIN_EVIDENCE`
- `WEB_EVALUATOR_MIN_DOMAINS`
- `WEB_EVALUATOR_MIN_TOP_SCORE`

## 8) Runbook vận hành nhanh

### Sự cố 429 tăng cao
1. Giảm `WEB_SEARCH_GLOBAL_RPS` và `WEB_SEARCH_GLOBAL_CONCURRENCY`.
2. Tạm hạ thứ tự provider rủi ro trong `WEB_SEARCH_PROVIDER_PRIORITY`.
3. Tăng TTL cache để giảm outbound volume.

### Provider chính chết
1. Circuit breaker tự mở sau ngưỡng fail.
2. Traffic tự đổ sang provider kế tiếp trong priority list.
3. Theo dõi `provider_trace` trong `web_search_debug`.

### Citation invalid tăng
1. Bật/giữ `WEB_CITATION_VALIDATION_ENABLED=true`.
2. Kiểm tra prompt synthesizer active trong DB.
3. Tăng diversity nguồn để giảm xung đột thông tin.

## 9) Danh sách thay đổi chính trong code
- `backend/service/search_broker_service.py` (mới)
- `backend/agent_chatbot/graph/rag_graph.py` (thêm summarize node và conditional retry loop)
- `backend/agent_chatbot/node/rag_query_pipeline.py` (wrapper SSE cho summarize node)
- `backend/agent_chatbot/node/util/rag_query_util.py` (planner decomposition + broad search + summarizer + evaluator loop + citation validation)
- `backend/service/rag_service.py` (global web search rate limit)
- `config/searxng/settings.local.yml` (mới, limiter on)
- `docker-compose.yml` (hardening bind + new searx config mount)
- `docker-compose.all.yml` (hardening bind + new searx config mount)
- `.env`, `.env.all` (thêm env vars production hardening)

## 10) Kết luận
Pipeline hiện tại đã được nâng cấp theo hướng production hardening đa tầng:
- an toàn outbound tốt hơn,
- chống phụ thuộc provider,
- có khả năng tự phục hồi,
- tối ưu chất lượng citation,
- kiểm soát tốt hiệu năng và độ trễ.

Để đạt mức an toàn vận hành cao nhất trong production thật, cần triển khai thêm network policy/firewall ở hạ tầng để cưỡng bức 100% outbound search đi qua egress gateway/proxy chuyên dụng.
