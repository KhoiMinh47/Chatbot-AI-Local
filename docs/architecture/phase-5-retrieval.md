# Phase 5 embedding, Qdrant và retrieval benchmark

- Trạng thái: **PASS / winner activated** cho local engineering
- Ngày kiểm chứng: 2026-07-15
- Phạm vi: chỉ Phase 5; generation/refusal/citation thuộc Phase 6
- Evidence chuẩn:
  `artifacts/phase-5/runs/20260715T022157Z-embed300m-final-r3`

## Data flow

```text
Phase 4 READY current child chunks
  -> Embed-300M passage embeddings
  -> immutable physical Qdrant collection
  -> payload + 2048-dimension vector upsert

query + AccessScope
  -> Embed-300M query embedding
  -> Qdrant alias ntc_chunks_active
  -> tenant + ACL + index-version + child-type filters
  -> fail-closed response validation
  -> deduplicate/diversify
  -> calibrated threshold
  -> final top 10 chunks
```

Finalization dùng 10 READY document, 10 current version và 12 child chunk từ
authoritative Phase 4 PostgreSQL rows. It does not reconstruct synthetic corpus
text inside the Phase 5 runner.

## Winner index contract

A physical collection is bound to the exact tuple:

```text
embedding model + model version + vector dimension + distance
+ chunk size + overlap + index version
```

Activated values:

```text
embedding: nvidia/llama-nemotron-embed-300m-v2
version: 1.13.0
dimension / distance: 2048 / Cosine
chunk / overlap: 256 / 10%
index version: embed300m-v2-phase4
physical collection: ntc_chunks_embed300m_v2_s256_o10_095bc081a101_recall95_v3
index fingerprint: a3cc25bb8e65a03ac1146c227c4c2b8c5a86370f4852eb35eb4d66330dd20290
points / status: 12 / green
```

`QdrantVectorIndex.ensure_collection()` reads the stored metadata before any
upsert. Dimension, distance, model/version or other index-config drift fails
with `CollectionContractError`; the adapter requires a new physical collection
instead of mutating the existing one.

## Retrieval policy contract

The active index is not sufficient to reproduce retrieval by itself. The exact
retrieval policy is separately fingerprinted:

```text
dense candidate limit: 20
final limit: 10
dense threshold: 0.2300481
hnsw_ef: 128
reranker: off
dedup: content_hash_and_document_section_v1
policy fingerprint: 37a6fb7d83d292ba67f7709ce5e8e77483a73b86cd470938486d37b2d38c65b8
```

`RetrievalPolicy` binds the index fingerprint plus every value above. Phase 6
must load the physical index contract through `ntc_chunks_active` and verify the
policy fingerprint; using only the alias or model name is not a complete
configuration binding.

Deduplication/diversification runs on the full dense candidate set before
`final_limit`, so overlapping chunks from one document/section cannot consume
the final window. Reranker is disabled in the winner policy; enabling it creates
a different policy fingerprint and needs new evidence.

## ACL and payload contract

Each point stores tenant/document/version/chunk/parent/owner IDs, ACL principals,
source MIME/name, page/slide/section path, language, full chunk text, token count,
content hash, index version, creation time and child type. Filter fields have
Qdrant payload indexes.

Every search applies Qdrant `must` filters for:

1. exact `tenant_id`;
2. caller `acl_principals` intersection;
3. exact `index_version`;
4. exact `chunk_type=child`;
5. optional `document_id` allow-list.

Returned points are validated again. Any out-of-scope tenant, ACL, document,
index version or non-child point fails closed. The canonical live integration
test uses two tenants and two users, proves each scope receives only its own
point, proves dimension/model drift is rejected, cleans its temporary
collection and leaves `ntc_chunks_active` unchanged.

## Gold, calibration and evaluation

Gold SHA-256:
`393c9147f6a59a41e1a038a7622dc7d4183571fb4a1aa3a1940514629c155ca3`.
It contains 100 cases over all ten Phase 4 sources:

- 50 calibration: 40 answerable, 10 unanswerable;
- 50 held-out evaluation: 40 answerable, 10 unanswerable;
- 75 English, 25 Vietnamese.

The threshold is fit only on calibration scores. The method selects the most
precise threshold that preserves minimum recall `0.95`; this yields threshold
`0.2300481`, calibration precision `0.8667`, recall `0.975`, F1 `0.9176`.
The max-F1-only threshold `0.3152053` is retained as a diagnostic, not selected,
because its calibration recall is only `0.875` and `r2` failed held-out recall.

The evaluation split was not used to compute the numeric threshold, but the
failed `r2` result did inform the switch from max-F1 to a recall-first objective.
It is therefore regression evidence, not an untouched release holdout. A fresh,
frozen release test set remains a Phase 12 requirement.

Held-out approved-policy metrics:

```text
Recall@5/10: 1.0 / 1.0
MRR@10: 1.0
nDCG@10: 1.0
context precision@10: 0.9375
p50 / p95: 16.09 / 58.23 ms
unanswerable non-empty rate: 0.1
```

Latency measures the client-side retrieval call, including query embedding,
Qdrant search and policy processing. `unanswerable_nonempty_rate=0.1` means one
of ten unanswerable queries still returned a dense candidate. It is a retrieval
diagnostic, not a generated answer; Phase 6 owns insufficient-evidence refusal.

## Decision and atomic activation

The workflow writes an immutable `decision-report.json` first, hashes those
exact bytes, then constructs `WinnerApproval`. Activation refuses:

- a collection missing or not `green`;
- model/version/dimension/metadata mismatch;
- unexpected point count;
- index or retrieval-policy fingerprint mismatch;
- report SHA mismatch;
- any alias other than `ntc_chunks_active`.

The alias switch is one Qdrant alias action batch followed by read-back. The
canonical receipt records:

```text
previous target: null
active alias: ntc_chunks_active
target/readback: ntc_chunks_embed300m_v2_s256_o10_095bc081a101_recall95_v3
verified: true
```

Decision SHA-256 is
`290d1b34f7c350658207dea14c8e1f045314fc2126c3522adeecf1eea12cb610`;
activation-receipt SHA-256 is
`2b0f68582a8e1398b4507e73a596887fa271cf33308456efeb294225f08fd76f`.

## Explicit BGE-M3 waiver

Exact BGE-M3 NGC access still returns HTTP `402`, so no same-gold BGE comparison
was executed. The workspace operator explicitly selected Embed-300M and waived
that comparison for local engineering activation. The waiver is recorded in
the decision report and must not be described as BGE-M3 passing or losing a
benchmark it never ran.

## Failed-run audit trail

- `r1`: rejected; held-out Recall/MRR/nDCG `0.65`; no alias activation.
- `r2`: rejected; max-F1 threshold `0.3152053`, held-out Recall `0.775`; no
  alias activation.
- `r3`: recall-first calibration and held-out quality pass; decision approved,
  alias activated and verified.

Full acceptance and evidence hashes are in
[`artifacts/phase-5/acceptance.md`](../../artifacts/phase-5/acceptance.md) and
[`artifacts/phase-5/INVENTORY.md`](../../artifacts/phase-5/INVENTORY.md).
