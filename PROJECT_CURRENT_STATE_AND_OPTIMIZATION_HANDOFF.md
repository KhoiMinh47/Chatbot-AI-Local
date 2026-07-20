# NTC Local Knowledge — Current State & Optimization Handoff

> Ngày chụp trạng thái: **2026-07-17, Asia/Ho_Chi_Minh**  
> Mục đích: cung cấp đủ bối cảnh để một AI/engineer khác tiếp quản việc tối ưu
> chất lượng trả lời, tốc độ chat, tốc độ upload/index và conversation memory.  
> Đây là tài liệu handoff kỹ thuật, **không phải tuyên bố production-ready**.

## 1. Yêu cầu dành cho AI/engineer tiếp quản

Hãy đọc toàn bộ tài liệu này và kiểm tra lại code/runtime trước khi sửa. Mục tiêu là
nâng chất lượng và hiệu năng dựa trên số đo, không chỉ thay prompt hoặc đổi model.

Các nguyên tắc bắt buộc:

1. Không làm hỏng tenant isolation, ACL, citation validation, audit trace, auth và
   tính idempotent của ingestion.
2. Không đổi LLM/embedding chỉ vì model khác nổi tiếng hơn. Trước hết phải sửa các
   lỗi wiring, retrieval, memory và streaming hiện có; nếu đổi model phải benchmark
   cùng dataset, GPU và cấu hình.
3. Mọi thay đổi chunking/embedding phải tạo physical Qdrant collection và
   `index_version` mới; chỉ chuyển alias sau khi eval pass và phải có rollback.
4. Không hiệu chỉnh threshold trên held-out set. Giữ riêng calibration, test và
   release holdout.
5. Không ghi PASS nếu chỉ chạy unit test/mock. Các chỉ số chất lượng và latency cuối
   phải lấy từ pipeline live end-to-end.
6. Không đưa secret, document content, raw prompt hoặc chain-of-thought vào log/report.
7. Thay đổi theo từng nhóm nhỏ, đo before/after, thêm regression test rồi mới đi tiếp.

## 2. Project hiện tại là gì

Đây là chatbot RAG nội bộ chạy local trên NVIDIA DGX Spark/GB10. Người dùng có thể
upload tài liệu, chờ worker parse/index, chọn tài liệu và hỏi đáp có citation.

### Stack chính

| Thành phần | Công nghệ/vai trò |
|---|---|
| Frontend | Next.js 16, React 19, SSE chat UI |
| API | Python 3.14, FastAPI, LangGraph |
| Worker | Celery, Docling, RabbitMQ |
| LLM | `nvidia/nemotron-nano-9b-v2`, NVIDIA NIM `1.0.0` |
| Embedding | `nvidia/llama-nemotron-embed-300m-v2`, NIM `1.13.0`, 2048 chiều |
| Reranker | Adapter/cấu hình có sẵn nhưng runtime hiện **tắt** |
| Vector DB | Qdrant |
| Metadata | PostgreSQL 16 |
| File/object | MinIO |
| Cache/rate limit | Redis |
| Queue | RabbitMQ + Celery |
| Gateway | Nginx |

### Luồng ingestion hiện tại

```text
Browser
  -> FastAPI nhận toàn bộ multipart file
  -> đọc toàn bộ file thành bytes, kiểm MIME, SHA-256
  -> ghi raw file vào MinIO
  -> ghi document/version/job vào PostgreSQL
  -> enqueue RabbitMQ
  -> Celery worker tải lại toàn bộ file từ MinIO
  -> Docling parse/normalize
  -> chunk child 256 + parent 2000, overlap 10%
  -> Embed 300M theo batch 16
  -> upsert Qdrant với wait=true
  -> cập nhật document READY
```

### Luồng chat/RAG hiện tại

