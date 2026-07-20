# Phase 3 NIM model bake-off

- Trạng thái tài liệu: source run là historical **BLOCKED** snapshot; current
  local-engineering decisions đã có addendum
- Ngày kiểm chứng: 2026-07-14
- Decision gates: DG-02, DG-03, DG-04, DG-05
- Phạm vi: chỉ Phase 3; không bao gồm ingestion, indexing hoặc retrieval của
  Phase 4/5 trong source run; các addendum chỉ liên kết quyết định sau

> Current-state addendum (2026-07-15): artifact
> `20260714T1120Z-full-r2` không bị sửa ngược và vẫn ghi đúng trạng thái tại thời
> điểm chạy. Sau đó operator chọn exact `nvidia/nemotron-nano-9b-v2` làm LLM
> chính bằng [ADR 0007](../adr/0007-nemotron-nano-9b-v2-local-engineering-winner.md).
> Phase 5 dùng corpus Phase 4 thật, chốt Embed 300M và activate
> `ntc_chunks_active`; BGE-M3 comparison được explicitly waived vì HTTP 402.
> Corporate legal review và throughput target vẫn là release follow-up.

## Mục tiêu và kết luận hiện tại

Phase 3 thêm một topology NIM riêng để stage model asset, chạy inference smoke,
benchmark LLM/embedding/reranking và thu evidence trước khi activate model cho
ứng dụng. Image, adapter và benchmark tooling đã có; bốn image NVIDIA pin đã
được kiểm tra trên Linux ARM64 và model cache đã được tải.

Run chuẩn `20260714T1120Z-full-r2` đã hoàn tất smoke, exact runtime/license
verification, quality, full 20+2 benchmark, 32K/64K/128K và cả hai tổ hợp
no-OOM cho bốn candidate khả dụng. Bản thân source run vẫn là **BLOCKED**:
BGE-M3 chưa thể stage vì authenticated registry scope probe cho
`nim/baai/bge-m3:pull` trả HTTP 402; human/legal review cũng chưa cho phép chọn
LLM winner ở thời điểm đó. Không dùng mutable `latest`, candidate thay thế hoặc
dữ liệu giả để bỏ qua hard gate. Các quyết định sau run được lưu append-only,
không đổi report gốc. Evidence tổng hợp nằm tại
[`artifacts/phase-3/acceptance.md`](../../artifacts/phase-3/acceptance.md).

## Topology và lifecycle

Phase 3 dùng `compose.phase3.yaml` và project mặc định `ntc-rag-phase3`, tách
khỏi stack Phase 2:

```text
temporary staging network (egress)
  +-- stage-nim-llm-llama       --> nim_llama_cache
  +-- stage-nim-llm-nemotron    --> nim_nemotron_cache
  +-- stage-nim-embedding-300m  --> nim_embed_300m_cache
  +-- stage-nim-reranking-500m  --> nim_rerank_500m_cache

private runtime network (internal: true, no host port)
  +-- nim-llm-llama       --> verified Llama cache
  +-- nim-llm-nemotron    --> verified Nemotron cache
  +-- nim-embedding-300m  --> verified embedding cache
  +-- nim-reranking-500m  --> verified reranking cache
```

Staging container nhận NGC credential qua Docker secret file và chỉ tồn tại tới
khi readiness cùng exact served model ID được quan sát. Runtime container không
mount credential, không có egress network và không publish port. Named volumes
giữ model asset qua container recreation; `make phase3-down` không xóa cache.

Wrapper `infra/nim/entrypoint.sh` không cho runtime dùng một cache chỉ vì thư mục
không rỗng. Marker phải khớp cache key, NIM version dự kiến, model ID dự kiến,
model ID thực thấy từ `GET /v1/models` và ARM64 digest. Marker cũ hoặc sai pin bị
từ chối; operator phải stage lại đúng candidate.

## Immutable image và model inventory

Các pin dưới đây đến từ `infra/compose/phase3.env`. “Image digest” và “ARM64
manifest” là hai trường riêng đối với multi-arch OCI index.

