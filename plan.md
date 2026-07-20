# PLAN.md — Nâng cấp chất lượng chatbot local dùng NVIDIA Nemotron Nano 9B v2 trên DGX Spark / ASUS GB10

> **Mục tiêu chính:** nâng chatbot hiện tại thành một hệ thống trả lời chính xác hơn, đầy đủ hơn, có trí nhớ hội thoại dài hạn, đọc file đáng tin cậy, citation đúng nguồn và phản hồi nhanh hơn.  
> **Không ưu tiên:** giảm kích thước model, giảm RAM, giảm context hoặc tối ưu để chạy trên phần cứng yếu.  
> **Phần cứng mục tiêu:** ASUS Ascent GX10 / NVIDIA GB10, 128 GB unified memory.  
> **Model mục tiêu ban đầu:** `nvidia/NVIDIA-Nemotron-Nano-9B-v2`.

---

## 0. Chỉ thị bắt buộc dành cho AI Agent

Agent phải làm theo thứ tự dưới đây, không được bắt đầu bằng cách viết lại toàn bộ project hoặc fine-tune model ngay lập tức.

1. Đọc toàn bộ cấu trúc repository và xác định:
   - ngôn ngữ, framework backend/frontend;
   - runtime đang dùng để serve model;
   - nơi tạo prompt;
   - nơi lưu lịch sử hội thoại;
   - pipeline upload/parse/index file;
   - vector database hoặc search engine;
   - logic tạo citation;
   - các giới hạn token ở frontend, backend, reverse proxy và inference server;
   - logging, tracing và test hiện có.

2. Tạo báo cáo audit trước khi sửa:
   - `docs/chatbot-quality-audit.md`;
   - sơ đồ luồng hiện tại từ user input đến model output;
   - danh sách root cause có bằng chứng từ code/config/log;
   - baseline latency và chất lượng;
   - danh sách file dự kiến sửa.

3. Không thay đổi API public hoặc schema dữ liệu hiện tại nếu không cần thiết. Nếu buộc phải thay đổi:
   - bổ sung migration;
   - giữ backward compatibility;
   - cập nhật tài liệu;
   - thêm test.

4. Không fine-tune model trong giai đoạn đầu. Phải sửa orchestration, memory, RAG, citation và generation trước. Chỉ đề xuất LoRA/SFT sau khi đã có benchmark chứng minh lỗi còn nằm ở model.

5. Không để model tự tạo URL, tên file, số trang hoặc citation từ trí nhớ. Citation phải được backend dựng từ metadata đã xác thực.

6. Mọi thay đổi phải có:
   - unit test;
   - integration test;
   - benchmark trước/sau;
   - feature flag hoặc cách rollback;
   - logging đủ để debug.

7. Tạo checklist tiến độ trong `docs/chatbot-quality-progress.md` và cập nhật sau mỗi phase.

---

# 1. Kết quả mong muốn

Sau khi hoàn tất, chatbot phải có các khả năng sau:

## 1.1. Trí nhớ hội thoại

- Nhớ chính xác các thông tin vừa trao đổi trong cùng conversation.
- Hiểu câu hỏi nối tiếp như:
  - “còn cái thứ hai thì sao?”;
  - “sửa lại đoạn đó”;
  - “file tôi vừa gửi có nhắc điều này không?”;
  - “dùng cấu hình tôi nói ở trên”.
- Không phụ thuộc hoàn toàn vào việc nhét toàn bộ lịch sử chat vào prompt.
- Có rolling summary và semantic memory để hội thoại dài vẫn hoạt động.
- Có khả năng lưu thông tin lâu dài theo user/workspace khi được cấu hình.
- Có thể xóa/reset memory rõ ràng.
- Memory phải có provenance, thời điểm tạo và confidence; không được biến suy đoán của model thành fact chắc chắn.

## 1.2. Trả lời chi tiết và đầy đủ

- Không mặc định trả lời quá ngắn.
- Phân biệt được câu hỏi đơn giản với yêu cầu cần phân tích sâu.
- Với câu hỏi kỹ thuật hoặc phân tích file:
  - trả lời trực tiếp;
  - giải thích nguyên nhân;
  - đưa bằng chứng;
  - nêu giới hạn/điểm chưa chắc;
  - đề xuất bước thực hiện;
  - citation cho các claim lấy từ tài liệu.
- Không bị cắt cụt do `max_tokens`, stop sequence, proxy timeout hoặc UI.
- Có chế độ “concise”, “normal”, “detailed”, nhưng mặc định là `detailed` cho project này.

## 1.3. Đọc file tốt

- Parse đúng PDF, DOCX, PPTX, XLSX/CSV, TXT/Markdown, source code và HTML.
- Giữ metadata:
  - tên file;
  - loại file;
  - page/slide/sheet;
  - heading/section;
  - row/column hoặc cell range;
  - line number với source code;
  - document version/hash.
- Đọc được bảng, heading và cấu trúc tài liệu, không chỉ lấy text phẳng.
- OCR chỉ dùng khi page thực sự không có text hoặc text extraction quá kém.
- Có parse-quality report để phát hiện file đọc thiếu.
- Không đưa cả file khổng lồ vào prompt một cách mù quáng.

## 1.4. Citation đúng nguồn

- Citation chỉ được phép tham chiếu evidence đã retrieval.
- Không tồn tại citation ID giả.
- Link/tên file/page phải do backend render từ metadata.
- Mỗi citation phải trỏ đúng đoạn hỗ trợ claim tương ứng.
- Nếu không có nguồn đủ mạnh, chatbot phải nói không tìm thấy bằng chứng thay vì bịa.
- Có post-generation citation validator.
- Có test tự động cho citation precision, citation coverage và source validity.

## 1.5. Tốc độ

- Streaming token ngay khi có thể.
- Model luôn warm trong chế độ sử dụng bình thường.
- Tối ưu prefill cho prompt dài.
- Cache các bước deterministic: parsing, OCR, embeddings, retrieval và prompt prefix khi runtime hỗ trợ.
- Reranking và retrieval chạy song song khi hợp lý.
- Không đánh đổi chất lượng citation hoặc memory chỉ để giảm latency.