```text
Question
  -> query embedding
  -> dense-only search trong Qdrant, có ACL/document filter
  -> deduplicate/diversify
  -> context packing
  -> Nemotron generate
  -> buffer toàn bộ answer
  -> citation validation
  -> sau đó mới phát các SSE token giả lập ra UI
```

Fast mode dùng một retrieval query. Reasoning mode có thể gọi LLM để rewrite/decompose
tối đa ba subquery rồi mới generate với `/think`.

## 3. Trạng thái runtime đã kiểm tra

Đây là snapshot tại thời điểm viết, không phải benchmark dài hạn:

- API, worker, web, PostgreSQL, Redis, MinIO, Qdrant, Nginx và hai NIM đang chạy.
- **RabbitMQ container đang `unhealthy`**, failing streak 157. Healthcheck lỗi:
  `Failed to create dirty io scheduler thread 4, error = 11`.
- Worker vẫn báo healthy và đã xử lý một job 18 chunks trong khoảng `8.97 s`, nhưng
  RabbitMQ unhealthy khiến upload/enqueue không thể được xem là ổn định.
- Worker idle dùng xấp xỉ `1.97 GiB / 8 GiB`; API khoảng `156 MiB / 2 GiB`.
- Qdrant alias `ntc_chunks_active` đang trỏ tới
  `ntc_chunks_embed300m_v2_uploads_v1`, có **820 points**, trạng thái green.
- Qdrant báo `indexed_vectors_count=0` vì collection nhỏ hơn
  `full_scan_threshold=10000`; truy vấn hiện có thể đang full-scan toàn bộ 820 vectors.

### Số liệu PostgreSQL live

| Dữ liệu | Kết quả |
|---|---:|
| Documents READY | 6 |
| Documents deleted | 2 |
| Ingestion jobs success | 9 |
| Ingestion jobs failed | 7 |
| Success ingestion average | 67.62 s |
| Success ingestion max | 551.23 s |
| Conversations | 23 |
| Messages persisted | **0** |

Lỗi ingestion đã tồn tại trong DB:

| Error | Số job |
|---|---:|
| `PARSER_CORRUPT_DOCUMENT` | 3 |
| `QUEUE_UNAVAILABLE` | 2 |
| `WORKER_INTERRUPTED` | 1 |
| `INGESTION_INTERNAL_ERROR` | 1 |

### Số liệu RAG trace live

Có 25 trace, tất cả lần dùng thực tế trong snapshot đều là Fast mode:

| Outcome | Số lượng | Tỷ lệ |
|---|---:|---:|
| `answered` | 13 | 52% |
| `insufficient_evidence` | 5 | 20% |
| `invalid_generation` | 5 | 20% |
| `error` | 2 | 8% |

Các lỗi generation gồm ba `uncited_claim`, hai `missing_citation` và hai
`rag_execution_failed`. Với 13 answer hợp lệ, tổng thời gian core
`retrieve + generate + planner` có p50 khoảng **2.52 s**, p95 khoảng **9.10 s**.
Đây chưa phải end-user latency hoàn chỉnh và chưa đo concurrency.

Kết luận thực tế: cảm nhận “trả lời không tốt/chậm, memory yếu và upload chậm” phù
hợp với code và số liệu live; không nên quy toàn bộ lỗi cho Nemotron.

## 4. Những gì project đã làm tốt

- Có tách API/worker và ingestion bất đồng bộ.
- Có MinIO, PostgreSQL, Qdrant và queue thay vì xử lý mọi thứ trong một process.
- Có hash/idempotency, version document, soft delete và retry state.
- Qdrant query giữ tenant/document/ACL filter trong truy vấn.
- Có grounded prompt, server-issued citation ID và citation validator.
- Có audit trace theo node, usage, model/index/policy fingerprint mà không lưu raw
  document hoặc chain-of-thought.
- Có Fast/Reasoning policy riêng và no-evidence branch không gọi LLM.
- NIM LLM đã được kiểm tra capability tới 131072 tokens; Embed 300M và Qdrant đang
  chạy live.
