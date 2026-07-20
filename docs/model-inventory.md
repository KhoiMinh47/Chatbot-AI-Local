# Model and NVIDIA NIM image inventory

- Phase 0 inventory date: 2026-07-13
- Phase 0 evidence run: `20260713T090800Z`
- Phase 3 staging snapshot: 2026-07-14
- Phase 3 source run: `20260714T1120Z-full-r2` — immutable historical
  `BLOCKED` snapshot before operator selection
- Phase 3 decision addendum: `20260715T0218Z-nemotron-local-winner` — Nemotron
  Nano 9B v2 selected for local engineering
- Phase 5 activation run: `20260715T022157Z-embed300m-final-r3` — Embed 300M
  selected and `ntc_chunks_active` verified
- Scope: immutable image/model identity, ARM64 and observed runtime fields
- Policy: no secret capture; selections require immutable benchmark/decision
  evidence and must preserve earlier blocked snapshots

## Host summary

| Field | Observed value |
|---|---|
| Host architecture | `aarch64` / Linux ARM64 |
| GPU | NVIDIA GB10, persistence on |
| Driver / CUDA reported by `nvidia-smi` | 580.142 / CUDA 13.0 |
| Operating system | Ubuntu 24.04.4 LTS, kernel 6.17.0-1014-nvidia |
| CPU / memory | 20 CPUs / 121.7 GiB |
| Docker Engine | 29.1.3, server architecture `linux/arm64` |
| Docker Compose | 2.40.3 |
| Free root disk at capture | approximately 2.5 TiB |
| NIM/HF credential presence in capture shell | both absent; only non-empty presence was evaluated, and values were never emitted or persisted |

Raw evidence is under
[`artifacts/preflight/20260713T090800Z/`](../artifacts/preflight/20260713T090800Z/).
The host values above are observations, not minimum requirements.

## Phase 3 staging snapshot

Phase 0 was a read-only baseline. Phase 3 has since pulled only the reviewed
immutable pins, created persistent model caches and started each available NIM
temporarily on the GB10. Staging readiness is useful runtime evidence but is not
the full bake-off. Phase 3 subsequently completed sample, quality,
concurrency/long-context and both target-combination no-OOM runs for all four
available candidates. The later append-only decision selected Nemotron Nano 9B
v2 for local engineering. Corporate legal review and the 40–50+ tok/s release
target remain open. Embed 300M was subsequently selected in Phase 5 using the
verified Phase 4 corpus; BGE-M3 remained HTTP 402 and its comparison was
explicitly waived by the workspace operator. See
[Phase 3 acceptance evidence](../artifacts/phase-3/acceptance.md) and
[Phase 5 acceptance evidence](../artifacts/phase-5/acceptance.md).