| Role | Exact image pin | Linux ARM64 manifest | In-image NIM / served model ID | Model terms |
|---|---|---|---|---|
| LLM baseline | `nvcr.io/nim/meta/llama-3.1-8b-instruct:2.0.6@sha256:31e360dbb15f825d69e5d68c2032e334301523b4957091270385ed7ef3db5e81` | `sha256:249dcac461f20bc29ddb0924bf0c30e0e3f646c26bd849d978996cbe30b4d06e` | NIM `2.0.6`; `meta/llama-3.1-8b-instruct` | NVIDIA Open Model License terms plus Llama 3.1 Community License; NIM container terms are separate |
| LLM candidate | `nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2-dgx-spark:1.0.0-variant@sha256:82028e38ab950edd32f5053ca2030ee14d965e8fd4fe1c6e06468eb0be07a9a4` | same single-platform digest | NIM `1.0.0`; `nvidia/nemotron-nano-9b-v2` | NVIDIA Open Model License Agreement; NIM container is governed by NVIDIA software/product-specific terms |
| Embedding baseline | `nvcr.io/nim/nvidia/llama-nemotron-embed-300m-v2:1.13.0@sha256:1f0a7fc168919d7b84bb4edfb4a4da0c5828d11ee284f9fb8113242b3b35cbb4` | `sha256:5f8274faf21418cd894eb073d2c520923cce61a750c173b3745aedd1bb7efa49` | NIM `1.13.0`; `nvidia/llama-nemotron-embed-300m-v2` | NVIDIA Open Model License; additional Llama 3.2 Community License information applies |
| Reranking baseline | `nvcr.io/nim/nvidia/llama-nemotron-rerank-500m-v2:1.1@sha256:3e39d44bdb3dd683d6a2ac8d7689b484aee6c18dc7e00c2064f19501742720f3` | `sha256:6a598c5e6e7620c542f2101e24e34f3461e650a5b751200df56d52bf9f9444a9` | catalog tag `1.1`, in-image/runtime NIM `1.10.0`; `nvidia/llama-nemotron-rerank-500m-v2` | NVIDIA Community Model License; NIM container is governed by NVIDIA software/product-specific terms |
| Embedding challenger | Chưa chọn exact image/tag/digest | Chưa có | model target `baai/bge-m3` | Chưa chụp terms cho một exact container vì access gate chưa qua |

License là acceptance field, không phải kết luận pháp lý. Người vận hành vẫn
phải review toàn bộ governing terms của exact artifact trước khi dùng trong môi
trường công ty.

## Runtime evidence đã quan sát

| Candidate | Runtime observation trên GB10 | Ý nghĩa và phần chưa chứng minh |
|---|---|---|
| Nemotron Nano 9B v2 | Exact served-ID/runtime verification pass; profile `f9db61d5a467d46be7733e90a26705798764b93d480c842143d525c1932b01e2`, backend vLLM, NVFP4, TP1/PP1, runtime max `131072` | Full benchmark/context pass; **selected for local engineering after this run**; corporate legal pending |
| Llama 3.1 8B | Exact cache marker đã refresh `2026-07-14T07:37:05Z`; active FP8 profile `c4789f7af56c770c1c88b73da666886365534d6980b6b922b41fd97036c77d73` được runtime verifier cross-bind với image/model/license | Full benchmark/context pass; not selected after operator review |
| Embed 300M v2 | Exact served-ID, NIM `1.13.0`, profile `e28f17c9c13a99055d065f88d725bf93c23b3aab14acd68f16323de1353fc528`, Triton/ONNX FP16 GPU; dimension `2048`; batch 1/16 và semantic sanity pass | Khoảng 569M total parameter đáp ứng dưới 1B; **selected/activated in Phase 5** with explicit BGE-M3 waiver |
| Rerank 500M v2 | Exact served-ID, runtime NIM `1.10.0`, profile `f7391ddbcb95b2406853526b8e489fedf20083a2420563ca3e65358ff417b10f`, Triton/ONNX FP16 GPU; passages 2/16 và semantic sanity pass | Runtime max 4096 được ưu tiên hơn claim 8192 của profile khác; catalog tag `1.1` không phải NIM version 1.1 |
| BGE-M3 | Authenticated registry scope probe trả HTTP `402` | Entitlement/payment block xảy ra trước exact immutable image selection; không có health/sample/report hợp lệ |

Sau live verification, `infra/compose/phase3.env` ghi Nemotron runtime state là
`verified-live-nim-1-0-0-ready-models-context-131072`; state cũ chỉ dựa trên
image label không còn được dùng.

NVIDIA support matrix từng tạo nghi vấn x86-versus-ARM64 và optimized kernel
trên GB10. Việc pinned Embed/Rerank ARM64 image thực sự load GPU là runtime
evidence quan trọng, nhưng không tự thay đổi tuyên bố vendor support. Mọi khác
biệt giữa catalog tag, NIM version, profile và runtime limit phải tiếp tục được
ghi riêng.