- Có test/acceptance artifact từ Phase 0–6; các artifact cũ hữu ích làm lịch sử,
  nhưng không thay thế benchmark trên corpus production mới.

## 5. Các vấn đề đã xác nhận trong code/runtime

### P0 — Conversation memory chưa được nối vào chat

`RagRequest` hỗ trợ `recent_messages` và `conversation_summary`, planner cũng có logic
rewrite follow-up. Tuy nhiên endpoint `/api/v1/chat/stream` chỉ truyền question,
scope và selected documents; không nạp message/history/summary.

DB hiện có 23 conversations nhưng **0 messages**. Schema message hiện chỉ lưu
`content_sha256`, không lưu nội dung có thể đọc lại. Vì vậy:

- chatbot gần như không nhớ turn trước;
- follow-up classifier không thể chạy đúng vì `recent_messages` luôn rỗng;
- summary không được tạo/nạp;
- conversation UI có thể tồn tại nhưng RAG mỗi request gần như độc lập.

Đây là nguyên nhân trực tiếp của “memory context yếu”, không phải do context window
của model trước tiên.

### P0 — Runtime token budget và tài liệu đang mâu thuẫn

- README ghi context 4096 và output 1000, nhưng code policy thực tế là cửa sổ 32768.
- Fast: context cap 8192, output 768, safety 1536.
- Reasoning: context cap 16384, output 4096, safety 2048.
- NIM đã chứng minh capability 131072, nhưng app chỉ dùng policy 32768.
- Runtime sử dụng `ApproxTokenCounter` theo `3.5 chars/token`, nhưng thuộc tính
  `exact` lại trả về `True`. Điều này có thể làm token budget sai, nhất là tiếng Việt,
  và tạo bằng chứng audit gây hiểu nhầm rằng tokenizer chính xác.

Không được tăng thẳng lên 128K. Trước hết phải dùng exact Nemotron tokenizer, đo
TTFT/VRAM và chỉ tăng context khi query thực sự cần.

### P0 — Retrieval policy live không đúng policy đã chọn ở Phase 5

Phase 5 từng chọn threshold `0.2300481`, candidate/final `20/10`, `hnsw_ef=128`.
Factory runtime hiện hard-code:

```text
dense_candidate_limit = 20
final_limit           = 10
dense_threshold       = 0.1
hnsw_ef                = 128
reranker_enabled       = false
```

Khi có selected document, graph còn bỏ threshold hoàn toàn. Điều này có thể tăng
recall nhưng đồng thời đưa context yếu/nhiễu vào prompt. Policy không được load từ
activation receipt/config versioned nên acceptance artifact và runtime đã drift.

### P0 — Retrieval còn là dense-only và không rerank

- Không có BM25/sparse/hybrid retrieval và RRF.
- Rerank 500M adapter có sẵn nhưng runtime tắt.
- Query expansion chỉ xuất hiện ở Reasoning mode và phải trả thêm LLM latency.
- Dedup hiện giữ tối đa một hit trên mỗi `(document, section_path)`. Với tài liệu có
  section dài, quy tắc này có thể loại nhiều chunk liên quan chỉ vì cùng section.
- Chunking cố định 256/10% chưa được A/B trên corpus 820 points hiện tại.
- Chưa có xử lý riêng đủ tốt cho bảng, heading, code, FAQ, multi-hop và cross-language.
- Qdrant collection hiện full-scan do ngưỡng HNSW mặc định; chưa phải vấn đề lớn ở
  820 points nhưng sẽ trở thành bottleneck khi corpus tăng.

### P0 — “Streaming” hiện làm người dùng cảm thấy chậm

NIM có stream delta, nhưng graph gom toàn bộ delta vào `pieces`, đợi model kết thúc,
validate citation rồi mới emit answer thành các đoạn nhỏ. Do đó UI chỉ thấy token đầu
tiên sau gần toàn bộ generation latency. SSE đang stream event, nhưng không phải
true model-token streaming.

