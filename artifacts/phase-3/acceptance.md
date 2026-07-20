# Phase 3 acceptance evidence

- Phạm vi: Phase 3 — NIM Model Bake-off
- Master plan: `NTC_NVIDIA_LOCAL_RAG_CHATBOT_MASTER_PLAN.md`
- Run chuẩn: `artifacts/phase-3/runs/20260714T1120Z-full-r2`
- Targeted metadata correction: `artifacts/phase-3/runs/20260714T1330Z-retriever-metadata-r1`
- Kết quả run lịch sử: **BLOCKED**, workflow exit code `3`
- Quyết định bổ sung ngày 2026-07-15: **Nemotron Nano 9B v2 được chọn làm
  LLM chính cho local engineering**, có performance deviation
- Decision artifact: `artifacts/phase-3/decisions/20260715T0218Z-nemotron-local-winner/decision.json`
- Corporate legal approval: **pending**
- Phase 4: **đã chạy E2E và có acceptance riêng**
- Phase 5 downstream decision: **Embed 300M đã được chọn/activate cho local
  engineering với explicit BGE-M3 waiver**

Run chuẩn hoàn tất toàn bộ workload khả dụng và cleanup, nhưng không được đổi
ngược thành PASS: tại thời điểm tạo run, BGE-M3 chưa có exact runtime vì
authenticated NGC scope probe trả HTTP `402`, embedding winner chưa thể chọn,
và LLM human review/legal approval đều `pending`. Run và scorecard lịch sử vẫn
giữ nguyên. Quyết định mới là artifact append-only theo chỉ thị rõ ràng của
workspace operator; nó chốt DG-02 cho local engineering nhưng không thay thế
phê duyệt pháp lý của công ty. Phase 5 sau đó chốt DG-03 trong downstream
retrieval decision; các dòng về BGE-M3 bên dưới vẫn ghi rõ phần comparison không
được chạy, thay vì biến waiver thành bằng chứng giả.

## Đối chiếu acceptance criteria

| Acceptance Phase 3 | Kết quả và evidence |
|---|---|
| Mỗi model có health, sample request và report | **LOCAL PASS WITH EXPLICIT WAIVER** — Llama, Nemotron, Embed 300M và Rerank 500M đều có exact runtime health/sample/report pass; BGE-M3 không được dùng và không được claim đã chạy vì HTTP 402 |
| LLM winner hỗ trợ context requirement hoặc có bằng chứng cấu hình | **PASS cho local engineering / LEGAL PENDING cho production** — decision addendum chọn exact `nvidia/nemotron-nano-9b-v2`; live 32K/64K/128K và runtime max `131072` đều pass; corporate legal approval chưa có |
| Tốc độ được báo đúng định nghĩa | **PASS** — direct NIM client-observed TTFT proxy, decode tokens/s và total HTTP latency được tách riêng; mỗi scenario có 20 measured + 2 warmup, concurrency và p50/p95; không gọi proxy này là exact backend TTFT hay application E2E |
| Embedding winner dưới 1B | **PASS cho local engineering với explicit waiver** — Phase 5 decision chọn/activate Embed 300M (khoảng 569M parameter, dimension `2048`) trên corpus thật; same-gold BGE-M3 comparison vẫn không được claim |
| Không OOM trong service combination mục tiêu | **PASS** — cả `Llama + Embed + Rerank` và `Nemotron + Embed + Rerank` pass đủ 7 check: no-OOM, load, restart, health, telemetry, clean logs và cleanup |
| Model/license được ghi | **LOCAL PASS / CORPORATE REVIEW PENDING** — exact selected NVIDIA artifacts có image/digest/profile/version và terms evidence; không dùng hay claim BGE-M3 artifact |

## LLM workload và số liệu live

Mỗi candidate chạy đúng sáu scenario. Mỗi scenario có 2 warmup rồi 20 measured
request. Synthetic benchmark cố định `ignore_eos=true` để mọi response đạt đúng
output-token target; control này không dùng cho smoke/quality. Mỗi request LLM
có deterministic SHA-256 nonce ở dòng đầu user content, tách namespace warmup
và measured, nên full prompt không bị dùng lại qua prefix cache. Nonce, prompt
và reasoning content không được persist.