| Role | Exact image pin | ARM64 manifest | NIM version / exact model ID | Observed profile/runtime | Model license/terms | Bake-off status |
|---|---|---|---|---|---|---|
| LLM baseline | `nvcr.io/nim/meta/llama-3.1-8b-instruct:2.0.6@sha256:31e360dbb15f825d69e5d68c2032e334301523b4957091270385ed7ef3db5e81` | `sha256:249dcac461f20bc29ddb0924bf0c30e0e3f646c26bd849d978996cbe30b4d06e` | `2.0.6`; `meta/llama-3.1-8b-instruct` | FP8 profile `c4789f7af56c770c1c88b73da666886365534d6980b6b922b41fd97036c77d73`; exact cache marker refreshed `2026-07-14T07:37:05Z`; runtime max `131072` | NVIDIA Open Model License terms plus Llama 3.1 Community License | Full benchmark pass; not selected after operator review |
| **LLM winner** | `nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2-dgx-spark:1.0.0-variant@sha256:82028e38ab950edd32f5053ca2030ee14d965e8fd4fe1c6e06468eb0be07a9a4` | same single-platform digest | `1.0.0`; `nvidia/nemotron-nano-9b-v2` | vLLM/NVFP4 profile `f9db61d5a467d46be7733e90a26705798764b93d480c842143d525c1932b01e2`, TP1/PP1, runtime max `131072` | NVIDIA Open Model License Agreement; corporate review pending | **Selected for local engineering**; full benchmark/context/no-OOM pass |
| **Embedding winner** | `nvcr.io/nim/nvidia/llama-nemotron-embed-300m-v2:1.13.0@sha256:1f0a7fc168919d7b84bb4edfb4a4da0c5828d11ee284f9fb8113242b3b35cbb4` | `sha256:5f8274faf21418cd894eb073d2c520923cce61a750c173b3745aedd1bb7efa49` | `1.13.0`; `nvidia/llama-nemotron-embed-300m-v2` | `a100x1-onnx-fp16` profile `e28f17c9c13a99055d065f88d725bf93c23b3aab14acd68f16323de1353fc528`; dimension `2048`; batch 1/16 pass | NVIDIA Open Model License; additional Llama 3.2 Community License information | **Selected/activated for local engineering** in Phase 5; BGE-M3 comparison explicitly waived |
| Reranking baseline | `nvcr.io/nim/nvidia/llama-nemotron-rerank-500m-v2:1.1@sha256:3e39d44bdb3dd683d6a2ac8d7689b484aee6c18dc7e00c2064f19501742720f3` | `sha256:6a598c5e6e7620c542f2101e24e34f3461e650a5b751200df56d52bf9f9444a9` | catalog tag `1.1`, in-image/runtime NIM `1.10.0`; `nvidia/llama-nemotron-rerank-500m-v2` | `a100x1-onnx-fp16` profile `f7391ddbcb95b2406853526b8e489fedf20083a2420563ca3e65358ff417b10f`; max `4096`; passages 2/16 pass | NVIDIA Community Model License | Evaluated; selected Phase 5 policy keeps reranker off |
| Embedding challenger | No exact image selected | Not available | target model `baai/bge-m3` | Authenticated `nim/baai/bge-m3:pull` scope probe returned HTTP `402` | Exact container terms not captured | **Blocked by entitlement/payment before immutable pin selection** |

Image tag, in-image NIM version, model ID and selected runtime profile are not
interchangeable. In particular, the Rerank catalog tag `1.1` packages NIM
`1.10.0`; its runtime-observed 4096-token limit takes precedence over an 8192
claim from a different optimized configuration. The exact Phase 3 topology,
metric definitions and acceptance gaps are documented in
[Phase 3 model bake-off](architecture/phase-3-model-bakeoff.md).

## NIM, model, and inference backend are different things

- A **model** is the learned weights plus tokenizer/configuration and its model
  identity/version. A model name or advertised context capability does not state
  how it is currently served.
- An NVIDIA **NIM** is a versioned inference microservice/container that exposes
  an API and selects supported runtime profiles for model assets. The NIM image,
  its cached model assets, and the served model ID are separate inventory items.
- **vLLM** is an inference engine. It can be the backend selected by a NIM
  profile—as in the local profile list—or run outside NIM. A generic vLLM image
  is therefore not automatically an NVIDIA NIM.

Tags make an image human-readable but can be repointed. An immutable registry
digest proves which image manifest was inspected; its Linux ARM64 child proves
that a platform build exists. Neither fact alone proves vendor support, loaded
model revision, active profile/precision, or runtime behavior, so those fields
are recorded and validated separately.

## Phase 0 local NIM baseline

At the Phase 0 capture, exactly one of 47 unique local image IDs matched the
captured NVIDIA NIM label criteria.

| Role | Repository:tag | Registry index digest | Local Docker image ID | Local platform | Registry ARM64 evidence | NIM version | Image-label model ID (served ID unverified) | Runtime status |
|---|---|---|---|---|---|---|---|---|
| LLM | `nvcr.io/nim/meta/llama-3.1-8b-instruct:2.0.6` | `sha256:31e360dbb15f825d69e5d68c2032e334301523b4957091270385ed7ef3db5e81` | `sha256:31e360dbb15f825d69e5d68c2032e334301523b4957091270385ed7ef3db5e81` | `linux/arm64` | Linux ARM64 child manifest `sha256:249dcac461f20bc29ddb0924bf0c30e0e3f646c26bd849d978996cbe30b4d06e` | 2.0.6 from image label and CLI banner | `meta/llama-3.1-8b-instruct` | Image present; no running NIM container; live API not smoked |

