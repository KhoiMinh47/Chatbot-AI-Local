# Phase 3 Completion Status

**Phase**: 3 — NIM Model Bake-off  
**Status**: Implementation complete; Nemotron selected for local engineering;
production legal gate pending  
**Completion Date**: 2026-07-14  
**Decision Addendum**: 2026-07-15, ADR-0007  

---

## Summary

Phase 3 implementation and canonical evidence collection are technically
complete. The immutable canonical run remains **BLOCKED** exactly as generated:
it had no LLM/embedding winner and BGE-M3 access returned HTTP 402. On
2026-07-15 the workspace operator selected exact Nemotron Nano 9B v2 as the
primary **local-engineering** LLM in a separate append-only decision. Corporate
legal approval and the 40–50+ tok/s performance target remain open; neither is
silently converted into a pass.

Current downstream state (2026-07-15): Phase 4 has completed its 10-file live
ingestion E2E, and Phase 5 has selected/activated Embed 300M using that corpus
with an explicit BGE-M3 waiver. The authorization and provisional strategy
sections below are retained as historical handoff context, not current pending
work.

---

## Implementation Completion Checklist

### Code Quality: ✅ COMPLETE
- [x] All Phase 3 scripts implemented (benchmark, quality, runtime_evidence, scorecard)
- [x] OpenAI-compatible LLM adapter (in preparation for Phase 6)
- [x] Embedding/reranking adapters (in preparation for Phase 5)
- [x] No TODO/FIXME/placeholder code
- [x] No hard-coded secrets or model URLs
- [x] Proper error handling and logging
- [x] Secret redaction in all outputs

### Testing: ✅ COMPLETE
- [x] 109 Phase 3 unit tests: PASS
- [x] 195 total pytest: PASS
- [x] 2 Vitest: PASS
- [x] Lint (Ruff, ESLint, ShellCheck): PASS
- [x] Typecheck (mypy, TypeScript): PASS
- [x] Integration tests for all candidates
- [x] Secret scanning tests
- [x] Acceptance test framework

### Evidence Collection: ✅ COMPLETE
- [x] Llama 3.1 8B: Full benchmark (6 scenarios, 20+2 requests each)
- [x] Nemotron Nano 9B: Full benchmark (6 scenarios, 20+2 requests each)
- [x] Embed 300M: Runtime verification, semantic sanity
- [x] Rerank 500M: Runtime verification, semantic ordering
- [x] BGE-M3: Access probe (HTTP 402 documented)
- [x] Quality evaluation (10 automatic hard gates)
- [x] Long context tests (32K/64K/128K)
- [x] Combination tests (Llama + retrieval, Nemotron + retrieval)
- [x] Scorecard generation with provisional scores
- [x] Metadata correction applied

### Documentation: ✅ COMPLETE
- [x] Acceptance evidence (artifacts/phase-3/acceptance.md)
- [x] Verification report (PHASE3_VERIFICATION_REPORT.md)
- [x] ADR-0004 (phase3-completion-and-phase4-start.md)
- [x] ADR-0007 (exact Nemotron local-engineering winner)
- [x] Append-only winner decision with canonical source hashes
- [x] Run artifacts preserved (20260714T1120Z-full-r2)
- [x] Debug closure documented
- [x] Metric scope explicitly defined

---

## Acceptance Criteria Status

| ID | Criterion | Status | Notes |
|----|-----------|--------|-------|
| AC-01 | Each model has health, sample request and report | 🚫 **BLOCKED** | 4/5 models complete; BGE-M3 HTTP 402 |
| AC-02 | LLM winner supports context requirement or has config evidence | ✅ **LOCAL PASS / LEGAL PENDING** | Exact Nemotron selected by operator; 32K/64K/128K and runtime max 131072 pass; corporate legal approval pending |
| AC-03 | Speed reported with correct definition | ✅ **PASS** | TTFT, decode, latency scope explicitly documented |
| AC-04 | Embedding winner under 1B | 🚫 **BLOCKED** | Embed 300M (~569M) verified; BGE-M3 comparison incomplete |
| AC-05 | No OOM in target service combinations | ✅ **PASS** | Both combinations healthy with RestartCount=0 |
| AC-06 | Model/license recorded | 🚫 **BLOCKED** | 4/5 models have pinned image/license; BGE-M3 unavailable |

**Current result**: the historical run was 2 PASS / 4 BLOCKED. The append-only
decision now closes the LLM engineering selection needed for local Phase 6, but
does not close BGE-M3/embedding or legal/compliance gates.

---

## External Blockers

### 1. BGE-M3 NGC Entitlement (Business Decision)

**Issue**: Live authenticated scope probe returns HTTP 402 (payment required)

**Evidence**: `artifacts/phase-3/runs/20260714T1120Z-full-r2/bge-m3-access.json`

**Required Action**: Business/procurement decision to purchase NGC entitlement

**Owner**: Business stakeholder (not engineering)

**Impact**: 
- Cannot complete embedding bake-off comparison
- AC-01, AC-04, AC-06 remain blocked
- Provisional Embed 300M can be used for Phase 4-6 development

**Timeline**: Uncertain (procurement process)

### 2. LLM Formal Review and Legal Approval (Compliance Process)

**Issue**: The operator has selected Nemotron for local engineering, while the
canonical formal case-level human review and legal license approval are still
pending.

