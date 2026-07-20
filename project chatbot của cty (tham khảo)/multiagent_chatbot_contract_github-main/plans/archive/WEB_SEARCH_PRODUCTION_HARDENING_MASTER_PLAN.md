# WEB SEARCH PRODUCTION HARDENING MASTER PLAN (ZERO-TRUST + HIGH-AVAILABILITY)

## 1) Mục tiêu theo yêu cầu
- Bảo vệ tuyệt đối hạ tầng nội bộ: không để IP server thật trực tiếp truy vấn search engine công cộng.
- Dịch vụ không phụ thuộc một nguồn duy nhất: luôn có phương án fallback khi provider lỗi/chặn/rate-limit.
- Chuẩn production: ưu tiên latency thấp, throughput cao, độ chính xác cao, security và observability đầy đủ.
- Nâng pipeline web search hiện tại lên kiến trúc đa tầng có kiểm soát rủi ro, rollback nhanh.

## 2) Làm rõ ràng buộc “an toàn 100%”
- Thực tế kỹ thuật và pháp lý: không có giải pháp open-web scraping nào đảm bảo 100% không bao giờ bị block hoặc ảnh hưởng.
- Mục tiêu khả thi trong production: giảm rủi ro về gần 0 cho IP thật/nội bộ bằng tách lớp egress, cô lập mạng, kill-switch, và provider đa nguồn.
- Kế hoạch này thiết kế theo chuẩn “blast-radius gần như bằng 0” cho hệ thống nội bộ khi upstream có sự cố/chặn.

## 3) Đánh giá AS-IS (khớp code hiện tại)
- Web search workflow hiện có: coordinator -> domain_mapper -> url_selector -> fetch_clean -> rerank -> synthesize -> verify.
- Retrieval hiện dựa chính vào SearxNG (engine cấu hình có google,bing,duckduckgo).
- Đã có rate limit theo user ở service layer, nhưng chưa có global upstream governor/circuit breaker đa provider.
- SearxNG limiter đang tắt (rủi ro burst request lên upstream).
- Chưa có lớp egress isolation bắt buộc để che chắn IP server thật theo mô hình zero-trust outbound.

## 4) Quan điểm về “random IP để giảm ban”
- Có thể giảm xác suất block, nhưng không đủ để đảm bảo ổn định hoặc compliance nếu vẫn scrape engine nhạy cảm.
- Không dùng random IP trực tiếp từ host/project network.
- Chỉ dùng qua lớp egress riêng (proxy gateway/NAT pool chuyên dụng), tách hoàn toàn với IP production chính.
- Ưu tiên nguồn dữ liệu chính từ official search APIs; random/rotating egress chỉ là lớp phụ trợ có kiểm soát chính sách.

## 5) Kiến trúc TO-BE (production target)
### 5.1 Search Broker đa nhà cung cấp (Provider Abstraction)
- Tạo `Search Broker` trong backend làm điểm vào duy nhất cho mọi truy vấn web search.
- Providers chuẩn hóa interface:
  1. `Official APIs` (Brave/Bing/SerpAPI/Google CSE hoặc tương đương) - tier ưu tiên cao nhất.
  2. `SearxNG Cluster` - tier bổ sung.
  3. `Internal cache/index` - tier fallback nhanh.
- Chính sách chọn provider:
  - Weighted routing theo health score + cost + latency.
  - Failover tự động khi timeout/429/5xx vượt ngưỡng.
  - Circuit breaker theo từng provider + half-open probes.

### 5.2 Zero-Trust Outbound Egress
- Toàn bộ outbound search traffic đi qua `Egress Gateway` tách biệt (VPC/subnet/container network riêng).
- Cấm backend app gọi internet trực tiếp bằng network policy/firewall.
- Gateway có khả năng:
  - NAT pool hoặc proxy pool chuyên dụng (IP không liên quan IP server thật).
  - Rotation policy có giới hạn, không “random vô tội vạ”.
  - Per-provider route policy, denylist/allowlist domain, TLS enforcement.