Đây là trade-off an toàn hợp lý cho citation, nhưng UX cần được thiết kế lại theo
sentence-buffer/verified streaming hoặc ít nhất phát progress status rõ ràng.

### P0 — Upload đang copy toàn bộ file qua nhiều tầng

- FastAPI đọc toàn bộ multipart file thành `bytes` trước khi hash và ghi MinIO.
- Worker lại tải toàn bộ object thành `bytes` trước khi parse.
- Limit hiện là 500 MB; với API memory limit 2 GB, nhiều upload đồng thời có nguy cơ
  memory pressure/OOM và latency lớn.
- API hash, MIME sniff và MinIO write nằm trên request path.
- Browser gửi file qua Web/API thay vì direct/resumable upload vào object storage.
- Không có chunked/resumable upload hoặc progress theo bytes ở backend.

### P0 — Ingestion throughput và queue chưa ổn định

- RabbitMQ đang unhealthy do healthcheck/Erlang không tạo được dirty scheduler thread.
- Worker concurrency là 2; Docling là heavyweight và mỗi process giữ model riêng.
- Embedding batch size 16 đang hard-code trong worker indexing, không dùng adaptive
  batch/downshift đã có ở API NIM client.
- Các embedding batch và Qdrant upsert chạy tuần tự; mỗi upsert dùng `wait=true`.
- Worker parse, normalize, chunk, embed, upsert nằm trong một task dài; retry có thể
  lặp lại nhiều công đoạn tốn thời gian.
- Parser khai báo `do_ocr=False`, nhưng normalized metadata lại ghi
  `ocr_enabled=True`; telemetry này không phản ánh runtime thật.
- Chưa routing riêng text PDF, scanned PDF, Office và CSV sang queue/pool phù hợp.
- Worker idle đã gần 2 GiB; tăng concurrency mù quáng có thể làm tệ hơn.

### P1 — Cache và backpressure có code nhưng chưa được wire

`GroundedRagGraph` hỗ trợ Redis exact-cache và semaphore, nhưng `rag_factory.py` không
truyền `redis` hoặc `semaphore`; hai tính năng không hoạt động trong runtime hiện tại.
Nếu bật cache cần thêm model/index/prompt/policy fingerprint vào key và xử lý cache
corrupt bằng fallback an toàn. Không cache answer theo question đơn thuần khi corpus,
ACL hoặc conversation memory có thể thay đổi.

### P1 — Invalid generation bị thay bằng câu lỗi chung

Nếu citation thiếu hoặc sai, validator thay toàn bộ answer bằng thông báo generic.
Snapshot có 5/25 trace `invalid_generation` (20%). Cần giữ validator fail-closed,
nhưng nên có một repair/retry có giới hạn hoặc structured grounded generation để giảm
tỷ lệ user nhận câu trả lời vô ích.

### P1 — Prompt-only và document-scoped intent chưa rõ ràng

Cần xác định rõ ba hành vi:

1. Có selected documents: chỉ RAG trong tài liệu đã chọn.
2. Không chọn tài liệu nhưng hỏi kiến thức nội bộ: RAG toàn corpus user được phép.
3. Chào hỏi/general chat/creative request: direct LLM có nhãn rõ, hoặc từ chối theo
   product policy.

Hiện mọi question đi vào retrieval; general prompt dễ nhận insufficient evidence hoặc
context không liên quan.

### P1 — Observability chưa đủ để tối ưu chính xác

Trace có node timings nhưng thiếu dashboard live cho:

- upload receive/hash/MinIO/enqueue latency;
- queue wait, parse, normalize, chunk, embed, Qdrant upsert theo file;
- TTFT thật, inter-token latency, decode token/s;
- query embed/search/rerank/context-pack/generate/citation-repair;
- file type, page count, byte size, chunk count;
- concurrency, queue depth, NIM request queue, GPU/VRAM.