**Evidence**: 
- `scorecard.json`: Both LLMs have `legal_approval.status: "pending"`
- Quality scores are marked `"automatic_provisional"`

**Required Action**: 
- Human review of quality evaluation results
- Legal review of license terms for production use

**Owner**: Legal/compliance team (not engineering)

**Impact**:
- Local application/Phase 6 may bind the exact Nemotron identity from ADR-0007.
- Production/commercial approval may not be inferred from that engineering
  choice.
- A future legal rejection must deactivate the production path and reopen the
  candidate decision.

**Timeline**: Uncertain (legal review process)

---

## What Was Achieved

### Technical Achievements

1. **Model Runtime Verification**
   - Proven both Llama 8B and Nemotron 9B can handle 128K context
   - Measured exact TTFT, decode throughput, total latency
   - Verified no OOM with concurrent combinations
   - Documented exact image digests, profiles, precisions

2. **Quality Framework**
   - 10 automatic hard gates implemented and tested
   - Deterministic scoring for correctness, faithfulness, instruction following
   - Proper citation validation
   - Prompt injection defense verified

3. **Retrieval Stack**
   - Embed 300M verified with Vietnamese semantic sanity
   - Rerank 500M verified with semantic ordering
   - Both proven compatible with target LLM combinations

4. **Infrastructure**
   - Secret handling audited (no leaks)
   - Cleanup verified (containers removed, volumes preserved)
   - Cache staging proven
   - Telemetry collection validated

### Evidence Quality

- **Reproducible**: Full run ID with timestamp
- **Immutable**: Pinned image digests, not `latest` tags
- **Auditable**: All artifacts preserved with provenance
- **Honest**: BLOCKED status documented without fake PASS
- **Secure**: Secrets redacted, scan verified

---

## Historical Phase 4 Authorization

Per **ADR-0004**, Phase 4 (Document Ingestion) is authorized to start because:

1. Phase 3 implementation is complete
2. Phase 4 does not depend on embedding/LLM winner selection
3. Provisional Embed 300M can support development
4. External blockers cannot be resolved by coding

**Configuration Strategy**:
- Use Embed 300M (2048-dim) provisionally
- Keep vector dimension configurable
- Document migration plan for winner change
- Do NOT hardcode model assumptions

**Boundary Enforcement**:
- Phase 4 will NOT claim embedding winner
- Phase 4 will NOT activate LLM for production
- Phase 4 will focus on document processing pipeline only

---

## Follow-up Actions

### If BGE-M3 Is Reconsidered for a Later Release:
1. Re-run embedding benchmark with same workload
2. Compare Embed 300M vs BGE-M3 metrics
3. Update scorecard with comparison results
4. Treat any change as a new reviewed decision; do not rewrite the active
   Embed-300M receipt
5. If BGE-M3 wins and dimension differs, create a new physical collection and
   migration/rollback plan

### When Human/Legal Review Completes:
1. Add a new append-only approval/rejection artifact; do not rewrite the
   canonical run.
2. Record the approved license scope and reviewer/authority.
3. Promote or revoke the local Nemotron selection for production accordingly.
4. Keep the measured performance deviation open until Phase 10 resolves or the
   accountable stakeholder accepts it for release.

### Phase 3 Status Update:
- Mark acceptance.md with completion timestamp
- Link to ADR-0004 for Phase 4 authorization
- Track external blocker resolution separately

---

## Lessons Learned

### What Went Well
- Comprehensive test coverage caught all issues early
- Debug runs helped identify prompt caching problems
- Metadata correction workflow proven effective
- Secret handling audit prevented leaks

### What Could Improve
- Earlier communication on external dependencies
- Parallel tracking of procurement/legal processes
- More explicit phase transition criteria

### Applied to Phase 4
- Start external dependency discussions early
- Document configuration flexibility from the start
- Maintain clear boundary between technical and business decisions

---

## References

- **Acceptance Evidence**: [artifacts/phase-3/acceptance.md](../../artifacts/phase-3/acceptance.md)
- **Verification Report**: [PHASE3_VERIFICATION_REPORT.md](../../PHASE3_VERIFICATION_REPORT.md)
- **ADR-0004**: [docs/adr/0004-phase3-completion-and-phase4-start.md](../../docs/adr/0004-phase3-completion-and-phase4-start.md)
- **ADR-0007**: [docs/adr/0007-nemotron-nano-9b-v2-local-engineering-winner.md](../../docs/adr/0007-nemotron-nano-9b-v2-local-engineering-winner.md)
- **Winner Decision**: [artifacts/phase-3/decisions/20260715T0218Z-nemotron-local-winner/decision.json](decisions/20260715T0218Z-nemotron-local-winner/decision.json)
- **Primary Run**: [artifacts/phase-3/runs/20260714T1120Z-full-r2/](../../artifacts/phase-3/runs/20260714T1120Z-full-r2/)
- **Master Plan**: [NTC_NVIDIA_LOCAL_RAG_CHATBOT_MASTER_PLAN.md](../../NTC_NVIDIA_LOCAL_RAG_CHATBOT_MASTER_PLAN.md)

---

**Status**: Phase 3 implementation complete. Nemotron is the primary local
engineering LLM per ADR-0007. Corporate legal and Phase 10 performance gates
remain tracked separately; Phase 4 was authorized per ADR-0004.

**Last Updated**: 2026-07-15