---

# 2. Giả thuyết root cause cần kiểm chứng

Agent phải kiểm tra từng giả thuyết bằng code hoặc log, không được coi đây là kết luận sẵn.

## 2.1. Model “quên câu trước”

Các nguyên nhân có khả năng cao:

- Backend chỉ gửi message hiện tại tới model.
- Frontend có history nhưng API request không chứa đầy đủ messages.
- History bị giới hạn theo số message thay vì token và vô tình xóa message quan trọng.
- Conversation ID bị đổi giữa các request.
- Database lưu message nhưng prompt builder không đọc lại.
- Role mapping sai (`user`, `assistant`, `system`, `tool`).
- Chat template của Nemotron không được áp dụng đúng.
- Summary ghi đè hoặc làm sai thông tin gốc.
- Tool result/file evidence không được gắn lại vào turn sau.
- Context bị truncate từ đầu thay vì dùng chính sách giữ thông tin quan trọng.

## 2.2. Citation sai nguồn

Các nguyên nhân có khả năng cao:

- Prompt yêu cầu model tự viết citation dạng URL/tên file.
- Chunk không có stable ID.
- Metadata source bị mất sau bước rerank.
- Citation index trong prompt khác index ở UI.
- Retrieval trả chunk gần nghĩa nhưng không thực sự hỗ trợ claim.
- Không có reranker.
- Chunk quá lớn hoặc quá nhỏ.
- Không có post-validation.
- Model được phép dùng kiến thức nền nhưng UI vẫn hiển thị như thể có nguồn.
- Citation renderer dựa trên thứ tự array dễ thay đổi.
- Multi-file query không filter đúng tenant/conversation/document.

## 2.3. Trả lời ngắn, thiếu chi tiết

Các nguyên nhân có khả năng cao:

- System prompt có câu như “be concise”, “briefly”, “short answer”.
- `max_tokens`/`max_new_tokens` quá thấp.
- Frontend gửi giá trị mặc định thấp hơn backend.
- Reverse proxy timeout khiến stream bị ngắt.
- Stop sequence trùng với output của model.
- Reasoning bị tắt bằng `/no_think`.
- Thinking budget quá thấp.
- Prompt không có rubric về completeness.
- Context evidence chiếm gần hết token budget nên output bị bóp.
- UI chỉ render phần trước hoặc parser bỏ phần sau `</think>`.
- Output sanitizer xóa nhầm nội dung.
- Model bị ép JSON schema quá chặt.

## 2.4. Đọc file thiếu

Các nguyên nhân có khả năng cao:

- Chỉ lấy text từ một số page.
- File parser không xử lý bảng, columns, headers hoặc text boxes.
- OCR chạy mọi page và làm giảm chất lượng text digital.
- Upload worker timeout hoặc file-size limit.
- Chunker cắt mất heading/table context.
- Embedding model yếu với tiếng Việt hoặc tài liệu dài.
- Retrieval chỉ dùng dense vector, không có lexical search.
- Không rerank.
- Không expand query hoặc xử lý câu hỏi nối tiếp.
- Không có parent-child retrieval.
- Không có parse coverage metric.

---

# 3. Phase 1 — Audit và baseline

## 3.1. Inventory hệ thống

Agent phải lập bảng sau trong `docs/chatbot-quality-audit.md`:

| Thành phần | Công nghệ hiện tại | File/config liên quan | Vấn đề phát hiện | Hướng sửa |
|---|---|---|---|---|
| Frontend chat |  |  |  |  |
| Chat API |  |  |  |  |
| Prompt builder |  |  |  |  |
| Model runtime |  |  |  |  |
| Conversation store |  |  |  |  |
| File ingestion |  |  |  |  |
| Chunking |  |  |  |  |
| Embedding |  |  |  |  |
| Vector/keyword search |  |  |  |  |
| Reranker |  |  |  |  |
| Citation builder |  |  |  |  |
| Observability |  |  |  |  |
| Tests/evals |  |  |  |  |

## 3.2. Trace một request hoàn chỉnh

Bổ sung request correlation ID và trace ít nhất các mốc:

1. user submits message;
2. conversation loaded;
3. memory retrieved;
4. query rewritten;
5. document retrieval;
6. rerank;
7. prompt assembled;
8. token count;
9. inference request started;
10. first token;
11. generation completed;
12. citation validation;
13. response persisted;
14. frontend received final event.

Không log nội dung nhạy cảm ở production. Cho phép debug logging có redaction trong local development.

## 3.3. Ghi lại baseline

Tạo script benchmark có thể chạy lặp lại, ví dụ:

```bash
make eval-chatbot
make benchmark-chatbot
```

Nếu project không dùng Makefile thì tạo command tương đương trong package manager hiện tại.

Baseline phải gồm:

- TTFT: time to first token;
- total latency;
- input tokens;
- output tokens;
- output tokens/second;
- retrieval latency;
- rerank latency;
- parse/index latency;
- memory hit rate;
- citation validity;
- citation precision;
- answer completeness;
- groundedness;
- tỷ lệ response bị truncate;
- GPU/unified-memory usage;
- error rate.

Lưu kết quả baseline vào:

```text
artifacts/evals/baseline-<date>.json
artifacts/evals/baseline-<date>.md
```

---

# 4. Phase 2 — Sửa model runtime và generation config

## 4.1. Xác nhận đúng model/chat template

Phải xác minh:

- checkpoint là bản instruct/chat:
  - `nvidia/NVIDIA-Nemotron-Nano-9B-v2`;
- không dùng nhầm `-Base`;
- tokenizer và chat template lấy từ cùng checkpoint;
- không tự nối prompt bằng chuỗi thủ công nếu runtime hỗ trợ chat template;
- role và tool messages giữ đúng cấu trúc;
- output parser không làm mất phần final answer.

## 4.2. Runtime ưu tiên chất lượng