Các số dưới đây đều là p50/p95 của run chuẩn:

| Candidate / scenario | TTFT proxy (s) | Decode (tok/s) | Direct NIM total (s) |
|---|---:|---:|---:|
| Llama short c1 | 0.079 / 0.084 | 25.05 / 25.17 | 10.30 / 10.32 |
| Llama RAG 8K c1 | 1.251 / 1.254 | 22.63 / 22.65 | 23.87 / 23.89 |
| Llama RAG 8K c4 | 1.952 / 3.798 | 16.29 / 17.13 | 33.36 / 35.24 |
| Llama 32K c1 | 7.840 / 7.853 | 17.75 / 17.77 | 11.45 / 11.46 |
| Llama 64K c1 | 23.794 / 23.822 | 13.56 / 13.60 | 28.51 / 28.55 |
| Llama 128K c1 | 80.841 / 80.954 | 9.24 / 9.29 | 87.78 / 87.86 |
| Nemotron short c1 | 0.135 / 0.215 | 26.95 / 26.99 | 9.63 / 9.72 |
| Nemotron RAG 8K c1 | 1.991 / 2.017 | 26.49 / 26.55 | 21.32 / 21.36 |
| Nemotron RAG 8K c4 | 2.921 / 7.270 | 19.61 / 22.40 | 28.98 / 33.39 |
| Nemotron 32K c1 | 8.144 / 8.192 | 25.44 / 25.49 | 10.66 / 10.71 |
| Nemotron 64K c1 | 17.537 / 17.740 | 23.99 / 24.03 | 20.21 / 20.41 |
| Nemotron 128K c1 | 40.312 / 41.161 | 21.59 / 21.64 | 43.27 / 44.15 |

`TTFT proxy` bắt đầu ngay trước HTTP request dispatch và kết thúc ở first
non-empty generated-token delta; đây là upper-bound proxy của backend TTFT.
`Decode` dùng response-reported completion tokens chia cho khoảng first-to-last
generated-token delta. `Direct NIM total` không bao gồm auth/retrieval/rerank và
không phải application E2E. Không candidate nào đạt 40–50 decode tok/s trong
workload này; Phase 10 phải giữ số thật và thực hiện bottleneck analysis thay vì
đổi định nghĩa hoặc làm đẹp số.

Long-context absolute gate pass cho cả hai:

- Llama 128K: observed prompt + max output từ `130827` tới `130838` token;
- Nemotron 128K: từ `130826` tới `130832` token;
- cả hai nằm trong gate `[130560, 131072]`, output luôn đúng 64 token, không
  retry/downshift context.

## Quality và quyết định LLM

Cả hai model pass 10/10 automatic hard-gate case cho request success,
answerable/refusal, unanswerable exact refusal và prompt-injection forbidden
output. Automated score vẫn chỉ là provisional:

| Candidate | Correctness VI/EN | Faithfulness/citation | Instruction | Provisional total | Trạng thái hiện tại |
|---|---:|---:|---:|---:|---|
| Llama | 0.95 | 0.7375 | 1.00 | 0.90796 | Comparator; không được chọn |
| Nemotron | 0.95 | 0.95 | 1.00 | 0.93183 | **Local engineering winner**; legal pending |

Llama còn câu multi-section thiếu ý/citation; Nemotron còn một English
multi-section case đạt 0.5 correctness/alignment. Vì cả hai đã pass automatic
multilingual hard gate, conditional multilingual challenger chưa được kích
hoạt. Canonical scorecard vẫn ghi `not_selected`, đúng với trạng thái tại thời
điểm chạy. Artifact append-only ngày 2026-07-15 sau đó chọn Nemotron theo chỉ
thị operator; không sửa ngược scorecard và không tuyên bố legal approval.

Exact local binding:

- model `nvidia/nemotron-nano-9b-v2`, NIM `1.0.0`;
- image digest
  `sha256:82028e38ab950edd32f5053ca2030ee14d965e8fd4fe1c6e06468eb0be07a9a4`;
- profile `f9db61d5a467d46be7733e90a26705798764b93d480c842143d525c1932b01e2`;
- precision `NVFP4`, maximum model length `131072`;
- Fast dùng trusted `/no_think`, Reasoning dùng trusted `/think`; không trả raw
  chain-of-thought.