The registry index also contains an AMD64 variant. The exact registry response
is saved as
[`llama-3.1-8b-nim-2.0.6-registry-manifest.json`](../artifacts/preflight/20260713T090800Z/llama-3.1-8b-nim-2.0.6-registry-manifest.json).

Images named `vllm`, project-local inference images, CUDA/PyTorch images, and
Riva images were excluded because they are not NVIDIA NIM images for the three
required RAG roles.

## Phase 0 local LLM profile evidence

`list-model-profiles` ran successfully against the GB10 without downloading a
new image. It detected the GB10 and listed these non-LoRA profiles under
“Compatible with system and runnable”:

| Profile ID | Backend | Precision | TP / PP | Minimum memory reported |
|---|---|---|---|---:|
| `c4789f7af56c770c1c88b73da666886365534d6980b6b922b41fd97036c77d73` | vLLM | FP8 | 1 / 1 | 27 GB/GPU |
| `092ed4213624e774d24cdaf84e3b6222839bab2008a21d3c214ab46626366f90` | vLLM | BF16 | 1 / 1 | 33 GB/GPU |
| `a28963301b18077db3454d5eb21f5678304936c5a425ddc552443de1f5449f2a` | vLLM | NVFP4 | 1 / 1 | 24 GB/GPU |

Equivalent LoRA-enabled variants were also reported and are preserved in
[`llama-3.1-8b-nim-2.0.6-profiles.txt`](../artifacts/preflight/20260713T090800Z/llama-3.1-8b-nim-2.0.6-profiles.txt).

No profile was marked active in the Phase 0 capture: the inference server was
not started. Therefore, at that time,
the actual selected precision, runtime maximum model length, model-asset
revision, TTFT, and tokens/s are **unverified**. The Llama 3.1 model's 128K
capability must not be substituted for the runtime configuration.

## Phase 0 endpoint contract versus runtime evidence

For the local LLM's version-specific NIM 2.0.6 documentation:

| Purpose | Documented endpoint | Live-verified in Phase 0 |
|---|---|---|
| Liveness | `GET /v1/health/live` | No |
| Readiness | `GET /v1/health/ready` | No |
| Served models | `GET /v1/models` | No |
| Chat | `POST /v1/chat/completions` | No |
| Metrics | `GET /v1/metrics` | No |
| Runtime metadata/version/manifest | `GET /v1/metadata`, `/v1/version`, `/v1/manifest` | No |

Reason: no model cache was identified at the standard host paths, there is no
container derived from this NIM image, and the capture shell had neither an NGC
nor a Hugging Face token. Anonymous Docker volumes were not scanned for model
content. Starting the service could download model assets; Phase 0 did not do
so. A static profile check passed, but it is not an API smoke. NVIDIA's 2.0.6
release notes explicitly list an updated 2.0.6
`llama-3.1-8b-instruct` model-specific Certified NIM, and the versioned support
matrix lists NVIDIA GB10 as a verified GPU. The same per-model section still
displays “Latest supported NIM LLM version: 2.0.5”; this is recorded as an
upstream documentation-metadata discrepancy. Live runtime fields remain
unverified because the service was not started.

## Phase 0 candidate gaps (historical baseline)

The table below preserves what was missing at the Phase 0 read-only capture; it
must not be read as current local state. Phase 3 later staged the three named
NVIDIA candidates as shown in the snapshot above. BGE-M3 remains blocked and
Qwen remains conditional rather than automatically required.