GB10 dùng unified memory nên `nvidia-smi` có thể trả N/A cho tổng/used GPU
memory. Báo cáo không được đổi N/A thành 0 hoặc một số ước lượng. Acceptance
phải kết hợp host `free`, container stats, GPU utilization/temperature/power và
`OOMKilled`/exit status để kết luận no-OOM.

## Application adapter boundary

Business code gọi ba typed ports, không gọi URL NIM rải rác:

- `NimLlmClient`: OpenAI-compatible chat completion, hỗ trợ stream, kiểm tra
  model/version metadata và không replay stream sau khi đã phát token;
- `NimEmbeddingClient`: `input_type`, truncate policy, exact dimension, bounded
  batch và tự downshift batch khi NIM báo OOM;
- `NimRerankClient`: giữ source index, kiểm tra đủ result, finite score và thứ
  tự score giảm dần.

Typed settings chỉ tạo client trio khi operator bật explicit gate và cung cấp đủ
base URL `/v1`, model, model version, embedding dimension, timeout/retry/batch.
URL chứa credential hoặc cấu hình nửa vời bị từ chối. Retry chỉ áp dụng lỗi
transient với exponential backoff có jitter và hard cap; OOM không bị che thành
retry vô hạn.

## Benchmark và quality contract

Master plan định nghĩa TTFT từ lúc backend nhận request tới token đầu tiên, và
end-to-end latency gồm cả auth, retrieval, rerank, prefill và decode. Runner
Phase 3 hiện không có timestamp bên trong backend nên phải ghi rõ deviation:

- `ttft_seconds` là client-observed proxy: timestamp ngay trước HTTP request
  dispatch tới **first non-empty generated-token delta** từ
  `delta.content` hoặc `delta.reasoning_content`. Reasoning delta chỉ được dùng
  làm timestamp, không được persist. Metric gồm transport, server queue/prefill,
  buffering và client parsing nên là upper-bound đối với backend-receive TTFT,
  không phải phép đo backend TTFT chính xác;
- `decode_tokens_per_second` là server-reported `completion_tokens` chia cho
  khoảng thời gian client quan sát từ first tới last non-empty generated-token
  delta thuộc một trong hai field trên;
- `total_latency_seconds` là direct NIM HTTP request-dispatch tới stream
  completion. Nó không phải application end-to-end latency của master plan;
- mỗi scenario vẫn phải ghi actual input/output tokens, warm state, concurrency,
  model, image, profile, precision và p50/p95.

Report phải giữ `master_backend_receive_ttft_measured=false`. Không được đổi tên
client proxy thành backend TTFT hoặc application end-to-end chỉ để kết luận đạt
performance gate.

Workload tối thiểu:

| Scenario | Input/output mục tiêu | Concurrency |
|---|---:|---:|
| Engine short | khoảng 512 / 256 tokens | 1 |
| RAG normal | khoảng 8K / 512 tokens | 1 và 4 |
| Long-context capability | 32K, 64K, 128K | 1 |

Sau warm-up, mỗi scenario chuẩn chạy 20–30 request. Scorecard LLM giữ trọng số
25% correctness Việt/Anh, 25% faithfulness/citation, 10% RAG instruction,
20% performance, 10% memory/concurrency và 10% operations/license. Automated
scoring chỉ là tín hiệu; injection/refusal/citation hard gate cùng operator
review phải được lưu rõ. Vì thế scorecard source run không tự ghi winner; lựa
chọn Nemotron nằm trong decision addendum riêng.

Synthetic LLM request dùng `ignore_eos=true` và exact output-token gate cho cả
warmup/measured để decode rate so sánh được. Mỗi request còn có deterministic
SHA-256 nonce ở dòng đầu user content, tách namespace warmup/measured và không
persist, nên một backend có prefix cache không được reuse toàn prompt trong khi
backend kia không có cache. Full run cũ `20260714T1000Z-full-r1` bị loại vì chưa
có control này; chỉ `full-r2` được dùng cho performance.

## Live result snapshot

| Candidate | Full engine matrix | 128K actual total-token range | Automatic quality | Target combination | Decision |
|---|---|---:|---|---|---|
| Llama FP8 | 6/6 scenario pass, 20+2 mỗi scenario | 130827–130838 | 10/10 hard gate pass | 7/7 runtime check pass | Not selected by later decision |
| Nemotron NVFP4 | 6/6 scenario pass, 20+2 mỗi scenario | 130826–130832 | 10/10 hard gate pass | 7/7 runtime check pass | **Later local-engineering winner** |
| Embed 300M | batch 1/16 pass, 20+2 | N/A | semantic sanity pass | pass trong cả hai combo | **Later Phase 5 winner/active index**; BGE waived |
| Rerank 500M | passages 2/16 pass, 20+2 | N/A | semantic sanity pass | pass trong cả hai combo | baseline only |