Không có những số này thì việc “optimize” dễ chỉ chuyển bottleneck từ chỗ này sang chỗ khác.

## 6. Kế hoạch tối ưu đề xuất theo thứ tự

### Stage 0 — Khóa baseline và bộ eval trước khi sửa

1. Tạo dataset production-like riêng từ tài liệu thật đã được phép dùng:
   - fact, table, multi-hop, cross-document, Vietnamese paraphrase;
   - follow-up/coreference qua 2–8 turns;
   - unanswerable và prompt injection;
   - selected-document và corpus-wide;
   - PDF text, PDF scan, DOCX, PPTX, CSV/MD/TXT.
2. Chia immutable `calibration`, `test`, `release_holdout`; không nhìn holdout khi tune.
3. Lưu expected document/chunk/page và answer rubric, không chỉ exact string answer.
4. Chạy baseline live ít nhất ba lần và ghi hardware/runtime/image digest.
5. Đo retrieval, generation, memory, ingestion và concurrency bằng cùng input.

Metric tối thiểu:

- Retrieval: Recall@5/10, MRR@10, nDCG@10, context precision, unanswerable nonempty rate.
- Answer: correctness, faithfulness, answer relevance, citation precision/recall,
  unsupported-claim rate, refusal accuracy; có human review mẫu tiếng Việt.
- Memory: follow-up resolution accuracy, entity/constraint retention, summary drift.
- Chat performance: TTFT p50/p95/p99, total latency, output tok/s, req/s, timeout/error.
- Ingestion: API acceptance latency, queue wait, parse/embed/index duration, jobs/min,
  peak RAM, failure/retry rate theo file type/size.

### Stage 1 — Sửa stability và upload path

1. Sửa RabbitMQ healthcheck/resource configuration; root cause hiện tại liên quan
   Erlang dirty scheduler thread và process/thread limit. Sau fix phải chạy healthy ổn
   định và enqueue/dequeue không rớt job.
2. Đổi API upload sang streaming/spooled file; tính SHA-256 khi stream, không giữ toàn
   bộ file trong RAM.
3. Tốt hơn: dùng presigned multipart upload trực tiếp browser -> MinIO, sau đó API
   finalize/validate/enqueue. Hỗ trợ resume, retry part và progress.
4. Ghi stage timestamps vào job; UI hiển thị `uploading`, `queued`, `parsing`,
   `embedding`, `indexing`, `ready/failed` với lỗi có thể hành động.
5. Warm Docling/parser assets khi worker start. Detect PDF scan để chỉ bật OCR khi cần;
   không chạy layout/OCR nặng cho TXT/MD/CSV.
6. Tách queue/pool cho light documents và heavy/scanned PDF để file lớn không chặn file nhỏ.
7. Benchmark concurrency 1/2/... theo RAM thực tế; chọn worker count/prefetch bằng số
   đo, không chỉ tăng concurrency.
8. Cho embedding batch size thành config; thử 16/32/64, adaptive downshift khi OOM/413.
9. Upsert Qdrant theo batch lớn hơn; đánh giá `wait=false` + final consistency check.
10. Không tạo/chuyển alias trong từng document task. Provision collection/index/alias
    bằng migration/deployment job riêng.

### Stage 2 — Làm conversation memory thật

1. Thiết kế nơi lưu nội dung message có mã hóa/access control và retention policy.
   `content_sha256` chỉ dùng audit/dedup, không thể làm memory.
2. Persist user message trước khi chạy; persist assistant message + trace atomically khi
   hoàn thành. Xử lý idempotency/reconnect/cancel.
3. Load recent turns theo conversation/user/tenant từ server, không nhận history tùy ý
   từ client.
4. Dùng sliding window theo exact token budget; summary các turn cũ và giữ facts,
   decisions, entities, constraints, unresolved questions.