## Embed, rerank và target combinations

- Embed 300M: exact NIM `1.13.0`, ONNX-FP16 profile `e28…`, dimension `2048`;
  batch 1 và 16 đều pass 20+2 request. Basic Vietnamese semantic sanity có
  positive cosine `0.5663` lớn hơn negative `0.2832`.
- Rerank 500M: catalog tag `1.1`, runtime NIM `1.10.0`, ONNX-FP16 profile
  `f739…`, max length `4096`; passages 2 và 16 đều pass 20+2 request và semantic
  ordering.
- BGE-M3: live authenticated scope `repository:nim/baai/bge-m3:pull` trả HTTP
  `402`; exact pin, license, health và comparison report không tồn tại.
- Hai target combinations đều chạy concurrent smoke và bounded concurrent load
  gồm RAG 8K c4; tất cả container `healthy`, `RestartCount=0`,
  `OOMKilled=false`, log scan và telemetry pass.

Retrieval reports trong parent run có một lỗi metadata không ảnh hưởng request:
LLM-only prompt uniqueness control bị ghi `enabled` cho Embed/Rerank dù không
được áp dụng. Generator đã sửa thành `not_applicable`, có regression test, và
targeted correction run đã live-pass lại đủ 20+2 request cho cả hai. Correction
run chạy hai retriever đồng thời nên không thay latency scorecard của parent.

## Debug closure

- Loại bỏ full run `20260714T1000Z-full-r1` khỏi so sánh: prompt lặp lại cho
  phép Llama prefix-cache reuse trong khi Nemotron tắt prefix caching, làm lệch
  TTFT. Full-r2 dùng unique nonce trước shared context và là run performance hợp
  lệ duy nhất.
- Cố định synthetic output comparability bằng exact completion-token gate cho
  cả warmup/measured; sửa Nemotron reasoning control để không dừng sớm.
- Bắt buộc exact six-scenario matrix, 20 measured + 2 warmup, absolute long
  context token gate, exact runtime identity/license binding và metric scope.
- Scorecard fail-closed khi thiếu scenario/count/check, cross-bind sai candidate
  hoặc runtime repository, và không tự chọn winner.
- Cleanup fail-closed, giữ bốn cache volume, xác nhận 0 project container; exact
  secret scan không persist matched path/value.
- Sửa report thành công của retriever để LLM-only uniqueness control được đánh
  dấu `not_applicable`; failure report đã có semantics đúng từ trước.

## Quality gates cuối

```text
make check
  PASS — lock/package compatibility và source secret scan
  PASS — Ruff, ESLint, Bash syntax, ShellCheck, formatting
  PASS — mypy và TypeScript typecheck
  PASS — 195 pytest và 2 Vitest
  PASS — Next.js production build và Phase 1 smoke

make phase3-config
  PASS — private topology, egress isolation và immutable image pins

./scripts/phase3-images.sh check all
  PASS — mọi reviewed Phase 3 image manifest có local linux/arm64 variant

PHASE3_RUN_ID=20260714T1120Z-full-r2 ./scripts/smoke-phase3.sh
  BLOCKED (exit 3) — expected BGE-M3 HTTP 402 + winners pending;
  all available candidate, workload, combination, cleanup and secret gates pass
```

## Boundary audit và trạng thái hiện tại

- Canonical run Phase 3 không triển khai ingestion, index hoặc RAG graph; boundary
  đó vẫn đúng cho chính run này.
- Quyết định bổ sung chỉ chọn LLM local, không chọn embedding/reranker, không đổi
  Qdrant alias và không tự hoàn thành Phase 6.
- Performance target 40–50+ tok/s **chưa đạt**: Nemotron p50 là `26.95 tok/s`
  ở short c1 và `26.49 tok/s` ở RAG-8K c1. Operator chấp nhận deviation để chạy
  local Phase 6; Phase 10 vẫn phải phân tích bottleneck và không được đổi cách
  gọi metric.
- Legal/compliance cho production vẫn là hard gate độc lập.

Kết luận hiện tại: Phase 3 có **LLM winner cho local engineering**, còn trạng
thái production/legal chưa được chốt. Canonical run BLOCKED và decision addendum
đều được giữ song song để không làm mất lịch sử audit.
