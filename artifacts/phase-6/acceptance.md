# Phase 6 acceptance evidence — winner-bound local RAG

- Master plan scope: Phase 6 — Baseline RAG and Fast/Reasoning LangGraph
- Canonical run: `20260715T025554Z-nemotron-embed300m-winner-r7`
- Created: `2026-07-15T02:56:08.041794Z`
- Result: **PASS — 6/6 Phase 6 acceptance criteria for local engineering**
- Phase 7 started: **No**
- Report SHA-256:
  `07701b7ba3ca0e694726753ab92442a3b98f5280c514328346f81fa00a9f264f`

The canonical run invokes the internal Phase 6 application graph directly. It
uses the exact active Qdrant alias and Phase 4 corpus, live Embed 300M NIM, live
Nemotron NIM, the exact local Nemotron tokenizer, and durable PostgreSQL trace
storage. It does not use synthetic retrieval evidence and it does not add a
public chat/auth/SSE endpoint from Phase 7.

Primary evidence:

- [`report.json`](runs/20260715T025554Z-nemotron-embed300m-winner-r7/report.json)
- [`report.sha256`](runs/20260715T025554Z-nemotron-embed300m-winner-r7/report.sha256)
- [`INVENTORY.md`](INVENTORY.md) — exact model/index/policy/input bindings
- [`ADR 0008`](../../docs/adr/0008-phase6-winner-bound-local-rag.md)

## Exact winner binding

| Layer | Canonical binding |
|---|---|
| LLM | `nvidia/nemotron-nano-9b-v2`, NIM `1.0.0`; live `/models` returned only the exact selected ID |
| Mode control | Fast `/no_think`; Reasoning `/think`; trusted system instruction only |
| Embedding | `nvidia/llama-nemotron-embed-300m-v2`, NIM `1.13.0`, dimension `2048`; live `/models` exact |
| Active Qdrant alias | `ntc_chunks_active` |
| Physical collection | `ntc_chunks_embed300m_v2_s256_o10_095bc081a101_recall95_v3`, 12 expected points |
| Index fingerprint | `a3cc25bb8e65a03ac1146c227c4c2b8c5a86370f4852eb35eb4d66330dd20290` |
| Retrieval-policy fingerprint | `37a6fb7d83d292ba67f7709ce5e8e77483a73b86cd470938486d37b2d38c65b8` |
| Retriever policy | threshold `0.2300481`, dense top 20, final 10, HNSW `ef=128`, reranker off |
| Exact tokenizer | `nvidia/nemotron-nano-9b-v2`; SHA-256 `32bd2509c1acc93dc18bdd0f9a2d9a15e72fd3110f24cfc9ff3fb820f4e20b6b` |
| Prompt/graph | `phase6-grounded-v4`, prompt SHA `d6199475...`, `phase6-stategraph-v2` |

Upstream evidence is hash-bound:

- Phase 5 decision:
  `290d1b34f7c350658207dea14c8e1f045314fc2126c3522adeecf1eea12cb610`;
- Phase 5 activation receipt:
  `2b0f68582a8e1398b4507e73a596887fa271cf33308456efeb294225f08fd76f`;
- exact stratified gold:
  `393c9147f6a59a41e1a038a7622dc7d4183571fb4a1aa3a1940514629c155ca3`;
- report field `gold_binding.matches_phase5_decision`: `true`.

## Acceptance criteria

| Acceptance criterion | Result | Canonical r7 evidence |
|---|---|---|
| Same question shows different mode budget/latency | **PASS** | Same case `p4-001-v1` and question hash. Fast: `1.166743 s`, output reserve 768, safety 1536, context cap 8192. Reasoning: `9.394018 s`, output reserve 4096, safety 2048, context cap 16384. These are single live observations, not p50/p95 |
| Answer has a valid citation | **PASS** | Both modes answered and cited server-issued `S1`, mapped to chunk `07306e9f-...`, document `177185e3-...`, `01_leave_policy.pdf`, page 1 |
| No fabricated citation | **PASS** | Citation IDs and metadata were server-issued; answer citations were within the current context allowlist; answer hashes matched PostgreSQL traces |
| Unanswerable test refuses correctly | **PASS** | Case `p4-019-v1` produced `insufficient_evidence`, zero context refs/citations and `chat=0`, `stream=0`; latency `0.029814 s` |
| Context stays within budget | **PASS** | Exact token budgets were present for all three paths; Fast prompt 347/output reserve 768/safety 1536 and Reasoning prompt 345/output reserve 4096/safety 2048 remained below 32768; NIM usage matched the exact tokenizer |
| Client receives no chain-of-thought | **PASS** | All result records report `contains_hidden_reasoning=false`; events contained no hidden-reasoning field; client/trace security checks confirm no CoT, raw prompt, raw answer or raw event payload was recorded |

## Fast and Reasoning policy evidence

The modes have different configured ceilings even when this simple fact query
needs only one actual subquery and one retrieval round:

| Control | Fast | Reasoning |
|---|---:|---:|
| Max subqueries | 1 | 3 |
| Max retrieval rounds | 1 | 2 |
| Max dense candidates | 12 | 30 |
| Candidate limit/query | 12 | 10 |
| Final context limit | 6 | 12 |
| Context token cap | 8192 | 16384 |
| Max output tokens | 768 | 4096 |
| Safety reserve | 1536 | 2048 |
| Reasoning control | `no_think` | `think` |
| Actual elapsed seconds | 1.166743 | 9.394018 |
| Actual input/output tokens | 347 / 27 | 345 / 223 |

Reasoning made one non-stream planning call and one streaming generation call;
Fast made only one streaming generation call. Forcing three subqueries for an
easy fact question would add work without improving evidence, so acceptance
checks distinct bounded policies rather than artificial decomposition.

The Phase 5 retrieval-policy fingerprint locks the approved **base** dense
ceiling at 20; it does not by itself encode Phase 6 mode caps. Graph v2 passes a
mode cap into the retriever, so the actual Qdrant request uses
`min(approved_base, mode_cap)`: Fast `min(20,12)=12`, Reasoning
`min(20,10)=10`. This binding is evidenced jointly by `mode_policy_binding`,
`phase6-stategraph-v2`, the graph/retrieval source hashes and regression tests.
The live corpus returned one candidate in each mode, which is within both caps.

## ACL and active-alias proof

The same active alias was queried with trusted filters before generation:

- owner scope returned exactly one hit and the expected source;
- unrelated principal returned zero hits;
- raw query and unrelated principal were not persisted;
- both retrieval results carried the selected index and policy fingerprints.

This is a datastore-filter proof, not post-retrieval filtering. The Phase 5
activation receipt also confirms alias readback to the exact physical
collection, but Phase 6 does not rely on the receipt alone.

## PostgreSQL trace and migration evidence

Migration
[`0005_phase6_winner_trace_binding.py`](../../migrations/versions/0005_phase6_winner_trace_binding.py)
adds the retrieval-policy fingerprint to generation traces while leaving old
unbound candidate rows truthful. Canonical source SHA-256:
`7668b4e05a5b5d91b0053b3e5ec56013fde8dd1f6db97b37e6e7215683c1f985`.

Live readback found three durable traces: Fast answered, Reasoning answered and
Fast insufficient-evidence. Each row matched its question/answer hash, outcome,
model/version where generation occurred, index fingerprint, retrieval-policy
fingerprint, token budget, context refs and citations. The insufficient path
correctly has null model/version because no LLM was called.

The schema/report persist none of: database URL, credentials, raw question,
prompt, answer, document text, raw events or chain-of-thought.

## Debug history retained

The winner-bound attempts are immutable and only r7 is canonical:

| Run | Status | Disposition |
|---|---|---|
| `20260715T022730Z-nemotron-embed300m-winner-r1` | **FAIL** | Reasoning ended in `rag_execution_failed`; failed checks remain recorded |
| `20260715T022911Z-nemotron-embed300m-winner-r2` | **FAIL** | Reasoning output was rejected for `hidden_reasoning` and `uncited_claim`; safety failed closed |
| `20260715T023134Z-nemotron-embed300m-winner-r3` | **PASS, noncanonical** | Passed technical checks against older gold hash `23fae69f...`, which does not match the Phase 5 winner decision |
| `20260715T023547Z-nemotron-embed300m-winner-r4` | **FAIL** | Correct gold/bindings, but report incorrectly required actual simple-query retrieval plans to differ; both modes legitimately used one query/round |
| `20260715T023711Z-nemotron-embed300m-winner-r5` | **PASS, historical snapshot** | Correct functional bindings, but the repository format gate rewrote three provenance-bound source files after the run; its hashes no longer describe the current workspace |
| `20260715T024856Z-nemotron-embed300m-winner-r6` | **PASS, historical snapshot** | No-CoT hardening was present, but audit found the mode candidate cap was not passed into the actual Qdrant request |
| `20260715T025554Z-nemotron-embed300m-winner-r7` | **PASS, canonical** | Graph v2 enforces effective Qdrant limits Fast 12/Reasoning 10; correct gold/decision/receipt, 23/23 checks true and all 13 source-provenance hashes match current source |

Earlier `llama-direct-r1` through `r4` are retained as pre-winner candidate
debug evidence. They do not override the selected Nemotron/Embed 300M run.

## Remaining release gates

Phase 6 is complete for local engineering, not a full production release:

1. Corporate legal approval for Nemotron remains pending.
2. Phase 10 still owns the 40–50+ tok/s deviation, p50/p95, concurrency and load
   evidence. The r7 latency values are not a performance distribution.
3. A fresh full generation evaluation set still needs independent human review
   for correctness, faithfulness, citation coverage and refusal behavior. r7
   covers one answerable question in both modes plus one unanswerable question.
4. Phase 7 must add authenticated public chat/SSE transport, RBAC, conversation
   lifecycle, reconnect/idempotency, cancellation and rate limiting.

No Phase 7 implementation or acceptance is claimed here.