5. Version summary prompt/model, lưu source turn range và kiểm tra summary drift.
6. Nối `recent_messages`/`conversation_summary` vào `RagRequest`.
7. Thay regex follow-up đơn giản bằng classifier/rule hybrid có eval; rewrite chỉ khi cần.
8. Cache phải bao gồm conversation state/version hoặc tắt cache cho follow-up.

### Stage 3 — Nâng retrieval quality

1. Thay `ApproxTokenCounter` bằng exact tokenizer của Nemotron; tuyệt đối không báo
   `exact=True` cho approximation.
2. Load retrieval policy từ config/activation receipt đã version hóa; bỏ hard-code 0.1
   hoặc chứng minh threshold mới bằng calibration.
3. A/B chunking 256/512/768 và overlap 10/20%, ưu tiên structure-aware chunking:
   heading, paragraph, table row/header, list, slide và parent-child.
4. Dùng child chunk để search nhưng mở rộng parent/neighbor có giới hạn khi assemble context.
5. Thêm sparse/BM25 + dense hybrid và RRF; đặc biệt hữu ích cho mã, tên riêng, số hiệu,
   từ khóa và câu hỏi tiếng Việt có exact term.
6. Benchmark NIM Rerank 500M: lấy dense/sparse candidates rộng hơn, rerank rồi chọn
   context cuối. Chỉ bật nếu held-out quality tăng đủ so với latency.
7. Sửa dedup để không loại tất cả chunk cùng section; dùng content overlap/MMR/source
   diversity có ngưỡng.
8. Thêm query normalization, acronym/entity expansion và cross-language strategy có eval.
9. Với selected document, không nên mặc định bỏ toàn bộ relevance threshold; dùng scope-aware
   threshold hoặc reranker/no-evidence classifier.
10. Tune HNSW/indexing threshold khi corpus tăng; đo recall/latency trước và sau.

### Stage 4 — Nâng generation quality và giảm latency cảm nhận

1. Phân loại intent để tách document-scoped RAG, corpus-wide RAG và general chat theo
   product policy.
2. Giữ temperature 0 làm baseline; tune prompt/context trước khi tune sampling.
3. Làm context compact hơn: loại duplicate, giữ heading/page, ưu tiên evidence phủ đủ
   các subquestion thay vì nhét top-k thuần túy.
4. Dùng structured answer/citation schema nếu NIM/model hỗ trợ ổn định.
5. Khi citation fail, chạy tối đa một grounded repair pass với cùng allowlist; không
   tự tạo citation và không retry vô hạn.
6. Cân nhắc sentence-buffer streaming: chỉ phát câu đã qua kiểm tra citation/allowlist.
   Nếu chưa làm được, phát status/progress ngay và hiển thị rõ phase đang chạy.
7. Đo TTFT thật từ browser/gateway; tránh Nginx/proxy buffering và xử lý disconnect.
8. Wire semaphore/backpressure và rate limit phù hợp để tải cao không làm mọi request chậm.
9. Wire cache có version/fingerprint/ACL/memory-safe key; cache query embedding và
   retrieval result ngắn hạn trước khi cache answer.
10. Tune NIM/vLLM continuous batching, max batched tokens, KV cache và concurrency dựa
    trên benchmark; không đoán theo cấu hình project khác.

### Stage 5 — Tận dụng context đúng cách

1. Giữ 32K làm baseline đã kiểm chứng trong app, sau đó test 64K trước khi cân nhắc 128K.
2. Dynamic context budget theo query complexity; câu hỏi đơn không cần prompt 64K.
3. Budget riêng cho system, recent turns, summary, retrieved evidence và output.
4. Long-context eval phải kiểm tra lost-in-the-middle, citation đúng page và latency/VRAM.
5. Ưu tiên retrieval/memory tốt hơn trước khi mở context tối đa; context dài không sửa
   được retrieval nhiễu và còn làm TTFT chậm hơn.

### Stage 6 — Release gate và regression