| Role/candidate | Public reference checked 2026-07-13 | Local image/model cache | Registry ARM64 evidence | Profile/runtime status |
|---|---|---|---|---|
| Nemotron Nano 9B v2 DGX Spark | `nvcr.io/nim/nvidia/nvidia-nemotron-nano-9b-v2-dgx-spark:1.0.0-variant` | Missing | Single Linux ARM64 manifest `sha256:82028e38ab950edd32f5053ca2030ee14d965e8fd4fe1c6e06468eb0be07a9a4` | Unverified; no pull performed |
| Embedding 300M v2 | `nvcr.io/nim/nvidia/llama-nemotron-embed-300m-v2:1.13.0` | Missing | Linux ARM64 child `sha256:5f8274faf21418cd894eb073d2c520923cce61a750c173b3745aedd1bb7efa49` | Unverified; support matrix still states x86 CPU requirement |
| BGE-M3 Embedding NIM challenger | model ID `baai/bge-m3`; exact image/tag not selected | Missing | Not applicable until an exact image is selected | Unverified |
| Rerank 500M v2 | `nvcr.io/nim/nvidia/llama-nemotron-rerank-500m-v2:1.1` | Missing | Linux ARM64 child `sha256:6a598c5e6e7620c542f2101e24e34f3461e650a5b751200df56d52bf9f9444a9` | Unverified; support matrix still states x86 CPU requirement and served model ID must come from `/v1/models` |
| Qwen 8B-class Model-Free NIM challenger | exact model/image intentionally deferred | Missing | Not applicable until an exact image is selected | Unverified |

The three exact candidate manifests above were inspected read-only through the
registry without pulling image layers. Structured evidence is in
[`candidate-nim-manifests.json`](../artifacts/preflight/20260713T090800Z/candidate-nim-manifests.json).
For the multi-architecture Embed and Rerank tags, that artifact records the
exact Linux ARM64 child-manifest digests but not the mutable tag's top-level OCI
index digest. A future approved staging action must either pin those recorded
ARM64 child digests or capture and verify the then-current index digest first.

The versioned Embedding 1.13.0 and Reranking 1.12.0 support matrices both state
an x86 processor requirement, while the target host is `aarch64`. The exact
tags do contain Linux ARM64 registry manifests, but an available platform image
does not by itself override the documented x86 support requirement. This is an
upstream support contradiction that requires NVIDIA confirmation or a pinned
runtime smoke before these services can be approved on the host.

Separately, the matrices create a GB10 kernel gate. DGX Spark GB10 is compute
capability 12.1, while the optimized tables for Embed 300M v2 and Rerank 500M v2
list 12.0 (plus older families), not 12.1. If an exact staged image accepts this
host and selects the documented non-optimized configuration, that configuration
is FP16 with a 4096-token maximum. Do not claim ARM64 support, FP8, or 8192
tokens on GB10 until the exact staged image and its version-specific support
evidence establish them.

## Reproducible checks

Re-run the read-only inventory:

```bash
./scripts/preflight.sh
```

List profiles for the existing LLM image without pulling another image:

```bash
docker run --rm --gpus all \
  nvcr.io/nim/meta/llama-3.1-8b-instruct@sha256:31e360dbb15f825d69e5d68c2032e334301523b4957091270385ed7ef3db5e81 \
  list-model-profiles
```

After an operator has started a pinned service with approved credentials and a
persistent cache, run the API smoke using the exact ID returned by
`GET /v1/models`. Substitute the real service URLs; the examples do not reserve
or implement ports:

```bash
LLM_BASE_URL=<actual-llm-base-url>
LLM_MODEL_ID=$(curl -fsS "$LLM_BASE_URL/v1/models" | jq -er '.data[0].id')
NIM_KIND=llm \
NIM_BASE_URL="$LLM_BASE_URL" \
NIM_MODEL="$LLM_MODEL_ID" \
  ./scripts/nim-smoke.sh

EMBED_BASE_URL=<actual-embedding-base-url>
EMBED_MODEL_ID=$(curl -fsS "$EMBED_BASE_URL/v1/models" | jq -er '.data[0].id')
NIM_KIND=embedding \
NIM_BASE_URL="$EMBED_BASE_URL" \
NIM_MODEL="$EMBED_MODEL_ID" \
  ./scripts/nim-smoke.sh

RERANK_BASE_URL=<actual-reranking-base-url>
RERANK_MODEL_ID=$(curl -fsS "$RERANK_BASE_URL/v1/models" | jq -er '.data[0].id')
NIM_KIND=reranking \
NIM_BASE_URL="$RERANK_BASE_URL" \
NIM_MODEL="$RERANK_MODEL_ID" \
  ./scripts/nim-smoke.sh
```