Vì mục tiêu là chất lượng, tạo hai profile để benchmark:

### Profile A — Quality baseline

- BF16 nếu runtime trên GB10 hỗ trợ ổn định.
- Context server tối đa có thể để 128K.
- `mamba_ssm_cache_dtype=float32`.
- Không quantize thêm nếu chưa benchmark.
- Dùng phiên bản vLLM/NIM/TRT-LLM tương thích chính thức với GB10.

### Profile B — DGX Spark optimized

- NIM DGX Spark NVFP4 hoặc engine NVIDIA tối ưu cho GB10.
- Chỉ chọn làm production default nếu:
  - citation/QA/memory quality không giảm đáng kể so với BF16;
  - latency hoặc throughput tốt hơn rõ ràng;
  - tất cả integration feature cần thiết đều hoạt động.

Không được tự kết luận NVFP4 tốt hơn hay kém hơn; phải chạy cùng eval set.

## 4.3. Các setting bắt buộc cần audit

- `max_model_len`;
- `max_tokens` / `max_new_tokens`;
- `temperature`;
- `top_p`;
- reasoning mode;
- thinking budget;
- stop sequences;
- repetition/frequency penalties;
- tokenizer truncation side;
- stream mode;
- request timeout;
- proxy timeout;
- UI response cap;
- server-side response cap.

## 4.4. Cấu hình generation khởi điểm

Dùng làm baseline, sau đó tune bằng eval:

### Với câu hỏi cần reasoning

- bật `/think`;
- `temperature=0.6`;
- `top_p=0.95`;
- `max_new_tokens` mặc định tối thiểu `4096`;
- cho phép `8192` với phân tích nhiều file hoặc yêu cầu dài;
- thinking budget adaptive:
  - simple factual: 256–512;
  - technical analysis: 1024–2048;
  - multi-document synthesis/debug phức tạp: 2048–4096;
  - chỉ tăng hơn khi eval chứng minh có lợi.

### Với câu hỏi rất đơn giản

- có thể dùng `/no_think`;
- greedy decoding;
- output budget vẫn đủ để không cắt câu.

### Quy tắc router

Tạo `ReasoningPolicy` hoặc module tương đương:

```text
simple greeting / formatting / direct lookup
    -> no_think

follow-up requiring memory
    -> think, low-medium budget

code debugging / architecture / multi-step logic
    -> think, medium-high budget

multi-file synthesis / conflicting evidence
    -> think, high budget
```

Router phải deterministic trước; có thể bổ sung classifier nhẹ sau. Không dùng chính Nemotron gọi thêm một lần nếu chi phí latency không cần thiết.

## 4.5. Response depth policy

Tạo trường cấu hình:

```text
response_depth = concise | normal | detailed
```

Default của project: `detailed`.

System prompt không được dùng các chỉ thị chung như “always be concise”. Thay vào đó:

- trả lời trực tiếp trước;
- giải thích đủ các bước cần thiết;
- dùng section khi câu trả lời dài;
- nêu assumptions;
- không lặp lại;
- không kéo dài nếu câu hỏi chỉ cần một đáp án ngắn;
- với file/RAG, mọi claim quan trọng phải có evidence.

## 4.6. Context budget

Server có thể hỗ trợ tối đa 128K, nhưng prompt assembler phải dùng budget động.

Khởi điểm:

```text
system/policy:          2K–4K
conversation summary:  1K–3K
long-term memory:      1K–4K
recent turns:          8K–16K
retrieved evidence:   16K–40K
current request:        actual size
reserved output:        4K–8K
```

Không nhét 128K lịch sử raw vào mọi request. Long memory phải dựa trên persistence + retrieval + summary, không chỉ context window.

---

# 5. Phase 3 — Xây memory đúng nghĩa

Thiết kế memory thành ba tầng tách biệt.

## 5.1. Working memory — recent exact turns

Giữ nguyên văn các turn gần nhất theo token budget, không chỉ theo số message.

Yêu cầu:

- luôn giữ system message;
- luôn giữ current user turn;
- ưu tiên giữ các turn có file/tool references;
- không tách tool call khỏi tool result;
- không truncate giữa một message;
- dùng tokenizer thật của Nemotron để đếm token;
- lưu lịch sử ở database, không phụ thuộc state của frontend.

Khởi điểm:

- giữ 8–16 turn gần nhất;
- hoặc 12K–20K tokens;
- chọn ngưỡng bằng benchmark thực tế.

## 5.2. Rolling conversation summary

Khi recent history vượt ngưỡng:

- tạo summary có cấu trúc;
- không thay thế toàn bộ history ngay lập tức;
- giữ overlap vài turn để chống mất context;
- version summary;
- lưu source message IDs dùng để tạo summary.

Schema gợi ý:

```json
{
  "conversation_id": "...",
  "summary_version": 3,
  "covered_message_ids": ["..."],
  "user_goal": "...",
  "known_facts": [],
  "decisions": [],
  "open_questions": [],
  "constraints": [],
  "referenced_documents": [],
  "current_working_state": "...",
  "created_at": "..."
}
```

Summary prompt phải yêu cầu:

- không suy diễn;
- phân biệt fact, preference, decision và assumption;
- giữ tên biến, đường dẫn, phiên bản, con số;
- giữ unresolved issues;
- không bỏ các ràng buộc user đã nêu.

Thêm test “summary drift”: sau nhiều lần re-summary, fact không được biến đổi.

## 5.3. Long-term semantic memory

Tạo store riêng cho các memory item có cấu trúc.

Schema tối thiểu:

```json
{
  "id": "...",
  "user_id": "...",
  "workspace_id": "...",
  "conversation_id": "...",
  "type": "preference|fact|decision|project_state|todo",
  "content": "...",
  "source_message_ids": ["..."],
  "confidence": 0.0,
  "created_at": "...",
  "updated_at": "...",
  "expires_at": null,
  "status": "active|superseded|deleted"
}
```

### Quy tắc ghi memory

Chỉ ghi khi:

- user nói rõ preference/fact;
- có quyết định dự án;
- có trạng thái cần dùng lại;
- có nhiệm vụ đang dang dở.

Không ghi:

- suy đoán của assistant;
- dữ liệu tạm thời không có ích;
- nội dung nhạy cảm không cần thiết;
- mọi câu chat một cách mù quáng.

### Quy tắc retrieval memory

Trước mỗi generation:

1. classify intent;
2. tạo memory query từ current turn + recent context;
3. hybrid retrieve;
4. rerank;
5. đưa top memory vào prompt với stable IDs;
6. nếu memory xung đột, ưu tiên item mới hơn hoặc hỏi lại thay vì tự chọn.

## 5.4. Conversation state

Ngoài message history, duy trì state riêng:

```json
{
  "active_documents": [],
  "active_code_files": [],
  "current_task": "...",
  "last_referenced_entities": [],
  "pending_tool_calls": [],
  "response_depth": "detailed",
  "reasoning_policy": "adaptive"
}
```

Điều này giúp xử lý các câu như “file đó”, “đoạn trên”, “cái thứ hai”.

## 5.5. Memory API/UI

Bổ sung nếu chưa có:

- reset conversation memory;
- clear long-term memory;
- xem các memory item đã lưu;
- sửa/xóa memory sai;
- bật/tắt persistent memory;
- export conversation.

---

# 6. Phase 4 — File ingestion chất lượng cao

## 6.1. Canonical document model

Mọi parser phải chuyển tài liệu về một cấu trúc chung:

```json
{
  "document_id": "...",
  "version_id": "...",
  "content_hash": "...",
  "filename": "...",
  "mime_type": "...",
  "language": "...",
  "blocks": [
    {
      "block_id": "...",
      "type": "heading|paragraph|table|code|list|image_caption",
      "text": "...",
      "page": 1,
      "slide": null,
      "sheet": null,
      "cell_range": null,
      "heading_path": ["...", "..."],
      "line_start": null,
      "line_end": null,
      "bbox": null,
      "parser_confidence": 0.0
    }
  ]
}
```

Stable IDs phải được tạo từ document version + location, không dựa vào thứ tự retrieval.

## 6.2. Parser theo loại file

Agent ưu tiên thư viện đang có nếu chất lượng đủ; nếu không, thay hoặc bổ sung adapter.

### PDF

- thử native text extraction trước;
- phát hiện scanned page;
- OCR chỉ page không có text hoặc text quality thấp;
- giữ page number;
- xử lý multi-column;
- giữ table structure;
- lưu warning với page lỗi;
- có thể lưu thumbnail/image reference nhưng không nhét ảnh vào text model nếu project chưa có VLM.

### DOCX

- headings;
- paragraph order;
- tables;
- lists;
- headers/footers khi cần;
- hyperlink text và target;
- comments/footnotes nếu use case cần.

### PPTX

- slide number;
- title;
- text boxes theo reading order;
- speaker notes;
- tables;
- chart labels/data nếu extract được;
- relation giữa title và body.

### XLSX/CSV

- workbook/sheet;
- used range;
- header detection;
- cell values và formulas;
- merged cells;
- table chunks theo row groups;
- không biến toàn bộ spreadsheet lớn thành một paragraph.

### Source code

- path;
- language;
- symbol/class/function;
- line numbers;
- imports;
- parent module;
- chunk theo AST/symbol khi có thể;
- fallback theo line window có overlap.

## 6.3. Parse quality gate

Sau ingestion, tính:

- số page/slide/sheet dự kiến;
- số page/slide/sheet có content;
- text length;
- số bảng;
- số warning;
- OCR pages;
- empty pages;
- duplicate ratio;
- encoding errors.

Nếu coverage thấp:

- đánh dấu document `needs_review`;
- hiển thị warning cho user;
- không giả vờ đã đọc đầy đủ.

## 6.4. Versioning và deduplication

- hash file;
- không index lại bản giống hệt;
- khi file thay đổi, tạo version mới;
- citation phải trỏ đúng version;
- xóa document phải xóa/index tombstone đúng tenant;
- không để stale chunks tiếp tục retrieval.

---

# 7. Phase 5 — RAG chính xác cho tiếng Việt và tài liệu dài

## 7.1. Tách retrieval khỏi generation

Pipeline đề xuất:

```text
User query
  -> follow-up resolver
  -> standalone query
  -> metadata filters
  -> dense retrieval
  -> lexical/sparse retrieval
  -> merge/deduplicate
  -> rerank
  -> parent/neighbor expansion
  -> evidence pack
  -> generation
  -> citation validation
```

## 7.2. Follow-up resolver

Câu hỏi nối tiếp phải được rewrite thành standalone query nhưng vẫn giữ original query.

Ví dụ:

```text
Turn trước: “So sánh cấu hình A và B trong file.”
Turn sau: “Cái thứ hai tốn bao nhiêu RAM?”

Standalone retrieval query:
“Trong tài liệu đang active, cấu hình B tốn bao nhiêu RAM?”
```

Không dùng query rewrite để thay đổi ý user. Lưu cả:

- original query;
- rewritten query;
- entities resolved;
- confidence.

## 7.3. Hybrid retrieval

Không chỉ dùng vector similarity.

Tối thiểu:

- dense multilingual retrieval;
- lexical/BM25 hoặc sparse retrieval;
- metadata filtering;
- weighted fusion như Reciprocal Rank Fusion;
- reranker.

Embedding baseline nên benchmark:

- `BAAI/bge-m3` cho multilingual/Vietnamese;
- model embedding hiện tại của project;
- một lựa chọn NVIDIA/local khác nếu project đã dùng.

Không đổi embedding model trực tiếp ở production. Phải re-index vào collection/version mới rồi A/B test.

## 7.4. Reranker

Baseline nên benchmark:

- `BAAI/bge-reranker-v2-m3`;
- reranker hiện tại nếu có.

Quy trình gợi ý:

```text
dense top 40
lexical top 40
merge top ~60
rerank top 20–30
select evidence top 6–12
expand parent/neighbors khi cần
```

Các con số phải tune theo eval, không hard-code không kiểm chứng.

## 7.5. Chunking

Dùng hierarchical parent-child chunks.

### Child chunk

- dùng để retrieval;
- khoảng 300–700 tokens với prose;
- overlap 10–20%;
- không cắt giữa table row, code symbol hoặc list quan trọng.

### Parent chunk

- dùng làm context sau khi child được chọn;
- khoảng 1,000–2,500 tokens;
- giữ heading/section;
- có thể mở rộng chunk trước/sau.

Với code:

- chunk theo symbol;
- parent là class/module;
- giữ line range.

Với bảng:

- lặp lại header ở mỗi chunk;
- giữ sheet/page;
- serialize dễ đọc;
- không tách row khỏi header.

## 7.6. Evidence pack

Model chỉ nhận evidence đã chuẩn hóa:

```xml
<evidence id="DOC1-C42"
          document_id="DOC1"
          filename="architecture.pdf"
          page="18"
          section="Memory Layer">
Exact retrieved text...
</evidence>
```

Yêu cầu:

- stable evidence ID;
- exact source text;
- metadata verified;
- retrieval/rerank score không nhất thiết gửi cho model;
- không gửi URL không xác thực;
- mỗi evidence có document version.

## 7.7. Query decomposition

Với câu hỏi nhiều phần:

1. tách sub-question;
2. retrieve riêng;
3. merge evidence;
4. trả lời theo từng phần;
5. kiểm tra coverage.

Chỉ dùng khi query thực sự compound để tránh tăng latency.

## 7.8. Insufficient evidence behavior

Nếu evidence không đủ:

- nêu rõ phần tìm thấy;
- nêu phần không tìm thấy;
- không gắn citation vào claim không được hỗ trợ;
- không dùng kiến thức nền như thể lấy từ file;
- có thể trả lời kiến thức chung nhưng phải tách rõ “ngoài tài liệu”.

---

# 8. Phase 6 — Citation không hallucination

## 8.1. Citation contract

Model không được sinh Markdown URL trực tiếp.

Model chỉ được xuất citation token theo stable evidence ID:

```text
[CITE:DOC1-C42]
```

Backend render thành:

```text
[architecture.pdf, p.18]
```

hoặc UI citation card tương ứng.

## 8.2. Structured generation

Response schema nội bộ gợi ý:

```json
{
  "answer_markdown": "... [CITE:DOC1-C42]",
  "claims": [
    {
      "text": "...",
      "citation_ids": ["DOC1-C42"]
    }
  ],
  "insufficient_evidence": false
}
```

Nếu runtime/schema làm giảm chất lượng đáng kể, có thể dùng text protocol nhưng vẫn phải parse và validate.

## 8.3. Validator bắt buộc

Sau generation:

1. extract citation IDs;
2. kiểm tra ID tồn tại trong evidence pack;
3. kiểm tra document/version còn active;
4. kiểm tra page/sheet/line metadata;
5. phát hiện citation không gắn với claim;
6. phát hiện claim cần citation nhưng thiếu;
7. chạy support verifier cho claim–evidence quan trọng;
8. nếu fail:
   - sửa deterministic nếu chỉ sai format;
   - regenerate phần lỗi với evidence giới hạn;
   - hoặc loại claim không đủ support;
   - tuyệt đối không render source giả.

## 8.4. Citation support verifier

Triển khai theo hai tầng:

### Tầng deterministic

- ID validity;
- metadata validity;
- exact source availability;
- duplicate citation;
- forbidden raw URL;
- page range.

### Tầng semantic

- claim có được evidence hỗ trợ không;
- evidence có mâu thuẫn không;
- claim có overstate so với source không.

Semantic verifier có thể dùng model local, nhưng phải:

- chạy temperature 0;
- output schema rõ;
- chỉ verify, không rewrite fact;
- cache kết quả;
- ưu tiên verify claim rủi ro cao.

## 8.5. Citation UI

Khi click citation:

- mở đúng document;
- highlight chunk;
- hiển thị page/slide/sheet/line;
- hiển thị excerpt;
- version đúng;
- không chỉ mở đầu file.

---

# 9. Phase 7 — Prompt architecture

## 9.1. Không dùng một system prompt khổng lồ

Tách prompt thành module:

- identity/behavior;
- answer-depth policy;
- memory policy;
- RAG grounding policy;
- citation contract;
- tool policy;
- output format.

Ghép module theo request type để giảm noise và tăng cache hit.

## 9.2. Thứ tự context đề xuất

```text
1. System behavior + reasoning signal
2. Grounding/citation rules
3. Conversation summary
4. Relevant long-term memories
5. Recent exact turns
6. Active document state
7. Retrieved evidence
8. Current user request
9. Output requirements
```

Nếu framework yêu cầu current request là user message cuối cùng, evidence có thể được đặt trong cùng user message theo section rõ ràng.

## 9.3. Core behavior prompt

Prompt phải thể hiện các quy tắc:

- trả lời đúng câu hỏi hiện tại;
- sử dụng lịch sử để resolve references;
- không nói “không có context” khi context đã được cung cấp;
- ưu tiên evidence từ file;
- không bịa citation;
- nêu uncertainty;
- trả lời đủ chi tiết theo `response_depth`;
- không tự ý rút gọn;
- không lặp lại reasoning trace cho user nếu UI chỉ cần final answer;
- kiểm tra tất cả phần của yêu cầu đã được trả lời trước khi kết thúc.

## 9.4. Completeness checklist trước khi kết thúc

Yêu cầu model tự kiểm tra ở mức internal:

- đã trả lời mọi sub-question chưa;
- có assumption nào cần nói rõ không;
- claim từ file đã có citation chưa;
- có contradiction giữa các nguồn không;
- output có bị dở câu không;
- có bước thực thi cụ thể không.

Không cần hiển thị checklist này cho user.

---

# 10. Phase 8 — Tối ưu latency mà không giảm chất lượng

