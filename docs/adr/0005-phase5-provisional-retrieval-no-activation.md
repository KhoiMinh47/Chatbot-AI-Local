# ADR 0005 — Physical vector indexes; provisional retrieval config is not activated

- Status: Superseded in part by the canonical Phase 5 winner decision; physical
  index and approval-bound activation design retained
- Date: 2026-07-15
- Phase: 5
- Decision gate: DG-03 and Phase 5 retrieval acceptance
- Owners: NTC Local RAG team

> Current-state addendum (2026-07-15): this ADR records the earlier provisional
> candidate-grid state. Phase 4 later supplied a verified 10-file corpus and the
> workspace operator explicitly selected Embed 300M while waiving the unavailable
> BGE-M3 same-gold comparison. Canonical run
> `20260715T022157Z-embed300m-final-r3` activated `ntc_chunks_active` only after
> writing an immutable decision and approval receipt. See
> [Phase 5 acceptance evidence](../../artifacts/phase-5/acceptance.md). The
> no-unapproved-switch, immutable-dimension, ACL-filter and atomic-alias rules
> below remain authoritative.

## Context

The master plan requires an Embed-300M versus BGE-M3 bake-off, an immutable
Qdrant dimension contract, ACL filtering inside vector search, a reproducible
retrieval report, and a justified winner. Embed-300M and Rerank-500M are
available locally; exact BGE-M3 access still returns HTTP 402. Phase 4 also does
not yet provide a verified 10+ file end-to-end corpus.

Running no benchmark would leave the retrieval architecture and security
contract untested. Calling Embed-300M a winner would violate the bake-off gate
and could lock Qdrant to the wrong dimension. The implementation therefore
needs useful candidate evidence without silently turning it into activation.

## Decision

1. Use one physical Qdrant collection per exact embedding/chunk/index config.
   Existing collection dimension and distance are immutable; a mismatch must
   create a new physical collection.
2. Apply tenant, ACL principals, index version, child type, and optional document
   filters inside every Qdrant query, then validate returned payloads again.
3. Bind every config to a deterministic SHA-256 fingerprint. Only an explicit
   `WinnerApproval` for that fingerprint may atomically switch
   `ntc_chunks_active`.
4. Run the exact master-plan chunk grid with available Embed-300M and compare
   Rerank-500M, but label all selection as provisional while BGE-M3 is missing.
5. Keep the active alias unchanged and return workflow status BLOCKED/exit 3.
6. Do not implement Phase 6 while Phase 5 is being evaluated.

## Provisional observation

Run `20260714T175000Z-embed300m-r5` selects:

```text
Embed-300M v2 / dimension 2048
chunk size 256 / overlap 10%
reranker off
dense threshold 0.31797254
winner eligible: false
activation authorized: false
```

The chunk choice follows a fixed metric/latency/tie-break order. Reranker is off
because its raw nDCG gain is not material, its calibrated Recall@10 regresses
below the gate, and p95 latency exceeds twice dense p95. The threshold is not a
production decision because it was calibrated and evaluated on the same
synthetic fixture.

## Consequences

### Positive

- Dimension drift and model/version drift fail before corrupting an index.
- ACL correctness is enforced by the datastore query, not post-filtering alone.
- Every metric can be traced to hashed inputs, relevant source/lockfile hashes,
  Qdrant runtime identity, ACL JUnit evidence, and per-query observations.
- Candidate benchmarking can proceed without making an unauthorized winner
  decision or mutating the active alias.

### Negative and risks

- Candidate collections must be rebuilt for every exact config, using more
  temporary time/storage during a grid run.
- Synthetic corpus metrics can be much easier than real parser output and must
  not be presented as production retrieval quality.
- Same-fixture threshold calibration is optimistic.
- Phase 5 remains blocked until BGE-M3 and the Phase 4 corpus are available.

## Rejected alternatives

- **Reuse one collection and change vector dimension:** Qdrant collection
  contract and stored points would become incompatible.
- **Filter ACL after top-k:** unauthorized vectors could affect ranking and leak
  metadata before filtering.
- **Declare Embed-300M winner because BGE-M3 is unavailable:** violates the
  explicit comparison gate and ADR 0003.
- **Switch alias to the provisional config:** turns incomplete evidence into
  production state and makes rollback/audit ambiguous.
- **Use another unreviewed BGE image/model:** would not satisfy exact runtime,
  immutable pin, license, or same-workload evidence.

## Validation

- 12/12 chunk-grid configurations produced observations and metrics.
- Live Qdrant test proved dimension mismatch rejection and tenant/user ACL
  isolation, then removed the temporary collection.
- Alias before and after the canonical run was null; no alias action occurred.
- Candidate NIM containers remained healthy with no restart or OOM during the
  run.
- Detailed evidence is in
  [`artifacts/phase-5/acceptance.md`](../../artifacts/phase-5/acceptance.md).

## Revisit when

- BGE-M3 entitlement is resolved and an exact immutable runtime can be tested;
- Phase 4 produces the required real ingestion corpus;
- a held-out threshold calibration run is available;
- a reviewed report names an embedding winner and provides exact approval
  evidence for alias activation.
