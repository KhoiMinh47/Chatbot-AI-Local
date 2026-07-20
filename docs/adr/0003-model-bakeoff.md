# ADR 0003 — Evidence-based model bake-off; winners deferred

- Status: Accepted; DG-02 local-engineering deferral superseded by ADR 0007
- Date: 2026-07-13
- Last reviewed: 2026-07-15
- Phase: 0 decision method; canonical Phase 3 live execution **BLOCKED**;
  local LLM selected later
- Decision gate: DG-02, DG-03, DG-04, DG-05
- Owners: NTC Local RAG team

## Context

At the Phase 0 capture the host had one local NIM LLM image. An installed image
was not proof that its model was the best choice, that all model assets were
cached, or that it met Vietnamese quality, context, memory, and throughput
requirements. Selecting winners in Phase 0 would therefore have hard-coded
assumptions that the master plan requires Phase 3 and Phase 5 to measure.

Phase 3 has now staged and live-tested the pinned Llama, Nemotron, Embed and
Rerank images with repeated benchmark, quality, long-context and target-combo
evidence. That progress does not change the decision method: automatic scores
are not a winner decision, and BGE-M3 access is a hard blocker for the embedding
comparison.

On 2026-07-15 the workspace operator explicitly selected Nemotron Nano 9B v2
as the primary local-engineering LLM. ADR 0007 records that later decision and
its exact evidence hashes. It supersedes only this ADR's DG-02 deferral; the
canonical run, DG-03 embedding gate, production legal gate and DG-04 performance
follow-up remain unchanged.

## Evidence and constraints

- The inventory identified one local image as NVIDIA NIM through its captured
  labels:
  `nvcr.io/nim/meta/llama-3.1-8b-instruct:2.0.6` with immutable index digest
  `sha256:31e360dbb15f825d69e5d68c2032e334301523b4957091270385ed7ef3db5e81`.
  Its registry index contains a Linux ARM64 manifest; its in-image command
  detects the GB10 and lists FP8, BF16, and NVFP4 profiles as compatible and
  runnable. At that Phase 0 capture no startup profile had been selected. See
  [the model inventory](../model-inventory.md).
- No candidate Nemotron Nano 9B v2 DGX Spark, Embedding 300M v2, BGE-M3 NIM, or
  Rerank 500M v2 image or model cache was identified in the Phase 0 host paths;
  Phase 0 did not pull images. Phase 3 later staged exact immutable pins for all
  except BGE-M3.
- The Phase 0 Retriever 1.13/1.12 support tables stated an x86 CPU requirement,
  which conflicted with this `aarch64` host. Read-only registry inspection
  confirmed Linux ARM64 children, and the pinned Phase 3 images later loaded
  Triton/ONNX FP16 GPU profiles on GB10. This is runtime compatibility evidence,
  not a rewrite of vendor support. Rerank logged a 4096 tokenizer maximum;
  neither service may inherit an 8192 optimized-path claim from another profile.
- Model capability (for example, 128K) and the runtime maximum model length are
  different fields and must be measured separately.
- NIM version, model ID/version, inference backend, profile, and precision are
  separate inventory fields. One must not be inferred from another.

## Phase 3 evidence update

- Nemotron Nano 9B v2 NIM `1.0.0` reached live staging on GB10 with exact model
  ID `nvidia/nemotron-nano-9b-v2`, vLLM/NVFP4 profile
  `f9db61d5a467d46be7733e90a26705798764b93d480c842143d525c1932b01e2`,
  TP1/PP1 and configured maximum model length `131072`.
- Llama 3.1 8B NIM `2.0.6` now explicitly configures FP8 profile
  `c4789f7af56c770c1c88b73da666886365534d6980b6b922b41fd97036c77d73`
  for stage and runtime. The exact profile-specific cache marker was refreshed
  at `2026-07-14T07:37:05Z`; runtime verification cross-binds repository,
  digest, served model, NIM version, profile, precision and license evidence.
- Embed 300M v2 NIM `1.13.0` loaded a Triton/ONNX FP16 GPU profile on GB10 and
  returned dimension `2048`. It remains a candidate of approximately 569M total
  parameters, not an embedding winner.
- Rerank image tag `1.1` identifies in-image/runtime NIM `1.10.0`, not NIM 1.1.
  It loaded a Triton/ONNX FP16 GPU profile and logged tokenizer maximum length
  `4096`.
- An authenticated registry scope request for `nim/baai/bge-m3:pull` returned
  HTTP `402`. No exact BGE-M3 image/tag/digest can be approved until the account
  has the required entitlement/payment access. Mutable `latest` is not an
  acceptable workaround.
- Exact pins, ARM64 manifests, profile IDs and license terms are recorded in
  [the updated model inventory](../model-inventory.md) and
  [the Phase 3 architecture](../architecture/phase-3-model-bakeoff.md).
