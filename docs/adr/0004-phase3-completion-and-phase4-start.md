# ADR-0004: Phase 3 Completion Status and Phase 4 Start Decision

> Current-state addendum (2026-07-15): Phase 4 later passed all five explicit
> acceptance criteria in live run `20260715T0912Z-live-e2e-r3`; see
> [`artifacts/phase-4/acceptance.md`](../../artifacts/phase-4/acceptance.md).
> ADR 0007 separately selected Nemotron as the local-engineering LLM. The
> original authorization and its then-current blockers below remain historical.

**Status**: Accepted  
**Date**: 2026-07-14  
**Decision Makers**: Engineering Team  
**Related**: Phase 3 acceptance.md, NTC_NVIDIA_LOCAL_RAG_CHATBOT_MASTER_PLAN.md

---

## Context

Phase 3 (NIM Model Bake-off) has completed all implementation work and testing with the following status:

### Phase 3 Completion Summary

**All Code and Tests: COMPLETE ✓**
- 109 Phase 3 unit tests: PASS
- 195 total pytest: PASS  
- 2 Vitest: PASS
- Lint (Ruff, ESLint, ShellCheck): PASS
- Typecheck (mypy, TypeScript): PASS
- No TODO/FIXME/placeholder code
- All debug run failures resolved

**Acceptance Criteria Status:**
- AC-01 (Model health/sample/report): 🚫 BLOCKED (BGE-M3 HTTP 402)
- AC-02 (LLM context support): 🚫 BLOCKED (Human/legal review pending)
- AC-03 (Speed definition): ✅ PASS
- AC-04 (Embedding < 1B): 🚫 BLOCKED (BGE-M3 comparison incomplete)
- AC-05 (No OOM): ✅ PASS
- AC-06 (License recorded): 🚫 BLOCKED (BGE-M3 license unavailable)

**Blockers (All External):**
1. **BGE-M3 NGC Access**: HTTP 402 (payment/entitlement required) - cannot be resolved by code
2. **LLM Winner Human/Legal Review**: Pending external approval - cannot be automated

**Evidence Collected:**
- ✅ Llama 3.1 8B: Full benchmark, quality, context tests (32K/64K/128K)
- ✅ Nemotron Nano 9B: Full benchmark, quality, context tests (32K/64K/128K)
- ✅ Embed 300M: Runtime verification, semantic sanity, license
- ✅ Rerank 500M: Runtime verification, semantic ordering, license
- ✅ Both LLM combinations (Llama/Nemotron + Embed + Rerank): No OOM, healthy
- ✅ Scorecard generated with provisional scores
- ✅ Metadata correction applied
- ✅ All secrets properly handled

---

## Decision

**We proceed to Phase 4 (Document Ingestion) while Phase 3 remains BLOCKED.**

### Rationale

1. **Phase 3 Implementation is Complete**
   - All code written, tested, and verified
   - No technical debt or incomplete implementations
   - All acceptance criteria that CAN be tested have been tested
   - Blockers are purely external dependencies

2. **Phase 4 Does Not Depend on Phase 3 Blockers**
   - Document ingestion/parsing works independently of embedding winner
   - Chunking strategy doesn't require final LLM selection
   - MinIO/RabbitMQ/Celery setup unrelated to model choices
   - Can use provisional Embed 300M for development/testing

3. **Waiting is Unproductive**
   - BGE-M3 entitlement requires NGC purchase decision (business/procurement)
   - Human review timing is uncertain (legal/compliance process)
   - Phase 4 work can proceed in parallel without conflicts

4. **Master Plan Allows Sequential Phases**
   - Phase 4 "10+ tài liệu được parse, normalize và version hóa"
   - This can be achieved with provisional embedding model
   - Phase 5 will finalize embedding winner with full metrics

5. **Risk Mitigation**
   - Phase 4 will NOT hardcode embedding dimension
   - Will use configuration/environment variables for model selection
   - Migration plan documented for when Phase 3 winners are finalized

### Boundary Enforcement

Phase 4 implementation will respect Phase 3 boundaries:

**NOT Allowed in Phase 4:**
- ❌ Claiming an embedding winner before Phase 5 metrics
- ❌ Activating LLM for production application use
- ❌ Hardcoding vector dimensions or model names
- ❌ Making architectural decisions that assume specific model choices

**Allowed in Phase 4:**
- ✅ Using provisional Embed 300M for development
- ✅ Designing schema/chunking that works with 2048-dim vectors
- ✅ Building ingestion pipeline with model config placeholders
- ✅ Testing with available models for pipeline validation

---

## Consequences

### Positive

- Development velocity maintained
- Phase 4 work provides value independently (document processing)
- Team gains experience with Docling/chunking/MinIO patterns
- Reduces critical path when Phase 3 blockers are resolved

### Negative

- Potential rework if Phase 5 selects different embedding (mitigated by config)
- Need to maintain Phase 3 documentation as "technically complete but blocked"
- Must clearly communicate Phase 3 status to stakeholders

### Required Actions

1. **Update Phase 3 Status**
   - Mark as "Implementation Complete, Blocked on External Dependencies"
   - Document exactly what's waiting and who owns resolution

2. **Phase 4 Setup**
   - Create artifacts/phase-4/ directory structure
   - Define acceptance criteria  
   - Set up provisional model configuration

3. **Communication**
   - Inform stakeholders Phase 3 is blocked on business/legal, not engineering
   - Explain Phase 4 can proceed without Phase 3 unblocking

---

## Alternatives Considered

### Alternative 1: Wait for Phase 3 Complete Unblocking
**Rejected**: Could take weeks/months for NGC procurement and legal review. Phase 4 work is independent and valuable.

### Alternative 2: Skip Phase 3 Entirely, Use Defaults
**Rejected**: Phase 3 evidence is critical for production model selection. Must complete properly even if delayed.

### Alternative 3: Mock/Fake Phase 3 Results to Proceed
**Rejected**: Violates master plan requirement "Không dùng ... evidence giả để vượt blocker." Integrity matters.

---

## Status Tracking

**Phase 3 Completion:**
- Implementation Status: ✅ COMPLETE (2026-07-14)
- Acceptance Status: 🚫 BLOCKED (External dependencies)
- Technical Debt: ✅ NONE
- Follow-up Required: 
  - [ ] Obtain BGE-M3 NGC entitlement
  - [ ] Complete human/legal review for LLM winner
  - [ ] Update Phase 3 status to PASS when unblocked

**Phase 4 Authorization:**
- Start Date: 2026-07-14
- Approved By: Engineering decision per ADR-0004
- Prerequisite Override: Phase 3 technically complete, blocked external only

---

## References

- [Phase 3 Acceptance Evidence](../../artifacts/phase-3/acceptance.md)
- [Phase 3 Verification Report](../../PHASE3_VERIFICATION_REPORT.md)
- [Master Plan Phase Definitions](../../NTC_NVIDIA_LOCAL_RAG_CHATBOT_MASTER_PLAN.md)
- [Phase 3 Run: 20260714T1120Z-full-r2](../../artifacts/phase-3/runs/20260714T1120Z-full-r2/)

---

**Conclusion**: Phase 3 is implementation-complete with external blockers only. Phase 4 may proceed as its work is independent and valuable. Model configuration will remain flexible until Phase 3/5 finalize winners.