- Có `kill-switch` để ngắt 1 provider hoặc toàn bộ open-web path mà không ảnh hưởng core service.

### 5.3 HA và không phụ thuộc 1 thứ
- Tối thiểu 2 provider “official API” + 1 provider “open-web backup”.
- Cache nhiều tầng:
  1. Query-result cache (Redis) TTL ngắn 5-30 phút.
  2. URL-content cache TTL trung bình 1-24 giờ.
  3. Evidence cache theo normalized query/domain.
- Graceful degradation:
  - Nếu open-web lỗi: trả từ cache + cảnh báo freshness.
  - Nếu provider A lỗi: tự chuyển provider B/C.
  - Nếu tất cả lỗi: vẫn trả “safe fallback response” thay vì timeout toàn request.

### 5.4 Security hardening
- Secrets trong secret manager, không hardcode.
- Egress ACL chỉ cho domain/API đã duyệt.
- SSRF defense đã có tiếp tục giữ, bổ sung outbound DNS policy + response size guard.
- Content sanitization chống prompt injection web:
  - Strip script/hidden instructions.
  - Policy “evidence-only” bắt buộc cho synthesize.
- Audit log đầy đủ: provider, latency, retries, breaker state, reason fallback.

## 6) Nâng cấp pipeline search cho tốc độ và độ chính xác
### 6.1 Coordinator
- Giữ rewrite/decompose nhưng thêm “query intent classes”:
  - factual_realtime, evergreen, entity_lookup, comparative.
- Intent quyết định budget và freshness policy để giảm gọi web không cần thiết.

### 6.2 Domain Mapper
- Chuyển từ gọi trực tiếp SearxNG sang gọi Search Broker.
- Broker trả unified candidates có metadata:
  - provider, retrieval_time, rank_origin, freshness_signals.
- Áp dụng domain diversity quota ngay ở bước candidate selection.

### 6.3 URL Selector + Fetch
- Dynamic budget theo SLA latency:
  - realtime intent: chọn ít URL hơn nhưng freshness cao.
  - evergreen intent: ưu tiên độ tin cậy domain.
- Fetch concurrency điều tiết bởi token bucket global, tránh spike gây ban/provider throttling.
- Retry policy chuẩn: exponential backoff + jitter, có max retry nhỏ.

### 6.4 Rerank + Synthesis
- Rerank có diversity penalty để tránh dồn 1 domain.
- Citation validator bắt buộc: mọi [Sx] phải map được evidence thật.
- Nếu citation invalid: regenerate một lần, sau đó fallback template an toàn.

### 6.5 Verify
- Confidence scoring kết hợp:
  - rerank score,
  - số domain độc lập,
  - freshness,
  - provider reliability window gần nhất.

## 7) SLO/KPI production bắt buộc
- Availability web_search >= 99.9% (tháng).
- P95 latency end-to-end <= 8s, P99 <= 12s.
- Search provider failover success rate >= 99%.
- Citation valid rate >= 99.5%.
- Domain diversity >= 2 domain cho query cần tổng hợp đa nguồn.
- Error budget có dashboard và alert theo 5m/1h/24h.

## 8) Kế hoạch triển khai theo phase
### Phase 0 - Guardrail ngay (1-2 ngày)
- Bật limiter ở SearxNG và giảm burst budget.
- Tắt engine rủi ro cao nếu chưa có egress isolation đầy đủ.
- Thêm global rate limit + circuit breaker tối thiểu ở backend.
- Đóng public exposure cho SearxNG, chỉ cho nội bộ gọi.

Deliverables:
- Env baseline production mới.
- Runbook xử lý 429/block.
- Dashboard health tối thiểu.

### Phase 1 - Broker + Multi-provider (3-5 ngày)
- Tạo Search Broker abstraction + adapter cho 2 official APIs + SearxNG.
- Implement health scoring, weighted routing, failover.
- Caching tầng query-result + observability chuẩn.