1. Chạy unit/integration/security test hiện có.
2. Chạy live ingestion matrix và live RAG matrix trên deployment candidate.
3. Chạy load 1/5/10/20/50 concurrent users hoặc tới giới hạn phần cứng.
4. So sánh before/after cùng dataset/config; report cả regression và trade-off.
5. Canary trên corpus nhỏ, monitor, rồi mới atomic alias/config switch.
6. Có rollback cho app image, prompt/policy version và Qdrant alias.

## 7. Acceptance criteria đề xuất

Các ngưỡng dưới đây là mục tiêu ban đầu. Sau baseline đầu tiên có thể điều chỉnh một
lần với lý do rõ ràng, sau đó phải khóa trước khi tune.

### Stability/ingestion

- RabbitMQ/API/worker/NIM/Qdrant healthy liên tục ít nhất 30 phút trong smoke/load run.
- 0 lost job, 0 duplicate active chunk coordinate trong retry/redelivery test.
- Upload API không giữ toàn bộ 500 MB trong RAM; peak API memory được chứng minh bounded.
- Tỷ lệ job lỗi không chủ ý <1% trên ingestion test matrix; lỗi corrupt/unsupported phải
  fail đúng mã và có thông báo rõ.
- File nhỏ không phải chờ sau một scanned PDF lớn trong queue ưu tiên.
- Báo p50/p95 riêng cho 1 MB text, 10–50 MB PDF và file lớn; không gộp thành một số đẹp.

### Retrieval/answer quality

- Held-out Recall@10 >= 0.95 hoặc không thấp hơn baseline; context precision phải tăng,
  không được đổi recall lấy context rác.
- Citation precision = 1.00 trên automated gate; citation recall >= 0.95 trên answerable.
- Unsupported factual claim rate <= 2% trên human-reviewed sample.
- `invalid_generation` <2%; không còn mức live 20% hiện tại.
- Unanswerable false-answer rate <= 5%.
- Table, follow-up và Vietnamese paraphrase mỗi nhóm đều phải report riêng.

### Memory

- Persisted messages >0 và được reload đúng sau API restart.
- Follow-up resolution accuracy >=90% trên bộ multi-turn riêng.
- Không lẫn conversation/user/tenant; cross-tenant memory leakage = 0.
- Summary giữ đúng các facts/constraints quan trọng và có regression test cho summary drift.

### Performance

- Báo end-to-end TTFT và total latency từ gateway/UI, không dùng HTTP 200 làm TTFT.
- Mục tiêu đầu: Fast TTFT p50 <=1.5 s, p95 <=4 s; total core latency p95 phải tốt hơn
  snapshot 9.10 s và không giảm quality.
- Report decode tok/s, req/s, timeout/error rate và VRAM tại concurrency 1/5/10/20.
- Reasoning có thể chậm hơn Fast nhưng phải tạo quality gain đo được; nếu không thì không
  gọi planner/decomposition thừa.

### Context

- Exact tokenizer được hash/version-bound; budget không vượt runtime context.
- Pass long-context 32K; 64K/128K chỉ activate sau khi pass correctness + latency + VRAM.
- Memory summary và evidence không bị cắt im lặng; trace phải ghi số token từng phần.

## 8. File/code map quan trọng

