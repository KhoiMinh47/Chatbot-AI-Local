#!/usr/bin/env python3
"""Evaluate real retrieval observations against the immutable gold set.

This runner deliberately has no mock/fabricated fallback. If a live retrieval run has
not produced an observation file, it exits non-zero instead of publishing invented
quality metrics.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT_DIR / "packages/rag-eval/src"))

from ntc_rag_eval.io import load_gold_jsonl, load_observations_jsonl  # noqa: E402
from ntc_rag_eval.metrics import evaluate_retrieval  # noqa: E402


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Score measured RAG retrieval observations; never fabricates results."
    )
    parser.add_argument(
        "--gold",
        type=Path,
        default=ROOT_DIR / "benchmarks/phase5/gold.jsonl",
        help="Immutable gold dataset in JSONL format.",
    )
    parser.add_argument(
        "--observations",
        type=Path,
        required=True,
        help="JSONL emitted by a real retrieval run.",
    )
    parser.add_argument(
        "--config-fingerprint",
        required=True,
        help="Version/hash identifying the measured retrieval configuration.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=ROOT_DIR / "evals/reports/retrieval-evaluation.json",
    )
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    for path, label in ((args.gold, "gold dataset"), (args.observations, "observations")):
        if not path.is_file():
            print(f"Missing {label}: {path}", file=sys.stderr)
            return 2

    try:
        gold_samples = load_gold_jsonl(args.gold)
        observations = load_observations_jsonl(args.observations)
        report = evaluate_retrieval(
            gold_samples,
            observations,
            config_fingerprint=args.config_fingerprint,
        )
    except ValueError as error:
        print(f"Evaluation input is invalid: {error}", file=sys.stderr)
        return 2

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "samples": report.total_samples,
                "recall_at_10": report.overall.recall_at_10,
                "mrr_at_10": report.overall.mrr_at_10,
                "p95_ms": report.latency.p95_ms,
                "quality_gate_passed": report.quality_gate_passed,
                "report": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0 if report.quality_gate_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