Deliverables:
- Module `search_broker` + provider adapters.
- Feature flags chuyển tuyến provider.
- Contract tests cho fallback matrix.

### Phase 2 - Egress Isolation chuẩn zero-trust (3-7 ngày)
- Tách outbound qua gateway/proxy tier riêng.
- Áp firewall rule cấm outbound trực tiếp từ app containers.
- Thêm NAT/proxy pool chính sách rotation có kiểm soát.

Deliverables:
- Network diagram + IaC/policy tài liệu hóa.
- Kill-switch vận hành.
- Kiểm thử chứng minh IP app không lộ ra internet search.

### Phase 3 - Pipeline quality/performance tuning (3-5 ngày)
- Intent-aware budget + adaptive concurrency.
- Diversity-aware rerank + citation validator cứng.
- Tối ưu cache hit, giảm token/context lãng phí.

Deliverables:
- A/B report latency/quality.
- KPI dashboard hoàn chỉnh.
- Regression suite web_search end-to-end.

## 9) Risk register và kiểm soát
- Rủi ro pháp lý ToS scraping:
  - Giảm bằng cách ưu tiên official APIs, open-web chỉ backup.
- Rủi ro provider outage:
  - Multi-provider + circuit breaker + cache fallback.
- Rủi ro rò IP nội bộ:
  - Zero direct egress + gateway isolation + periodic verification.
- Rủi ro latency tăng do nhiều lớp:
  - Budget theo intent, cache warming, async concurrency control.

## 10) Runbook sự cố (tóm tắt)
1. Tăng 429/captcha ở provider X:
- Mở breaker provider X ngay.
- Chuyển traffic sang provider Y/Z.
- Hạ query budget tạm thời.

2. Egress gateway lỗi:
- Chuyển sang gateway dự phòng.
- Nếu chưa hồi phục: dùng cache-only mode cho web_search.

3. Citation validity tụt:
- Bật strict verifier mode.
- Tạm hạ mức trả lời chỉ khi evidence đạt ngưỡng.

## 11) Thay đổi cấu hình đề xuất (production profile)
- `SEARXNG_ENGINES`: bỏ `google` ở profile mặc định nếu chưa có compliance + egress isolation hoàn chỉnh.
- `WEB_QUERY_DECOMPOSITION_MAX_SUBQUERIES`: giảm để kiểm soát burst.
- `WEB_SEARXNG_TOPK`: giảm baseline, tăng bằng adaptive policy khi cần.
- `WEB_SEARCH_STRICT_SOURCE_FILTER=true` + cấu hình allowlist domain đáng tin.
- Thêm flags mới:
  - `WEB_SEARCH_BROKER_ENABLED`
  - `WEB_SEARCH_PROVIDER_PRIORITY`
  - `WEB_SEARCH_GLOBAL_RPS`
  - `WEB_SEARCH_CIRCUIT_BREAKER_ENABLED`
  - `WEB_SEARCH_CACHE_TTL_SEC`
  - `WEB_SEARCH_EGRESS_MODE=isolated`

## 12) Acceptance criteria (Definition of Done)
- Không còn outbound search trực tiếp từ IP server/app chính.
- Có ít nhất 3 đường fallback độc lập (provider A/B + cache).
- Khi provider chính chết, hệ thống tự failover không downtime perceivable cho user.
- KPI latency/quality/security đạt ngưỡng ở mục SLO/KPI tối thiểu 7 ngày liên tục.
- Có runbook + dashboard + alert + rollback rõ ràng.

## 13) Gợi ý thứ tự thực thi ngay
1. Làm Phase 0 trong nhánh hotfix để giảm rủi ro tức thì.
2. Làm Phase 1 song song chuẩn bị provider credentials và contract tests.
3. Chốt kiến trúc mạng, triển khai Phase 2 trước khi mở lưu lượng lớn.
4. Tối ưu chất lượng/latency ở Phase 3 bằng đo lường thật.