## 10.1. Streaming

- backend stream ngay khi model trả token;
- frontend render incremental;
- citation placeholder có thể resolve sau;
- không chờ toàn bộ semantic validation nếu có thể validate theo claim/chunk, nhưng final UI phải đánh dấu trạng thái chưa xác thực nếu hiển thị sớm.

## 10.2. Model warm-up

Khi service start:

- load model;
- chạy warm-up prompt;
- kiểm tra health;
- chỉ nhận traffic sau khi ready;
- tránh unload/reload giữa các request;
- có readiness/liveness probe.

## 10.3. Chunked prefill

Bật khi runtime hỗ trợ ổn định. Benchmark:

- prompt 2K;
- 16K;
- 32K;
- 64K;
- concurrent decode.

Mục tiêu là giảm việc prompt dài chặn request decode đang chạy.

## 10.4. Prefix caching

Bật automatic prefix caching nếu version/runtime hỗ trợ đúng hybrid Mamba/attention của Nemotron.

Để tăng cache hit:

- giữ system prompt ổn định;
- đặt phần cố định trước;
- đặt dynamic evidence/current query sau;
- không thêm timestamp/random ID vào đầu prompt;
- benchmark correctness và hit rate.

Không bật nếu runtime version có bug với model này.

## 10.5. Parallel retrieval

Các bước có thể song song:

- dense search và lexical search;
- memory retrieval và document retrieval;
- parse metadata fetch và embedding query;
- rerank batches.

Cần cancellation khi user hủy request.

## 10.6. Cache

Cache theo content hash/version:

- parsed document;
- OCR page;
- normalized blocks;
- embeddings;
- lexical index;
- query embedding;
- retrieval result ngắn hạn;
- rerank result ngắn hạn;
- claim–citation verification;
- conversation summary version.

Không cache final answer nếu context/user/memory khác nhau trừ khi cache key đầy đủ.

## 10.7. Dynamic retrieval depth

- câu direct lookup: ít chunks;
- câu synthesis: nhiều chunks;
- câu hỏi toàn tài liệu: map-reduce/hierarchical retrieval;
- tránh luôn luôn retrieve top 50 rồi đưa hết vào prompt.

## 10.8. Resource isolation

Trên unified memory:

- theo dõi tổng memory của model, parser, OCR, embeddings, reranker và vector DB;
- đặt concurrency limit riêng;
- tránh ingestion lớn làm inference bị swap/thrash;
- queue OCR/indexing;
- cho inference ưu tiên cao hơn background ingestion;
- không giảm model precision chỉ vì background worker chiếm memory.

---

# 11. Phase 9 — Đọc file rất dài

Với file vượt context window hoặc câu hỏi yêu cầu hiểu toàn bộ tài liệu, không chỉ dùng top-k RAG.

## 11.1. Hierarchical document index

Tạo:

- document summary;
- section summaries;
- section chunks;
- raw blocks.

Mỗi summary phải có source block IDs.

## 11.2. Query strategy

### Local question

Retrieve child chunks + parent expansion.

### Broad synthesis

1. retrieve relevant sections;
2. lấy section summaries;
3. deep retrieval trong mỗi section;
4. tổng hợp với citation;
5. verify coverage.

### “Tóm tắt toàn bộ file”

1. summarize mỗi section;
2. merge summaries theo hierarchy;
3. giữ important facts/tables/decisions;
4. citation theo section;
5. không dùng một lần generation duy nhất với file cực dài nếu vượt budget.

## 11.3. Multi-file comparison

- retrieve mỗi file riêng để tránh một file áp đảo;
- set minimum evidence quota cho mỗi file;
- detect missing side;
- trả bảng so sánh;
- citation theo từng cell/claim khi cần.

---

# 12. Phase 10 — Evaluation suite

Tạo thư mục:

```text
evals/
  datasets/
  runners/
  scorers/
  reports/
```

## 12.1. Bộ test memory

Ít nhất 100 scenario, gồm:

- reference câu trước;
- reference 10–20 turn trước;
- đổi ý/ghi đè preference;
- pronoun/entity resolution;
- pending task;
- file đã upload;
- summary boundary;
- conversation reload sau restart;
- hai conversation không bị leak;
- hai user/workspace không bị leak.

Metric:

- exact fact recall;
- entity resolution;
- stale-memory error;
- cross-conversation leakage;
- summary drift.

## 12.2. Bộ test citation

Ít nhất 100 câu hỏi trên tài liệu có answer key:

- exact lookup;
- paraphrase;
- multi-hop trong cùng file;
- nhiều file;
- conflicting sources;
- no-answer;
- table lookup;
- page-specific;
- code line-specific.

Metric:

- citation ID validity: mục tiêu 100%;
- fabricated source rate: mục tiêu 0%;
- citation precision;
- citation recall/coverage;
- claim support;
- correct document/page;
- no-answer accuracy.

## 12.3. Bộ test file ingestion

Bao gồm:

- digital PDF;
- scanned PDF;
- two-column PDF;
- PDF có bảng;
- DOCX heading/table;
- PPTX text boxes/notes;
- XLSX nhiều sheet;
- CSV lớn;
- repository code;
- file tiếng Việt có dấu;
- file lỗi/empty/password-protected.

Metric:

- page/slide/sheet coverage;
- text extraction accuracy sample;
- table preservation;
- metadata accuracy;
- duplicate rate;
- parse warning correctness.

## 12.4. Bộ test answer quality

Rubric 1–5:

- correctness;
- completeness;
- relevance;
- structure;
- groundedness;
- uncertainty calibration;
- actionability;
- Vietnamese fluency;
- code correctness khi có code.

So sánh blind A/B giữa baseline và phiên bản mới.

## 12.5. Performance benchmark

Các profile:

```text
input: 2K / 8K / 16K / 32K / 64K
output: 256 / 1K / 4K
concurrency: 1 / 2 / 4 / 8
RAG: off / on
memory: short / long
```

Thu thập:

- p50/p95 TTFT;
- p50/p95 total latency;
- prefill throughput;
- decode throughput;
- retrieval/rerank time;
- GPU utilization;
- unified-memory usage;
- queue time;
- cache hit rate;
- timeout/error rate.

## 12.6. Acceptance gates

Không merge production nếu không đạt:

- citation ID validity = 100%;
- fabricated citation/source = 0 trong eval set;
- không có cross-user/cross-conversation memory leak;
- follow-up memory accuracy cải thiện rõ ràng so với baseline;
- answer completeness tăng mà correctness không giảm;
- parse coverage không giảm;
- không có truncation không được báo;
- p95 latency không xấu đi nghiêm trọng nếu quality gain nhỏ;
- mọi regression quan trọng đều có giải thích và quyết định rõ.

Đặt target số cụ thể sau khi có baseline. Ưu tiên relative target:

- giảm ít nhất 30% lỗi follow-up memory;
- giảm ít nhất 80% citation sai;
- tăng ít nhất 20% completeness score;
- cải thiện TTFT hoặc giữ nguyên trong khi context/evidence tăng;
- không giảm groundedness quá 1 điểm phần trăm.

---

# 13. Phase 11 — Fine-tuning chỉ khi cần

Chỉ thực hiện sau khi hoàn tất các phase trên.

## 13.1. Khi nào cần LoRA/SFT

Chỉ khi eval chứng minh model vẫn yếu ở:

- tiếng Việt chuyên ngành;
- format output cố định;
- style trả lời chi tiết;
- domain terminology;
- tool calling đặc thù;
- citation token protocol.

Không fine-tune để sửa:

- history không được gửi;
- retrieval sai;
- parser thiếu page;
- citation renderer bug;
- token cap thấp;
- prompt lỗi.

## 13.2. Dataset

Dataset phải có:

- tiếng Việt tự nhiên;
- câu hỏi nối tiếp;
- multi-turn context;
- answer đầy đủ;
- grounded answer;
- no-answer examples;
- citation ID đúng;
- hard negatives;
- domain data được phép sử dụng.

Tách train/dev/test theo document để tránh leakage.

## 13.3. Đánh giá sau fine-tune

So sánh:

- base BF16;
- base runtime optimized;
- LoRA;
- quantized LoRA nếu có.

Không deploy LoRA nếu:

- giảm general reasoning;
- tăng hallucination;
- citation precision giảm;
- làm output dài nhưng loãng;
- overfit style.

---

# 14. Data model và migration đề xuất

Agent phải điều chỉnh theo database hiện tại, không bắt buộc dùng tên bảng này.

## 14.1. Conversation

```text
conversations
messages
conversation_summaries
conversation_state
memory_items
```

## 14.2. Documents

```text
documents
document_versions
document_blocks
document_parse_reports
document_chunks
document_embeddings
```

## 14.3. Retrieval/citations

```text
retrieval_runs
retrieval_candidates
evidence_packs
response_claims
response_citations
citation_validation_runs
```

## 14.4. Evals/telemetry

```text
generation_runs
quality_feedback
eval_runs
```

Mọi record phải có tenant/workspace scope nếu ứng dụng có nhiều user.

---

# 15. API contract đề xuất

Điều chỉnh theo project hiện tại.

## 15.1. Chat request

```json
{
  "conversation_id": "...",
  "message": "...",
  "active_document_ids": ["..."],
  "response_depth": "detailed",
  "reasoning_mode": "adaptive",
  "stream": true
}
```

Frontend không cần gửi toàn bộ history nếu backend là source of truth.

## 15.2. Stream events

```text
response.started
retrieval.started
retrieval.completed
token.delta
citation.resolved
response.validation
response.completed
response.error
```

Không bắt buộc hiển thị toàn bộ event cho user, nhưng hữu ích cho tracing.

## 15.3. Final response

```json
{
  "message_id": "...",
  "answer_markdown": "...",
  "citations": [
    {
      "citation_id": "DOC1-C42",
      "document_id": "DOC1",
      "document_version": "...",
      "filename": "architecture.pdf",
      "page": 18,
      "section": "Memory Layer",
      "excerpt": "...",
      "verified": true
    }
  ],
  "usage": {
    "input_tokens": 0,
    "output_tokens": 0
  },
  "quality": {
    "citation_validation": "passed",
    "truncated": false
  }
}
```

---

# 16. Observability

## 16.1. Log fields

- request ID;
- conversation ID hash;
- user/workspace hash;
- model/runtime/profile;
- reasoning mode/budget;
- input/output tokens;
- context composition token counts;
- retrieved memory IDs;
- retrieved document chunk IDs;
- rerank scores;
- citation validation result;
- TTFT/total latency;
- cache hit;
- truncation reason;
- parser warnings.

Không log raw private file content mặc định.

## 16.2. Debug panel local/admin

Nên hiển thị:

- prompt token breakdown;
- memory selected;
- retrieval candidates;
- reranked evidence;
- final evidence pack;
- citation mapping;
- generation params;
- timing waterfall.

Panel này là công cụ quan trọng để tìm nguyên nhân “model ngu” thực sự nằm ở đâu.

---

# 17. Security và isolation

- filter retrieval theo tenant/workspace/user trước vector search hoặc bằng payload filter bắt buộc;
- conversation ID phải được authorize;
- document citation không được mở file user khác;
- xóa file phải xóa embeddings và cache;
- sanitize uploaded filename/path;
- giới hạn decompression/archive bombs;
- scanner cho file upload nếu project có môi trường nhiều user;
- không gửi code/file ra dịch vụ cloud khi chế độ local-only được bật;
- có audit log với thao tác memory/document.

---

# 18. Rollout strategy

## 18.1. Feature flags

Tối thiểu:

```text
ENABLE_NEW_MEMORY
ENABLE_HYBRID_RETRIEVAL
ENABLE_RERANKER
ENABLE_CITATION_VALIDATOR
ENABLE_DETAILED_RESPONSE_POLICY
ENABLE_ADAPTIVE_REASONING
ENABLE_NEW_INGESTION
ENABLE_PREFIX_CACHE
ENABLE_CHUNKED_PREFILL
```