| File | Vai trò/điểm cần sửa |
|---|---|
| `apps/api/app/api/conversations.py` | Chat SSE; hiện chưa load/persist memory |
| `apps/api/app/rag/graph.py` | LangGraph, buffered streaming, cache/semaphore hooks |
| `apps/api/app/application/rag.py` | Prompt, token packing, citation validation |
| `apps/api/app/rag/planner.py` | Follow-up rewrite/decomposition |
| `apps/api/app/infrastructure/rag_factory.py` | Hard-coded retrieval policy, approximate tokenizer wiring |
| `apps/api/app/infrastructure/approx_token_counter.py` | Approximation đang báo `exact=True` |
| `apps/api/app/application/retrieval.py` | Dense retrieval, dedup, optional reranker |
| `apps/api/app/application/ingestion.py` | API upload bytes/hash/MinIO/enqueue |
| `apps/worker/worker/tasks/__init__.py` | Pipeline ingestion dài trong một Celery task |
| `apps/worker/worker/parsers/__init__.py` | Docling/OCR routing và metadata mismatch |
| `apps/worker/worker/indexing.py` | Batch 16, sequential embedding/upsert, alias provisioning |
| `apps/worker/worker/settings.py` | Worker tuning knobs |
| `compose.yaml` | Resource limits, worker concurrency, runtime wiring |
| `compose.phase3.yaml` | NIM services/runtime |
| `infra/nginx/nginx.conf` | Upload/SSE proxy settings |
| `artifacts/phase-3..6/` | Historical acceptance/evidence, không phải current benchmark |
| `packages/rag-eval/` | Metric/calibration utilities có thể tái sử dụng |

## 9. Thứ tự PR/change set nên làm

1. **Baseline & telemetry** — dataset, stage timings, dashboard/report.
2. **Queue + streaming upload** — RabbitMQ healthy, bounded-memory upload, UI progress.
3. **Conversation persistence/memory** — lưu/nạp messages, exact token budgeting, summary.
4. **Retrieval policy correctness** — config/receipt binding, threshold drift, dedup fix.
5. **Hybrid + reranker experiments** — benchmark và activate nếu thắng.
6. **Generation/citation repair + verified streaming**.
7. **NIM/context/concurrency tuning**.
8. **Full load/release regression + rollback rehearsal**.

Không gom toàn bộ thành một PR lớn vì sẽ không biết thay đổi nào làm quality tốt hoặc xấu.

## 10. Những việc không nên làm

- Không đổi Nemotron sang model khác trước khi memory/retrieval/runtime wiring được sửa.
- Không copy thông số vLLM/Gemma từ project tham khảo vào NIM một cách máy móc.
- Không tăng top-k/context window vô hạn để “chữa” recall.
- Không bật OCR cho mọi PDF.
- Không tăng Celery concurrency khi chưa đo peak RAM/CPU/GPU contention.
- Không bỏ citation validator để giảm `invalid_generation`.
- Không cache answer mà thiếu tenant, ACL, selected docs, conversation state và
  model/index/prompt/policy version trong key.
- Không re-index đè collection đang active.
- Không dùng Phase 5/12 score cũ như bằng chứng rằng corpus production hiện tại đã tốt.
- Không chỉ chạy unit test rồi kết luận chatbot trả lời chính xác.

## 11. Definition of Done cho đợt optimize

Đợt tối ưu chỉ được coi hoàn thành khi:

1. Root causes P0 trong tài liệu này đã được sửa hoặc có evidence bác bỏ.
2. Memory multi-turn hoạt động thật và survives restart.
3. Upload bounded-memory, queue healthy, stage progress rõ và test file nhỏ/lớn pass.
4. Retrieval/generation before-after được đo trên held-out production-like dataset.
5. Chất lượng tăng mà không phá ACL/citation/security.
6. TTFT/latency/concurrency được đo end-to-end và đạt gate đã khóa.
7. Có artifact tái lập: config, image/model/version, dataset hash, report và commands.
8. Có rollback đã test cho app config và Qdrant alias.

## 12. Tóm tắt một câu cho AI tiếp quản

Project không “cùi” vì thiếu nhiều framework; phần khung đã khá đầy đủ. Vấn đề chính là
nhiều thành phần tốt chưa được nối/tune đúng trong runtime: memory bằng 0, tokenizer chỉ
xấp xỉ nhưng báo exact, retrieval policy drift và không rerank/hybrid, answer bị buffer
trước SSE, upload copy toàn file qua RAM, ingestion task dài và RabbitMQ đang unhealthy.
Hãy sửa các điểm này theo số đo trước khi cân nhắc đổi model.