- Full run `20260714T1120Z-full-r2` executed six identical LLM scenarios with
  20 measured + 2 warmup requests each. Both models passed actual
  32K/64K/128K absolute token gates and automatic quality hard gates.
- Both provisional combinations (`Llama + Embed + Rerank` and
  `Nemotron + Embed + Rerank`) passed no-OOM, concurrent load, restart, health,
  telemetry, clean-log and cleanup checks.
- Full run `20260714T1000Z-full-r1` is invalid performance evidence because
  repeated prompts allowed asymmetric prefix-cache reuse. The accepted runner
  places a non-persisted deterministic nonce before shared context; only
  `full-r2` is used for comparison.

## Candidates and order

### LLM (Phase 3)

1. Smoke the existing Llama 3.1 8B NIM after its model assets and credentials
   are available.
2. Smoke NVIDIA Nemotron Nano 9B v2 DGX Spark when its exact image is staged.
3. Run the same Vietnamese/English RAG benchmark for both.
4. Add one Qwen 8B-class Model-Free NIM challenger only if the first two miss
   the multilingual quality gate.
5. Consider a 14B-class model only when a measured quality gain justifies the
   latency and memory cost.

Both first-line candidates passed the automatic multilingual hard gate, so the
conditional Qwen challenger was not activated. Human review can reopen this
decision if both candidates prove unacceptable.

### Embedding and reranking (Phase 3/5)

- Compare `nvidia/llama-nemotron-embed-300m-v2` with BGE-M3 on the same gold
  queries. The 300M model is approximately 569M total parameters and therefore
  satisfies the strict under-1B requirement on paper.
- Start with `nvidia/llama-nemotron-rerank-500m-v2`; compare the 1B challenger
  only if it produces a material quality gain.
- Never fix a Qdrant vector dimension until the embedding winner is selected.

## Decision method

LLM weighted score:

| Criterion | Weight |
|---|---:|
| Vietnamese/English correctness | 25% |
| Faithfulness and citation | 25% |
| RAG instruction following | 10% |
| TTFT and decode tokens/s | 20% |
| Memory and concurrency | 10% |
| Operations, license, and NIM compatibility | 10% |

Embedding/reranker weighted score:

| Criterion | Weight |
|---|---:|
| Recall@10 | 30% |
| MRR@10 | 20% |
| nDCG@10 | 15% |
| Vietnamese and table retrieval | 15% |
| Latency/throughput | 10% |
| Memory and operations | 10% |

Every candidate must first pass these hard gates:

1. Exact repository, tag, digest, Linux ARM64 manifest, license, and
   version-specific documentation recorded.
2. Runtime health, served model ID, backend, selected profile/precision, and
   maximum configured length observed rather than inferred.
3. No OOM in the intended LLM + embedding + reranker combination.
4. Reproducible JSON/CSV output for quality, TTFT, decode tokens/s, memory, and
   concurrency. Warm/cold state, input/output lengths, and profile are included.
5. The LLM long-context capability is tested separately from the smaller
   normal RAG context budget.

## Decision

Adopt the bake-off process and gates above. **No LLM winner or embedding winner
is selected as of the 2026-07-14 Phase 3 live snapshot.** Nemotron's provisional
automatic total (`0.93183`) is higher than Llama's (`0.90796`), but human and
legal review are pending and automatic winner selection is forbidden. Llama
3.1 8B remains the baseline; Nemotron remains the LLM candidate; vector
dimension must not be fixed from Embed 300M until DG-03 is resolved. Overall
Phase 3 state is **BLOCKED**, not PASS.

That statement is the historical snapshot, not the current application choice.
ADR 0007 subsequently selects exact Nemotron for local engineering by explicit
operator authority, while retaining legal and performance deviations.

## Consequences

### Positive

- Model choice is reviewable and reproducible rather than based on parameter
  count or an image name.
- Version/profile differences stay behind future client adapters.
- ARM64 manifests, documented platform support, and runtime profile support are
  treated as separate, visible decision gates.

### Negative and risks

- The full embedding bake-off cannot complete while BGE-M3 registry access
  returns HTTP 402.
- Retriever has both an x86-versus-ARM64 support contradiction and a GB10
  optimized-kernel uncertainty. Exact local runtime smoke now passes on the
  pinned ARM64 artifacts, but this does not rewrite vendor support tables;
  version-specific NVIDIA confirmation remains desirable.
- NVIDIA's release notes list a certified Llama 3.1 8B NIM update for 2.0.6 and
  its matrix verifies GB10, while the same page retains a stale per-model
  “2.0.5” label. Treat this as upstream documentation metadata, not a missing
  certification claim; keep the staged live 2.0.6 metadata in the final report.