These are one-request contract checks, not the Phase 3 bake-off. Current Phase
3 operator commands are:

```bash
make phase3-config
make phase3-images
make phase3-cache-llama
make phase3-cache-nemotron
make phase3-cache-retriever
make phase3-status
make phase3-acceptance
```

## Current model decision state

- DG-02 local-engineering decision is closed by ADR 0007: Nemotron Nano 9B v2
  is selected. Corporate legal approval remains an external release gate.
- DG-03 local-engineering decision is closed by the Phase 5 decision and
  activation receipt: Embed 300M is selected with operator waiver because exact
  BGE-M3 access still returns HTTP 402. No BGE-M3 comparison is claimed.
- DG-04 metric evidence is satisfied: decode rate, direct HTTP latency and
  client-observed request-dispatch-to-first-generated-token-delta latency are
  reported separately. The
  current runner times non-empty `content` or `reasoning_content` deltas but
  never persists reasoning; this value is an upper-bound proxy, not exact
  backend-receive TTFT or application end-to-end latency; report warm state,
  token lengths, concurrency and p50/p95 with that deviation. Neither model
  reaches 40–50 decode tok/s in this workload; bottleneck analysis remains for
  Phase 10.
- DG-05 live capability evidence passes for both candidates: actual
  32K/64K/128K requests pass the absolute token gate with runtime max 131072.
- Both LLM + Embed + Rerank combinations pass concurrent smoke/load, health,
  restart, telemetry, clean-log, cleanup and no-OOM checks.
- The active vector contract is now 2048 dimensions in physical collection
  `ntc_chunks_embed300m_v2_s256_o10_095bc081a101_recall95_v3`; alias
  `ntc_chunks_active` was read back against the signed Phase 5 receipt.

## Official sources checked

- [NIM LLM 2.0.6 quickstart](https://docs.nvidia.com/nim/large-language-models/2.0.6/get-started/quickstart.html)
- [NIM LLM 2.0.6 API reference](https://docs.nvidia.com/nim/large-language-models/2.0.6/reference/api-reference.html)
- [NIM LLM 2.0.6 support matrix](https://docs.nvidia.com/nim/large-language-models/2.0.6/reference/support-matrix.html)
- [NIM LLM 2.0.6 model-specific release update](https://docs.nvidia.com/nim/large-language-models/2.0.6/about-nim-llm/release-notes.html#model-specific-nim-updates)
- [Nemotron Nano 9B v2 model card](https://build.nvidia.com/nvidia/nvidia-nemotron-nano-9b-v2.md)
- [Nemotron Nano 9B v2 DGX Spark NGC catalog](https://catalog.ngc.nvidia.com/orgs/nim/nvidia/containers/nvidia-nemotron-nano-9b-v2-dgx-spark/-)
- [Embedding 300M v2 NIM 1.13 support matrix](https://docs.nvidia.com/nim/nemo-retriever/text-embedding/1.13.0/support-matrix.html)
- [Embedding 300M v2 NGC catalog](https://catalog.ngc.nvidia.com/orgs/nim/nvidia/containers/llama-nemotron-embed-300m-v2/-)
- [Rerank 500M v2 NIM 1.12 support matrix](https://docs.nvidia.com/nim/nemo-retriever/text-reranking/1.12.0/support-matrix.html)
- [Rerank 500M v2 NGC catalog](https://catalog.ngc.nvidia.com/orgs/nim/nvidia/containers/llama-nemotron-rerank-500m-v2/-)
- [Reranking NIM 1.10 support matrix used by the pinned image](https://docs.nvidia.com/nim/nemo-retriever/text-reranking/1.10.0/support-matrix.html)
- [BGE-M3 self-host deployment page](https://build.nvidia.com/baai/bge-m3/deploy?nim=self-hosted)
- [NVIDIA CUDA GPU compute capability](https://developer.nvidia.com/cuda/gpus)
- [NGC multi-architecture images](https://docs.nvidia.com/ngc/latest/ngc-catalog-user-guide.html#multi-architecture-support-for-ngc-container-images)