## 18.2. Thứ tự rollout

1. observability;
2. history correctness;
3. token/output caps;
4. citation stable IDs;
5. citation validator;
6. hybrid retrieval;
7. reranker;
8. parser improvements;
9. rolling summary;
10. long-term memory;
11. adaptive reasoning;
12. performance optimizations;
13. optional fine-tune.

## 18.3. Rollback

Mỗi phase phải có:

- migration rollback hoặc forward-fix plan;
- flag disable;
- old index giữ trong thời gian A/B;
- old prompt profile;
- benchmark report.

---

# 19. Deliverables bắt buộc

Agent phải hoàn thành các file hoặc equivalent phù hợp với repository:

```text
docs/chatbot-quality-audit.md
docs/chatbot-architecture-before.md
docs/chatbot-architecture-after.md
docs/chatbot-quality-progress.md
docs/model-runtime-config.md
docs/memory-design.md
docs/rag-citation-design.md
docs/file-ingestion-design.md
docs/evaluation-methodology.md

evals/datasets/...
evals/runners/...
evals/scorers/...
artifacts/evals/baseline-*.json
artifacts/evals/final-*.json
```

Code deliverables:

- corrected prompt builder;
- token budget manager;
- conversation persistence/loader;
- rolling summary;
- semantic memory store/retriever;
- canonical document parser;
- parse quality report;
- hybrid retriever;
- reranker;
- evidence pack builder;
- citation renderer;
- citation validator;
- adaptive reasoning policy;
- streaming and tracing;
- tests;
- migrations;
- feature flags.

---

# 20. Definition of Done

Project chỉ được xem là hoàn tất khi:

- restart backend không làm mất conversation đã lưu;
- follow-up questions dùng đúng thông tin trước đó;
- user có thể hỏi lại về file đã upload;
- file parser báo rõ khi không đọc đủ;
- RAG dùng hybrid retrieval + reranking;
- model không được phép tự tạo nguồn;
- mọi citation render từ stable evidence ID;
- citation validator chặn nguồn giả;
- câu trả lời mặc định đủ chi tiết;
- output không bị cắt âm thầm;
- reasoning budget được chọn theo độ khó;
- runtime giữ `mamba_ssm_cache_dtype=float32`;
- có benchmark BF16 và profile optimized trên GB10;
- có dashboard/log để biết latency nằm ở parse, retrieval, prefill hay decode;
- eval suite chạy tự động;
- kết quả sau tốt hơn baseline theo acceptance gates;
- tài liệu và rollback đầy đủ.

---

# 21. Việc Agent phải làm ngay khi bắt đầu

Thực hiện đúng checklist này:

- [ ] Scan repository và dependency files.
- [ ] Tìm tất cả nơi gọi chat completion/model API.
- [ ] Tìm tất cả `max_tokens`, `max_new_tokens`, timeout và stop sequence.
- [ ] Xác nhận model checkpoint và chat template.
- [ ] Xác nhận reasoning signal `/think` hoặc `/no_think`.
- [ ] Xác nhận `mamba_ssm_cache_dtype=float32`.
- [ ] Trace conversation ID và history từ UI đến prompt.
- [ ] Trace upload từ file bytes đến chunks/index.
- [ ] Trace citation từ retrieval result đến UI.
- [ ] Tạo baseline eval.
- [ ] Viết audit report.
- [ ] Sửa history/token truncation trước.
- [ ] Sửa citation contract và validator.
- [ ] Nâng retrieval/chunking/parser.
- [ ] Bổ sung summary + long-term memory.
- [ ] Tune generation và reasoning.
- [ ] Tối ưu latency.
- [ ] Chạy full regression.
- [ ] Viết final report với before/after metrics.

---

# 22. Ghi chú kỹ thuật về Nemotron Nano 9B v2

Các điểm Agent phải giữ đúng:

1. Model là hybrid Mamba2–Transformer và hỗ trợ context tối đa 128K.
2. Với vLLM, phải giữ Mamba SSM cache ở `float32` để tránh suy giảm chất lượng.
3. Model mặc định reasoning on nếu không có `/no_think`.
4. NVIDIA khuyến nghị cho reasoning mode:
   - `temperature=0.6`;
   - `top_p=0.95`;
   - `max_new_tokens >= 1024`.
5. Non-reasoning có thể dùng greedy.
6. Reasoning trace thường tăng chất lượng với prompt khó nhưng tăng latency; vì vậy phải dùng budget adaptive.
7. DGX Spark có NIM riêng cho Nemotron Nano 9B v2 với profile NVFP4 throughput; phải benchmark chất lượng với BF16 trước khi chọn default.
8. Model card không liệt kê tiếng Việt trong nhóm ngôn ngữ use-case chính, nên eval tiếng Việt là bắt buộc. Những lỗi tiếng Việt còn lại sau khi sửa system layer có thể cần domain SFT/LoRA hoặc đổi generator model ở phase sau.

---

# 23. Nguồn tham khảo chính

- NVIDIA model card — NVIDIA-Nemotron-Nano-9B-v2:  
  https://huggingface.co/nvidia/NVIDIA-Nemotron-Nano-9B-v2
- NVIDIA NIM model card:  
  https://build.nvidia.com/nvidia/nvidia-nemotron-nano-9b-v2/modelcard
- NVIDIA NIM supported models / DGX Spark profile:  
  https://docs.nvidia.com/nim/large-language-models/1.15.0/supported-models.html
- vLLM optimization and chunked prefill:  
  https://docs.vllm.ai/en/stable/configuration/optimization/
- vLLM automatic prefix caching:  
  https://docs.vllm.ai/en/latest/features/automatic_prefix_caching/
- BGE-M3 multilingual embedding model:  
  https://huggingface.co/BAAI/bge-m3
- BGE reranker v2 M3:  
  https://huggingface.co/BAAI/bge-reranker-v2-m3
