#!/usr/bin/env python3
"""Run the provisional Phase 5 Embed-300M chunk grid against live local NIM/Qdrant.

The runner deliberately cannot activate ``ntc_chunks_active`` or claim an
embedding winner. BGE-M3 is still unavailable, so this produces auditable
candidate evidence and a provisional chunk winner only.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import subprocess
import time
import xml.etree.ElementTree as ET
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import NAMESPACE_URL, UUID, uuid5

import httpx2 as httpx
import tiktoken
from app.application.ai_clients import EmbeddingRequest
from app.application.retrieval import DenseRetriever, EmbeddingBatchPipeline
from app.domain.retrieval import AccessScope, ChunkPayload, IndexConfig
from app.infrastructure.nim_clients import NimEmbeddingClient, NimRerankClient
from app.infrastructure.qdrant_store import QdrantVectorIndex
from ntc_rag_eval import (
    GoldSample,
    LabeledScore,
    RetrievalObservation,
    calibrate_threshold,
    evaluate_retrieval,
    load_gold_jsonl,
)

_ENCODING = tiktoken.get_encoding("cl100k_base")
_BENCHMARK_CREATED_AT = datetime(2026, 7, 15, tzinfo=UTC)
_PROVENANCE_PATHS = (
    "scripts/phase5_benchmark.py",
    "scripts/smoke-phase5.sh",
    "apps/api/app/domain/retrieval.py",
    "apps/api/app/application/retrieval.py",
    "apps/api/app/infrastructure/nim_clients.py",
    "apps/api/app/infrastructure/qdrant_store.py",
    "packages/rag-eval/src/ntc_rag_eval/models.py",
    "packages/rag-eval/src/ntc_rag_eval/metrics.py",
    "packages/rag-eval/src/ntc_rag_eval/calibration.py",
    "packages/rag-eval/src/ntc_rag_eval/io.py",
    "tests/test_phase5_qdrant_integration.py",
    "pyproject.toml",
    "uv.lock",
)


@dataclass(frozen=True, slots=True)
class CorpusSection:
    tenant_id: UUID
    owner_id: UUID
    acl_principals: tuple[str, ...]
    document_id: UUID
    version_id: UUID
    source_name: str
    mime_type: str
    language: str
    section_id: str
    section_path: tuple[str, ...]
    page: int | None
    slide: int | None
    code: str
    title_vi: str
    title_en: str
    fact_vi: str
    fact_en: str


@dataclass(frozen=True, slots=True)
class GridSpec:
    sizes: tuple[int, ...]
    overlaps: tuple[int, ...]
    candidate_limit: int
    hnsw_ef: int


def _object(value: object, field_name: str) -> Mapping[str, object]:
    if not isinstance(value, dict):
        raise ValueError(f"{field_name} must be an object")
    return cast(dict[str, object], value)


def _array(value: object, field_name: str) -> list[object]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    return cast(list[object], value)


def _string(value: object, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} must be a non-blank string")
    return value


def _integer(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an integer")
    return value


def _number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"{field_name} must be numeric")
    return float(value)


def _nullable_integer(value: object, field_name: str) -> int | None:
    if value is None:
        return None
    return _integer(value, field_name)


def _read_json(path: Path) -> Mapping[str, object]:
    try:
        parsed: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(f"{path} is invalid JSON: {error.msg}") from None
    return _object(parsed, str(path))


def _load_corpus(path: Path) -> tuple[CorpusSection, ...]:
    sections: list[CorpusSection] = []
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not raw_line.strip():
            raise ValueError(f"{path}:{line_number} must not be blank")
        try:
            parsed: object = json.loads(raw_line)
        except json.JSONDecodeError as error:
            raise ValueError(f"{path}:{line_number} is invalid JSON: {error.msg}") from None
        record = _object(parsed, f"{path}:{line_number}")
        sections.append(
            CorpusSection(
                tenant_id=UUID(_string(record.get("tenant_id"), "tenant_id")),
                owner_id=UUID(_string(record.get("owner_id"), "owner_id")),
                acl_principals=tuple(
                    _string(item, "acl_principals[]")
                    for item in _array(record.get("acl_principals"), "acl_principals")
                ),
                document_id=UUID(_string(record.get("document_id"), "document_id")),
                version_id=UUID(_string(record.get("version_id"), "version_id")),
                source_name=_string(record.get("source_name"), "source_name"),
                mime_type=_string(record.get("mime_type"), "mime_type"),
                language=_string(record.get("language"), "language"),
                section_id=_string(record.get("section_id"), "section_id"),
                section_path=tuple(
                    _string(item, "section_path[]")
                    for item in _array(record.get("section_path"), "section_path")
                ),
                page=_nullable_integer(record.get("page"), "page"),
                slide=_nullable_integer(record.get("slide"), "slide"),
                code=_string(record.get("code"), "code"),
                title_vi=_string(record.get("title_vi"), "title_vi"),
                title_en=_string(record.get("title_en"), "title_en"),
                fact_vi=_string(record.get("fact_vi"), "fact_vi"),
                fact_en=_string(record.get("fact_en"), "fact_en"),
            )
        )
    if not sections:
        raise ValueError("corpus must not be empty")
    if len({section.section_id for section in sections}) != len(sections):
        raise ValueError("corpus section_id values must be unique")
    tenants = {section.tenant_id for section in sections}
    if len(tenants) != 1:
        raise ValueError("benchmark quality corpus must use one tenant")
    return tuple(sections)


def _grid_spec(config: Mapping[str, object]) -> GridSpec:
    grid = _object(config.get("chunk_grid"), "chunk_grid")
    retrieval = _object(config.get("retrieval"), "retrieval")
    sizes = tuple(
        _integer(item, "chunk_grid.sizes[]") for item in _array(grid.get("sizes"), "sizes")
    )
    overlaps = tuple(
        _integer(item, "chunk_grid.overlap_percent[]")
        for item in _array(grid.get("overlap_percent"), "overlap_percent")
    )
    if sizes != (256, 512, 768, 1024) or overlaps != (0, 10, 20):
        raise ValueError("Phase 5 acceptance requires the exact master-plan chunk grid")
    return GridSpec(
        sizes=sizes,
        overlaps=overlaps,
        candidate_limit=_integer(retrieval.get("dense_candidate_limit"), "candidate_limit"),
        hnsw_ef=_integer(retrieval.get("hnsw_ef"), "hnsw_ef"),
    )


def render_section(section: CorpusSection, *, repetitions: int = 14) -> str:
    """Render a deterministic bilingual section long enough to exercise the chunk grid."""

    if isinstance(repetitions, bool) or repetitions < 1:
        raise ValueError("repetitions must be a positive integer")
    paragraphs = [
        (
            f"{section.code} — {section.title_vi} / {section.title_en}. "
            f"Quy định chính thức: {section.fact_vi} Official requirement: {section.fact_en}"
        )
    ]
    for number in range(1, repetitions + 1):
        paragraphs.append(
            f"Ghi chú kiểm soát {number} cho mục {section.code}: {section.fact_vi} "
            f"Không suy diễn sang mục khác. Control note {number} for {section.code}: "
            f"{section.fact_en} Do not substitute a neighboring policy code."
        )
    return "\n\n".join(paragraphs)


def build_chunk_payloads(section: CorpusSection, config: IndexConfig) -> tuple[ChunkPayload, ...]:
    """Apply an exact token window inside one structure-aware section boundary."""

    prefix = f"{section.section_id} | {section.code} | {section.title_vi} | {section.title_en}\n"
    prefix_tokens = _ENCODING.encode(prefix)
    capacity = config.chunk_size - len(prefix_tokens)
    if capacity <= 0:
        raise ValueError("section prefix consumes the entire chunk budget")
    body_tokens = _ENCODING.encode(render_section(section))
    parent_id = uuid5(NAMESPACE_URL, f"{config.index_version}:{section.section_id}:parent")
    payloads: list[ChunkPayload] = []
    start = 0
    ordinal = 0
    while start < len(body_tokens):
        end = min(start + capacity, len(body_tokens))
        text = prefix + _ENCODING.decode(body_tokens[start:end])
        # Prefix/body token boundaries can merge or split when encoded as one
        # string. Shrink against the exact final encoding instead of assuming
        # token counts are additive.
        while end > start and len(_ENCODING.encode(text)) > config.chunk_size:
            end -= 1
            text = prefix + _ENCODING.decode(body_tokens[start:end])
        if end == start:
            raise RuntimeError("section prefix leaves no usable body token budget")
        chunk_id = uuid5(
            NAMESPACE_URL,
            f"{config.index_version}:{section.section_id}:{ordinal}:{hashlib.sha256(text.encode()).hexdigest()}",
        )
        token_count = len(_ENCODING.encode(text))
        if token_count > config.chunk_size:
            raise RuntimeError("rendered chunk exceeds configured token size")
        payloads.append(
            ChunkPayload(
                tenant_id=section.tenant_id,
                document_id=section.document_id,
                version_id=section.version_id,
                chunk_id=chunk_id,
                parent_id=parent_id,
                owner_id=section.owner_id,
                acl_principals=section.acl_principals,
                source_name=section.source_name,
                mime_type=section.mime_type,
                page=section.page,
                slide=section.slide,
                section_path=(section.section_id, *section.section_path),
                language=section.language,
                text=text,
                token_count=token_count,
                content_hash=hashlib.sha256(text.encode()).hexdigest(),
                index_version=config.index_version,
                created_at=_BENCHMARK_CREATED_AT,
            )
        )
        ordinal += 1
        if end == len(body_tokens):
            break
        actual_capacity = end - start
        overlap_tokens = round(actual_capacity * config.overlap_percent / 100)
        next_start = end - overlap_tokens
        if next_start <= start:
            raise RuntimeError("chunk overlap leaves no forward progress")
        start = next_start
    return tuple(payloads)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _source_provenance(repository_root: Path) -> dict[str, object]:
    hashes: dict[str, str] = {}
    for relative_path in _PROVENANCE_PATHS:
        source_path = repository_root / relative_path
        if not source_path.is_file():
            raise ValueError(f"provenance source is missing: {relative_path}")
        hashes[relative_path] = _sha256_file(source_path)

    try:
        git_result = subprocess.run(
            ["git", "-C", str(repository_root), "rev-parse", "HEAD"],
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError:
        git_result = None
    git_commit = (
        git_result.stdout.strip() if git_result is not None and git_result.returncode == 0 else None
    )
    return {
        "git_commit": git_commit,
        "git_commit_unavailable_reason": (
            None if git_commit is not None else "workspace is not a Git worktree"
        ),
        "source_sha256": hashes,
    }


def _junit_evidence(path: Path) -> dict[str, object]:
    try:
        root = ET.parse(path).getroot()
    except (OSError, ET.ParseError) as error:
        raise ValueError(f"Qdrant contract evidence is not valid JUnit XML: {error}") from None
    suites = [element for element in root.iter() if element.tag.rsplit("}", 1)[-1] == "testsuite"]
    if not suites:
        raise ValueError("Qdrant contract evidence contains no testsuite")
    totals: dict[str, int] = {}
    for field_name in ("tests", "failures", "errors", "skipped"):
        try:
            totals[field_name] = sum(int(suite.attrib.get(field_name, "0")) for suite in suites)
        except ValueError:
            raise ValueError(
                f"Qdrant contract evidence has a non-integer {field_name} count"
            ) from None
    if (
        totals["tests"] < 1
        or totals["failures"] != 0
        or totals["errors"] != 0
        or totals["skipped"] != 0
    ):
        raise ValueError("Qdrant ACL/dimension contract test did not pass without skips")
    return {
        "kind": "pytest-junit",
        "path": str(path),
        "sha256": _sha256_file(path),
        **totals,
        "acl_leakage_expected": 0,
        "result": "passed",
    }


async def _qdrant_identity(base_url: str) -> dict[str, str]:
    async with httpx.AsyncClient(base_url=f"{base_url.rstrip('/')}/", trust_env=False) as client:
        response = await client.get("")
    if response.status_code != 200:
        raise RuntimeError(f"Qdrant identity endpoint returned HTTP {response.status_code}")
    try:
        parsed: object = response.json()
    except (ValueError, UnicodeDecodeError):
        raise RuntimeError("Qdrant identity endpoint returned invalid JSON") from None
    document = _object(parsed, "Qdrant identity")
    return {
        "title": _string(document.get("title"), "Qdrant identity.title"),
        "version": _string(document.get("version"), "Qdrant identity.version"),
        "commit": _string(document.get("commit"), "Qdrant identity.commit"),
    }


def _json_dump(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _write_exclusive(path: Path, content: str) -> None:
    with path.open("x", encoding="utf-8") as target:
        target.write(content)


def _write_observations(path: Path, observations: Sequence[RetrievalObservation]) -> None:
    content = "".join(
        json.dumps(asdict(observation), ensure_ascii=False, separators=(",", ":")) + "\n"
        for observation in observations
    )
    _write_exclusive(path, content)


def _deduplicated_observation(
    sample_id: str,
    ranked_section_scores: Sequence[tuple[str, float]],
    latency_ms: float,
) -> RetrievalObservation:
    ids: list[str] = []
    scores: list[float] = []
    seen: set[str] = set()
    for section_id, score in ranked_section_scores:
        if section_id in seen:
            continue
        seen.add(section_id)
        ids.append(section_id)
        scores.append(score)
    return RetrievalObservation(
        sample_id=sample_id,
        retrieved_ids=tuple(ids),
        scores=tuple(scores),
        latency_ms=latency_ms,
    )


async def _embed_queries(
    embedding: NimEmbeddingClient,
    samples: Sequence[GoldSample],
    *,
    model: str,
    model_version: str,
    dimension: int,
    batch_size: int = 16,
) -> dict[str, tuple[float, ...]]:
    vectors: dict[str, tuple[float, ...]] = {}
    for offset in range(0, len(samples), batch_size):
        batch = samples[offset : offset + batch_size]
        response = await embedding.embed(
            EmbeddingRequest(
                texts=tuple(sample.question for sample in batch),
                input_type="query",
                truncate="NONE",
            )
        )
        if response.model != model or response.dimension != dimension:
            raise RuntimeError("query embedding identity or dimension drifted")
        if response.model_version is not None and response.model_version != model_version:
            raise RuntimeError("query embedding model version drifted")
        if len(response.vectors) != len(batch):
            raise RuntimeError("query embedding count mismatch")
        for sample, vector in zip(batch, response.vectors, strict=True):
            vectors[sample.id] = vector
    return vectors


def _calibrate(
    samples: Sequence[GoldSample],
    observations: Sequence[RetrievalObservation],
) -> tuple[dict[str, object], tuple[RetrievalObservation, ...]]:
    sample_map = {sample.id: sample for sample in samples}
    labeled: list[LabeledScore] = []
    for observation in observations:
        sample = sample_map[observation.sample_id]
        relevant = set(sample.gold_chunk_or_section_ids)
        labeled.extend(
            LabeledScore(score, sample.answerable and item_id in relevant)
            for item_id, score in zip(observation.retrieved_ids, observation.scores, strict=True)
        )
    calibration = calibrate_threshold(tuple(labeled))
    thresholded = tuple(
        RetrievalObservation(
            sample_id=observation.sample_id,
            retrieved_ids=tuple(
                item_id
                for item_id, score in zip(
                    observation.retrieved_ids, observation.scores, strict=True
                )
                if score >= calibration.threshold
            ),
            scores=tuple(score for score in observation.scores if score >= calibration.threshold),
            latency_ms=observation.latency_ms,
        )
        for observation in observations
    )
    result = asdict(calibration)
    result["method"] = "max_f1_same_fixture_provisional_not_held_out"
    return result, thresholded


async def _grid_observations(
    *,
    qdrant: QdrantVectorIndex,
    config: IndexConfig,
    samples: Sequence[GoldSample],
    query_vectors: Mapping[str, tuple[float, ...]],
    scope: AccessScope,
    candidate_limit: int,
) -> tuple[RetrievalObservation, ...]:
    observations: list[RetrievalObservation] = []
    for sample in samples:
        started = time.perf_counter()
        hits = await qdrant.search(
            config,
            query_vectors[sample.id],
            scope,
            limit=candidate_limit,
            score_threshold=None,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        observations.append(
            _deduplicated_observation(
                sample.id,
                tuple((hit.payload.section_path[0], hit.score) for hit in hits),
                latency_ms,
            )
        )
    return tuple(observations)


async def _online_observations(
    *,
    retriever: DenseRetriever,
    config: IndexConfig,
    samples: Sequence[GoldSample],
    scope: AccessScope,
    candidate_limit: int,
) -> tuple[RetrievalObservation, ...]:
    observations: list[RetrievalObservation] = []
    for sample in samples:
        started = time.perf_counter()
        result = await retriever.retrieve(
            query=sample.question,
            scope=scope,
            config=config,
            candidate_limit=candidate_limit,
            final_limit=10,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        observations.append(
            _deduplicated_observation(
                sample.id,
                tuple(
                    (
                        ranked.hit.payload.section_path[0],
                        ranked.hit.score if ranked.rerank_score is None else ranked.rerank_score,
                    )
                    for ranked in result.hits
                ),
                latency_ms,
            )
        )
    return tuple(observations)


def select_provisional_chunk_winner(results: Sequence[Mapping[str, object]]) -> int:
    """Select only the best chunk config for one candidate embedding."""

    if not results:
        raise ValueError("grid results must not be empty")

    def score(item: Mapping[str, object]) -> tuple[float, ...]:
        evaluation = _object(item.get("raw_evaluation"), "raw_evaluation")
        overall = _object(evaluation.get("overall"), "raw_evaluation.overall")
        latency = _object(evaluation.get("latency"), "raw_evaluation.latency")
        chunk_size = _integer(item.get("chunk_size"), "chunk_size")
        overlap = _integer(item.get("overlap_percent"), "overlap_percent")
        return (
            _number(overall["recall_at_10"], "recall_at_10"),
            _number(overall["mrr_at_10"], "mrr_at_10"),
            _number(overall["ndcg_at_10"], "ndcg_at_10"),
            _number(overall["context_precision_at_10"], "context_precision_at_10"),
            -_number(latency["p95_ms"], "p95_ms"),
            -float(chunk_size),
            -float(overlap),
        )

    return max(range(len(results)), key=lambda index: score(results[index]))


def select_reranker_policy(
    dense_report: Mapping[str, object],
    rerank_report: Mapping[str, object] | None,
) -> tuple[str, str]:
    """Enable reranking only for material quality gain without gate/latency regression."""

    if rerank_report is None:
        return "off", "Reranker benchmark was not run."
    dense_raw = _object(dense_report.get("raw_evaluation"), "dense raw evaluation")
    rerank_raw = _object(rerank_report.get("raw_evaluation"), "rerank raw evaluation")
    dense_raw_overall = _object(dense_raw.get("overall"), "dense raw overall")
    rerank_raw_overall = _object(rerank_raw.get("overall"), "rerank raw overall")
    dense_threshold = _object(
        dense_report.get("threshold_evaluation"), "dense threshold evaluation"
    )
    rerank_threshold = _object(
        rerank_report.get("threshold_evaluation"), "rerank threshold evaluation"
    )
    dense_threshold_overall = _object(dense_threshold.get("overall"), "dense threshold overall")
    rerank_threshold_overall = _object(rerank_threshold.get("overall"), "rerank threshold overall")
    dense_latency = _object(dense_raw.get("latency"), "dense latency")
    rerank_latency = _object(rerank_raw.get("latency"), "rerank latency")
    rerank_gate = rerank_threshold.get("quality_gate_passed") is True
    no_threshold_regression = all(
        _number(rerank_threshold_overall[metric], f"rerank {metric}")
        >= _number(dense_threshold_overall[metric], f"dense {metric}")
        for metric in ("recall_at_10", "mrr_at_10", "ndcg_at_10")
    )
    material_raw_gain = (
        _number(rerank_raw_overall["ndcg_at_10"], "rerank ndcg_at_10")
        - _number(dense_raw_overall["ndcg_at_10"], "dense ndcg_at_10")
        >= 0.01
    )
    latency_ratio = _number(rerank_latency["p95_ms"], "rerank p95_ms") / _number(
        dense_latency["p95_ms"], "dense p95_ms"
    )
    if rerank_gate and no_threshold_regression and material_raw_gain and latency_ratio <= 2:
        return "rerank500m-v2", "Reranking passed the calibrated gate with material quality gain."
    return (
        "off",
        "Reranking did not meet the material-gain, calibrated no-regression, and <=2x p95 "
        "latency policy.",
    )


async def _alias_target(qdrant_url: str, alias_name: str) -> str | None:
    async with httpx.AsyncClient(base_url=f"{qdrant_url.rstrip('/')}/", trust_env=False) as client:
        response = await client.get("aliases")
        if response.status_code != 200:
            raise RuntimeError(f"Qdrant alias inspection returned HTTP {response.status_code}")
        root = _object(response.json(), "aliases response")
        result = _object(root.get("result"), "aliases result")
        for item in _array(result.get("aliases"), "aliases"):
            alias = _object(item, "alias")
            if alias.get("alias_name") == alias_name:
                return _string(alias.get("collection_name"), "collection_name")
    return None


async def _delete_collection(qdrant_url: str, collection_name: str) -> None:
    if not collection_name.startswith("ntc_p5_"):
        raise RuntimeError(
            "refusing to delete a collection outside the Phase 5 benchmark namespace"
        )
    async with httpx.AsyncClient(base_url=f"{qdrant_url.rstrip('/')}/", trust_env=False) as client:
        response = await client.delete(f"collections/{collection_name}")
        if response.status_code not in {200, 404}:
            raise RuntimeError(
                f"Qdrant cleanup for {collection_name} returned HTTP {response.status_code}"
            )


def _render_markdown(report: Mapping[str, object]) -> str:
    rows = [
        "# Phase 5 provisional retrieval benchmark",
        "",
        f"- Status: **{report['status']}**",
        f"- Run ID: `{report['run_id']}`",
        "- Scope: Embed-300M chunk grid plus optional Rerank-500M; BGE-M3 unavailable.",
        "- Active alias changed: **No**",
        "",
        "| Chunk | Overlap | Recall@10 | MRR@10 | nDCG@10 | p95 Qdrant ms |",
        "|---:|---:|---:|---:|---:|---:|",
    ]
    for item_value in cast(list[object], report["grid_results"]):
        item = _object(item_value, "grid result")
        evaluation = _object(item["raw_evaluation"], "raw evaluation")
        overall = _object(evaluation["overall"], "overall")
        latency = _object(evaluation["latency"], "latency")
        rows.append(
            f"| {item['chunk_size']} | {item['overlap_percent']}% | "
            f"{_number(overall['recall_at_10'], 'recall_at_10'):.4f} | "
            f"{_number(overall['mrr_at_10'], 'mrr_at_10'):.4f} | "
            f"{_number(overall['ndcg_at_10'], 'ndcg_at_10'):.4f} | "
            f"{_number(latency['p95_ms'], 'p95_ms'):.2f} |"
        )
    winner = _object(report["provisional_chunk_winner"], "provisional winner")
    candidate = _object(report["provisional_candidate_config"], "provisional config")
    rows.extend(
        [
            "",
            "## Provisional chunk winner",
            "",
            f"`chunk_size={winner['chunk_size']}, overlap={winner['overlap_percent']}%`.",
            "This is not an embedding winner and is not authorized for the active alias.",
            f"Provisional retrieval policy: reranker `{candidate['reranker']}`, "
            f"score threshold `{candidate['score_threshold']}`.",
            f"Reason: {candidate['reason']}",
            "",
            "## Blocking gates",
            "",
            "- BGE-M3 exact runtime remains blocked by NGC HTTP 402, so the embedding "
            "bake-off is incomplete.",
            "- Phase 4 does not yet provide a verified 10+ document end-to-end corpus.",
            "- `ntc_chunks_active` was inspected before/after and never mutated.",
            "",
        ]
    )
    return "\n".join(rows)


async def run(args: argparse.Namespace) -> int:
    repository_root = Path(__file__).resolve().parent.parent
    config_path = args.config.resolve()
    corpus_path = args.corpus.resolve()
    gold_path = args.gold.resolve()
    qdrant_contract_junit = args.qdrant_contract_junit.resolve()
    output_dir = args.output_dir.resolve()
    source_provenance = _source_provenance(repository_root)
    security_evidence = _junit_evidence(qdrant_contract_junit)
    config_document = _read_json(config_path)
    grid = _grid_spec(config_document)
    sections = _load_corpus(corpus_path)
    samples = load_gold_jsonl(gold_path)
    if len(sections) != 50 or len(samples) != 100:
        raise ValueError("Phase 5 fixture requires exactly 50 sections and 100 gold samples")
    section_ids = {section.section_id for section in sections}
    if any(
        not set(sample.gold_chunk_or_section_ids).issubset(section_ids)
        for sample in samples
        if sample.answerable
    ):
        raise ValueError("gold data references a section absent from the corpus")

    output_dir.mkdir(parents=True, exist_ok=False)
    observations_dir = output_dir / "observations"
    observations_dir.mkdir()
    started_at = datetime.now(UTC)
    run_id = output_dir.name
    alias_name = _string(config_document.get("collection_alias"), "collection_alias")
    alias_before = await _alias_target(args.qdrant_url, alias_name)
    qdrant_identity = await _qdrant_identity(args.qdrant_url)
    created_collections: list[str] = []

    embedding = NimEmbeddingClient(
        api_base_url=args.embedding_base_url,
        model=args.embedding_model,
        model_version=args.embedding_version,
        expected_dimension=args.dimension,
        max_batch_size=args.embedding_batch_size,
        timeout_seconds=300,
    )
    qdrant = QdrantVectorIndex(
        base_url=args.qdrant_url,
        hnsw_ef=grid.hnsw_ef,
        timeout_seconds=60,
    )
    reranking = (
        None
        if args.rerank_base_url is None
        else NimRerankClient(
            api_base_url=args.rerank_base_url,
            model=args.rerank_model,
            model_version=args.rerank_version,
            timeout_seconds=300,
        )
    )
    try:
        query_vectors = await _embed_queries(
            embedding,
            samples,
            model=args.embedding_model,
            model_version=args.embedding_version,
            dimension=args.dimension,
            batch_size=args.embedding_batch_size,
        )
        scope = AccessScope(
            tenant_id=sections[0].tenant_id,
            acl_principals=("group:phase5-eval",),
        )
        grid_results: list[dict[str, object]] = []
        configs: list[IndexConfig] = []
        for chunk_size in grid.sizes:
            for overlap in grid.overlaps:
                collection_name = (
                    f"ntc_p5_embed300m_s{chunk_size}_o{overlap}_{run_id.lower()}".replace("-", "_")[
                        :128
                    ]
                )
                index_version = f"embed300m-v2_s{chunk_size}_o{overlap}_{run_id}"
                index_config = IndexConfig(
                    collection_name=collection_name,
                    index_version=index_version,
                    embedding_model=args.embedding_model,
                    embedding_model_version=args.embedding_version,
                    vector_dimension=args.dimension,
                    chunk_size=chunk_size,
                    overlap_percent=overlap,
                )
                configs.append(index_config)
                chunks = tuple(
                    chunk
                    for section in sections
                    for chunk in build_chunk_payloads(section, index_config)
                )
                pipeline = EmbeddingBatchPipeline(
                    embedding=embedding,
                    vector_index=qdrant,
                    batch_size=args.embedding_batch_size,
                )
                indexing = await pipeline.index(index_config, chunks)
                created_collections.append(collection_name)
                observations = await _grid_observations(
                    qdrant=qdrant,
                    config=index_config,
                    samples=samples,
                    query_vectors=query_vectors,
                    scope=scope,
                    candidate_limit=grid.candidate_limit,
                )
                calibration, thresholded = _calibrate(samples, observations)
                raw_evaluation = evaluate_retrieval(
                    samples, observations, config_fingerprint=index_config.fingerprint
                )
                threshold_evaluation = evaluate_retrieval(
                    samples, thresholded, config_fingerprint=index_config.fingerprint
                )
                observation_name = f"s{chunk_size}_o{overlap}.jsonl"
                _write_observations(observations_dir / observation_name, observations)
                grid_results.append(
                    {
                        "chunk_size": chunk_size,
                        "overlap_percent": overlap,
                        "collection_name": collection_name,
                        "index_version": index_version,
                        "config_fingerprint": index_config.fingerprint,
                        "chunk_count": len(chunks),
                        "indexing": asdict(indexing),
                        "raw_evaluation": raw_evaluation.to_dict(),
                        "threshold_calibration": calibration,
                        "threshold_evaluation": threshold_evaluation.to_dict(),
                        "latency_scope": "qdrant_query_only_with_precomputed_query_embeddings",
                        "observations_file": f"observations/{observation_name}",
                    }
                )

        winner_index = select_provisional_chunk_winner(grid_results)
        winner_result = grid_results[winner_index]
        winner_config = configs[winner_index]
        dense_retriever = DenseRetriever(embedding=embedding, vector_index=qdrant)
        online_dense = await _online_observations(
            retriever=dense_retriever,
            config=winner_config,
            samples=samples,
            scope=scope,
            candidate_limit=grid.candidate_limit,
        )
        dense_calibration, dense_thresholded = _calibrate(samples, online_dense)
        _write_observations(observations_dir / "winner-online-dense.jsonl", online_dense)
        online_dense_report = {
            "raw_evaluation": evaluate_retrieval(
                samples, online_dense, config_fingerprint=winner_config.fingerprint
            ).to_dict(),
            "threshold_calibration": dense_calibration,
            "threshold_evaluation": evaluate_retrieval(
                samples, dense_thresholded, config_fingerprint=winner_config.fingerprint
            ).to_dict(),
            "latency_scope": "client_observed_query_embedding_plus_qdrant",
            "observations_file": "observations/winner-online-dense.jsonl",
        }

        online_rerank_report: dict[str, object] | None = None
        if reranking is not None:
            rerank_retriever = DenseRetriever(
                embedding=embedding,
                vector_index=qdrant,
                reranking=reranking,
            )
            online_rerank = await _online_observations(
                retriever=rerank_retriever,
                config=winner_config,
                samples=samples,
                scope=scope,
                candidate_limit=grid.candidate_limit,
            )
            rerank_calibration, rerank_thresholded = _calibrate(samples, online_rerank)
            _write_observations(observations_dir / "winner-online-rerank.jsonl", online_rerank)
            online_rerank_report = {
                "raw_evaluation": evaluate_retrieval(
                    samples, online_rerank, config_fingerprint=winner_config.fingerprint
                ).to_dict(),
                "threshold_calibration": rerank_calibration,
                "threshold_evaluation": evaluate_retrieval(
                    samples, rerank_thresholded, config_fingerprint=winner_config.fingerprint
                ).to_dict(),
                "latency_scope": "client_observed_query_embedding_plus_qdrant_plus_reranker",
                "observations_file": "observations/winner-online-rerank.jsonl",
            }

        selected_reranker, reranker_reason = select_reranker_policy(
            online_dense_report, online_rerank_report
        )
        selected_calibration = (
            dense_calibration
            if selected_reranker == "off" or online_rerank_report is None
            else _object(
                online_rerank_report["threshold_calibration"],
                "rerank threshold calibration",
            )
        )

        alias_after = await _alias_target(args.qdrant_url, alias_name)
        if alias_after != alias_before:
            raise RuntimeError("active Qdrant alias changed during a non-activation benchmark")
        report: dict[str, object] = {
            "schema_version": 1,
            "status": "BLOCKED",
            "run_id": run_id,
            "started_at": started_at.isoformat(),
            "completed_at": datetime.now(UTC).isoformat(),
            "inputs": {
                "config_path": str(config_path),
                "config_sha256": _sha256_file(config_path),
                "corpus_path": str(corpus_path),
                "corpus_sha256": _sha256_file(corpus_path),
                "gold_path": str(gold_path),
                "gold_sha256": _sha256_file(gold_path),
                "corpus_sections": len(sections),
                "gold_samples": len(samples),
            },
            "source_provenance": source_provenance,
            "runtime_identity": {"qdrant": qdrant_identity},
            "security_evidence": security_evidence,
            "embedding_candidate": {
                "model": args.embedding_model,
                "model_version": args.embedding_version,
                "dimension": args.dimension,
                "winner_eligible": False,
            },
            "grid_results": grid_results,
            "provisional_chunk_winner": {
                "chunk_size": winner_result["chunk_size"],
                "overlap_percent": winner_result["overlap_percent"],
                "collection_name": winner_result["collection_name"],
                "config_fingerprint": winner_result["config_fingerprint"],
                "selection_order": [
                    "Recall@10 desc",
                    "MRR@10 desc",
                    "nDCG@10 desc",
                    "context precision@10 desc",
                    "Qdrant p95 latency asc",
                    "chunk size asc",
                    "overlap asc",
                ],
                "activation_authorized": False,
            },
            "online_dense": online_dense_report,
            "online_rerank": online_rerank_report,
            "provisional_candidate_config": {
                "embedding": "embed300m-v2",
                "chunk_size": winner_result["chunk_size"],
                "overlap_percent": winner_result["overlap_percent"],
                "reranker": selected_reranker,
                "score_threshold": selected_calibration["threshold"],
                "reason": reranker_reason,
                "winner_eligible": False,
                "activation_authorized": False,
            },
            "embedding_bakeoff": {
                "complete": False,
                "missing_candidate": "baai/bge-m3",
                "blocker": "authenticated NGC registry scope returned HTTP 402",
            },
            "alias_guard": {
                "alias": alias_name,
                "before": alias_before,
                "after": alias_after,
                "changed": False,
            },
            "limitations": [
                "Synthetic non-sensitive benchmark corpus; not verified Phase 4 parser output.",
                "Threshold calibration and evaluation use the same fixture and are provisional.",
                "Grid latency excludes query embedding; online winner latency reports include it.",
                "No embedding winner or active alias is selected while BGE-M3 is unavailable.",
            ],
        }
        _write_exclusive(output_dir / "report.json", _json_dump(report))
        _write_exclusive(output_dir / "report.md", _render_markdown(report))
    finally:
        cleanup_errors: list[str] = []
        for collection_name in created_collections:
            try:
                await _delete_collection(args.qdrant_url, collection_name)
            except RuntimeError as error:
                cleanup_errors.append(str(error))
        if reranking is not None:
            await reranking.aclose()
        await qdrant.aclose()
        await embedding.aclose()
        if cleanup_errors:
            raise RuntimeError("; ".join(cleanup_errors))
    return 3


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("benchmarks/phase5/config.json"))
    parser.add_argument("--corpus", type=Path, default=Path("benchmarks/phase5/corpus.jsonl"))
    parser.add_argument("--gold", type=Path, default=Path("benchmarks/phase5/gold.jsonl"))
    parser.add_argument("--qdrant-contract-junit", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--qdrant-url", required=True)
    parser.add_argument("--embedding-base-url", required=True)
    parser.add_argument("--embedding-model", default="nvidia/llama-nemotron-embed-300m-v2")
    parser.add_argument("--embedding-version", default="1.13.0")
    parser.add_argument("--dimension", type=int, default=2048)
    parser.add_argument("--embedding-batch-size", type=int, default=16)
    parser.add_argument("--rerank-base-url")
    parser.add_argument("--rerank-model", default="nvidia/llama-nemotron-rerank-500m-v2")
    parser.add_argument("--rerank-version", default="1.10.0")
    return parser.parse_args()


def main() -> int:
    try:
        return asyncio.run(run(parse_args()))
    except (OSError, ValueError, RuntimeError) as error:
        print(f"phase5 benchmark failed: {error}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