- The live workflow now proves automatic supplied-context quality, p50/p95
  engine performance, long-context behavior and target-combination no-OOM, but
  it does not replace human semantic review, legal approval, BGE-M3 comparison
  or application end-to-end evaluation.
- Neither LLM reaches 40–50 decode tok/s in the fixed Phase 3 workload. The
  absolute observation must remain visible for Phase 10 bottleneck analysis;
  relative score normalization is not evidence that the target was reached.

## Validation

- Local image labels, digest, registry ARM64 manifest, and profile list are
  captured under `artifacts/preflight/20260713T090800Z/`.
- A reusable API contract smoke exists at [`scripts/nim-smoke.sh`](../../scripts/nim-smoke.sh).
- Phase 3 provides pinned Compose, cache staging, LLM/embedding/reranking client
  adapters and benchmark/quality runners. The reviewed full evidence is
  summarized in
  [`artifacts/phase-3/acceptance.md`](../../artifacts/phase-3/acceptance.md);
  this ADR asserted no winner at the snapshot. The later LLM selection is
  separately auditable in ADR 0007 and does not turn this run into full PASS.
- `make check` passes 195 pytest, 2 Vitest, lint, formatting, typecheck, build and
  Phase 1 smoke. Phase 3 Compose/image contracts also pass, cleanup leaves zero
  project containers and exact secret scanning has zero hit.

## Unknowns and blockers

- BGE-M3 exact image selection, health and comparison report are blocked by the
  authenticated HTTP 402 registry response.
- Llama/Nemotron repeated short/RAG/concurrency and actual 32K/64K/128K evidence
  are complete; Vietnamese/English human review and legal approval remain open.
- Both intended combinations have durable no-OOM evidence. GB10 unified-memory
  N/A fields remain N/A and were not rewritten as zero.
- DG-04's 40–50 tokens/s deviation is accepted by the operator only for local
  Phase 6 work; production performance remains open for Phase 10. Reports
  include decode throughput and direct NIM HTTP latency. The
  runner's request-dispatch-to-first-generated-token-delta timing is only a
  client-observed upper-bound proxy. It times non-empty `content` or
  `reasoning_content` deltas without persisting reasoning; exact backend-receive
  TTFT and application end-to-end latency are not measured by this Phase 3
  runner.
- Embed 300M and Rerank 500M pass basic semantic sanity only. Retrieval metrics
  such as Recall@10/MRR/nDCG and the BGE-M3 comparison remain unavailable; no
  Phase 5 work was pulled into this ADR.

## Revisit when

- A candidate image, digest, model asset, or license changes.
- Corporate legal/human review promotes or rejects the ADR 0007 local choice.
- The Phase 3/5 process names an embedding winner after its applicable gates.
- A support matrix or runtime smoke changes the GB10 compatibility result.

## References

- [NIM LLM 2.0.6 support matrix](https://docs.nvidia.com/nim/large-language-models/2.0.6/reference/support-matrix.html)
- [NIM LLM 2.0.6 model-specific release update](https://docs.nvidia.com/nim/large-language-models/2.0.6/about-nim-llm/release-notes.html#model-specific-nim-updates)
- [NIM LLM 2.0.6 API reference](https://docs.nvidia.com/nim/large-language-models/2.0.6/reference/api-reference.html)
- [Embedding NIM 1.13 support matrix](https://docs.nvidia.com/nim/nemo-retriever/text-embedding/1.13.0/support-matrix.html)
- [Reranking NIM 1.10 support matrix](https://docs.nvidia.com/nim/nemo-retriever/text-reranking/1.10.0/support-matrix.html)
- [Nemotron Nano 9B v2 DGX Spark catalog](https://catalog.ngc.nvidia.com/orgs/nim/nvidia/containers/nvidia-nemotron-nano-9b-v2-dgx-spark/-?_lr=1)
- [Embed 300M v2 catalog](https://catalog.ngc.nvidia.com/orgs/nim/nvidia/containers/llama-nemotron-embed-300m-v2/-?_lr=1)
- [Rerank 500M v2 catalog](https://catalog.ngc.nvidia.com/orgs/nim/nvidia/containers/llama-nemotron-rerank-500m-v2/-)
- [BGE-M3 self-host deployment page](https://build.nvidia.com/baai/bge-m3/deploy?nim=self-hosted)
- [DGX Spark system overview](https://docs.nvidia.com/dgx/dgx-spark/system-overview.html)
- [Master plan: model strategy](../../NTC_NVIDIA_LOCAL_RAG_CHATBOT_MASTER_PLAN.md#6-chiến-lược-chọn-model)
- [ADR 0007: Nemotron local-engineering winner](0007-nemotron-nano-9b-v2-local-engineering-winner.md)