Nemotron có automatic score `0.93183`, Llama `0.90796`; các số này là input cho
decision addendum, không tự thân là quyết định. Không candidate nào đạt 40–50 decode tok/s trong workload
đã định nghĩa; số tuyệt đối và p50/p95 được giữ nguyên cho bottleneck analysis
Phase 10. Targeted correction run `20260714T1330Z-retriever-metadata-r1` sửa
metadata retriever: LLM-only uniqueness control phải là `not_applicable`, không
thay latency scorecard của parent run.

## Acceptance mapping hiện tại

| Master-plan acceptance | Trạng thái snapshot | Evidence còn thiếu để kết luận |
|---|---|---|
| Mỗi model có health, sample request và report | **Local pass with explicit waiver** | Bốn exact available candidates pass; unavailable BGE-M3 remains HTTP 402 and is not falsely claimed as run |
| LLM winner đáp ứng context hoặc có config evidence | **Local pass / legal pending** | Nemotron selected by append-only decision; actual 32K/64K/128K and runtime max 131072 pass |
| Tốc độ báo đúng định nghĩa | **Pass** | Full 20+2 report có TTFT proxy, decode, direct NIM total, p50/p95, token length, warm state và concurrency; không claim backend/E2E |
| Embedding winner dưới 1B | **Local pass with explicit waiver** | Embed 300M selected/activated in Phase 5; exact BGE-M3 comparison remains unavailable and waived |
| Không OOM trong tổ hợp mục tiêu | **Pass** | Cả hai LLM + Embed + Rerank combinations pass 7/7 health/load/restart/OOM/telemetry/log/cleanup check |
| Model/license được ghi | **Local pass / corporate review pending** | Selected exact NVIDIA pins have identity and terms recorded; no BGE artifact is used or claimed |

## Command contract

```bash
make phase3-secrets
make phase3-config
make phase3-images
make phase3-cache-llama
make phase3-cache-nemotron
make phase3-cache-retriever
make phase3-status
make phase3-acceptance
make phase3-down
```

`phase3-acceptance` là workflow GPU có mutation và có thể chạy lâu: nó start
NIM, gửi inference request và ghi artifacts. Workflow phải trả non-zero/blocked
khi hard gate BGE-M3 còn HTTP 402; việc các NVIDIA candidate khác healthy không
được đổi thành PASS toàn Phase 3.

## Nguồn chính thức

- [NIM LLM 2.0.6 quickstart](https://docs.nvidia.com/nim/large-language-models/2.0.6/get-started/quickstart.html)
- [NIM LLM benchmark request controls](https://docs.nvidia.com/nim/benchmarking/llm/latest/parameters.html)
- [Nemotron Nano 9B v2 DGX Spark catalog](https://catalog.ngc.nvidia.com/orgs/nim/nvidia/containers/nvidia-nemotron-nano-9b-v2-dgx-spark/-?_lr=1)
- [Nemotron Nano 9B v2 model card](https://build.nvidia.com/nvidia/nvidia-nemotron-nano-9b-v2/modelcard)
- [Llama 3.1 8B NIM catalog](https://catalog.ngc.nvidia.com/orgs/nim/meta/containers/llama-3.1-8b-instruct/-?_lr=1)
- [Embedding NIM support matrix](https://docs.nvidia.com/nim/nemo-retriever/text-embedding/latest/support-matrix.html)
- [Embed 300M v2 catalog](https://catalog.ngc.nvidia.com/orgs/nim/nvidia/containers/llama-nemotron-embed-300m-v2/-?_lr=1)
- [Reranking NIM 1.10 support matrix](https://docs.nvidia.com/nim/nemo-retriever/text-reranking/1.10.0/support-matrix.html)
- [Rerank 500M v2 catalog](https://catalog.ngc.nvidia.com/orgs/nim/nvidia/containers/llama-nemotron-rerank-500m-v2/-)
- [BGE-M3 self-host deployment](https://build.nvidia.com/baai/bge-m3/deploy?nim=self-hosted)
- [Master plan: Phase 3](../../NTC_NVIDIA_LOCAL_RAG_CHATBOT_MASTER_PLAN.md#phase-3--nim-model-bake-off)
