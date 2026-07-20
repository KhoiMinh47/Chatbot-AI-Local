#!/usr/bin/env python3
"""Measured HTTP/SSE benchmark for the running local chatbot.

Authentication and real conversations are mandatory. The script never substitutes a
fake token, a mock observation, or a synthetic latency value.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx


@dataclass(frozen=True, slots=True)
class Result:
    request_index: int
    status_code: int
    ttft_ms: float | None
    total_latency_ms: float
    input_tokens: int | None
    output_tokens: int | None
    citation_count: int
    outcome: str | None
    error: str | None


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    index = (len(ordered) - 1) * fraction
    low = int(index)
    high = min(low + 1, len(ordered) - 1)
    weight = index - low
    return ordered[low] * (1 - weight) + ordered[high] * weight


async def _create_conversation(
    client: httpx.AsyncClient,
    *,
    token: str,
    mode: str,
    index: int,
) -> str:
    response = await client.post(
        "/api/v1/conversations",
        headers={"Authorization": f"Bearer {token}"},
        json={"title": f"benchmark-{index}", "mode": mode},
    )
    response.raise_for_status()
    payload = response.json()
    conversation_id = payload.get("id")
    if not isinstance(conversation_id, str) or not conversation_id:
        raise RuntimeError("conversation API returned no id")
    return conversation_id


async def _run_one(
    client: httpx.AsyncClient,
    *,
    token: str,
    conversation_id: str,
    question: str,
    document_ids: list[str],
    request_index: int,
) -> Result:
    start = time.perf_counter()
    first_visible_token_at: float | None = None
    input_tokens: int | None = None
    output_tokens: int | None = None
    citation_count = 0
    outcome: str | None = None
    error: str | None = None
    status_code = 0

    try:
        async with client.stream(
            "POST",
            "/api/v1/chat/stream",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "conversation_id": conversation_id,
                "question": question,
                "language": "vi",
                "selected_document_ids": document_ids,
                "response_depth": "detailed",
            },
        ) as response:
            status_code = response.status_code
            if response.status_code != 200:
                body = (await response.aread()).decode(errors="replace")[:500]
                error = f"HTTP {response.status_code}: {body}"
            else:
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    try:
                        event = json.loads(line[6:])
                    except json.JSONDecodeError:
                        error = "malformed SSE JSON"
                        continue
                    event_type = event.get("event_type")
                    data = event.get("data") if isinstance(event.get("data"), dict) else {}
                    if event_type == "token" and first_visible_token_at is None:
                        first_visible_token_at = time.perf_counter()
                    elif event_type == "citation":
                        citation_count += 1
                    elif event_type == "usage":
                        raw_input = data.get("input_tokens")
                        raw_output = data.get("output_tokens")
                        input_tokens = raw_input if isinstance(raw_input, int) else None
                        output_tokens = raw_output if isinstance(raw_output, int) else None
                    elif event_type == "done":
                        raw_outcome = data.get("outcome")
                        outcome = raw_outcome if isinstance(raw_outcome, str) else None
                    elif event_type == "error":
                        error = str(data.get("code") or data.get("message") or "stream error")
    except Exception as exception:
        error = f"{type(exception).__name__}: {exception}"

    end = time.perf_counter()
    return Result(
        request_index=request_index,
        status_code=status_code,
        ttft_ms=(
            None if first_visible_token_at is None else (first_visible_token_at - start) * 1000
        ),
        total_latency_ms=(end - start) * 1000,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        citation_count=citation_count,
        outcome=outcome,
        error=error,
    )


async def _benchmark(args: argparse.Namespace, token: str) -> dict[str, object]:
    timeout = httpx.Timeout(args.timeout_seconds)
    limits = httpx.Limits(max_connections=max(args.concurrency * 2, 10))
    async with httpx.AsyncClient(base_url=args.base_url, timeout=timeout, limits=limits) as client:
        conversation_ids = await asyncio.gather(
            *(
                _create_conversation(client, token=token, mode=args.mode, index=index)
                for index in range(args.requests)
            )
        )
        semaphore = asyncio.Semaphore(args.concurrency)

        async def bounded(index: int) -> Result:
            async with semaphore:
                return await _run_one(
                    client,
                    token=token,
                    conversation_id=conversation_ids[index],
                    question=args.question,
                    document_ids=args.document_id,
                    request_index=index,
                )

        started = time.perf_counter()
        results = await asyncio.gather(*(bounded(index) for index in range(args.requests)))
        wall_seconds = time.perf_counter() - started

    successful = [result for result in results if result.error is None]
    ttfts = [result.ttft_ms for result in successful if result.ttft_ms is not None]
    totals = [result.total_latency_ms for result in successful]
    output_token_total = sum(result.output_tokens or 0 for result in successful)
    return {
        "schema_version": 1,
        "measured": True,
        "base_url": args.base_url,
        "mode": args.mode,
        "rag_documents_attached": bool(args.document_id),
        "concurrency": args.concurrency,
        "requests": args.requests,
        "successful": len(successful),
        "failed": len(results) - len(successful),
        "wall_seconds": wall_seconds,
        "throughput_requests_per_second": (
            len(successful) / wall_seconds if wall_seconds > 0 else None
        ),
        "effective_output_tokens_per_second": (
            output_token_total / wall_seconds if wall_seconds > 0 else None
        ),
        "ttft_ms": {"p50": _percentile(ttfts, 0.50), "p95": _percentile(ttfts, 0.95)},
        "total_latency_ms": {
            "p50": _percentile(totals, 0.50),
            "p95": _percentile(totals, 0.95),
            "mean": statistics.fmean(totals) if totals else None,
        },
        "results": [asdict(result) for result in results],
    }


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Benchmark a real local RAG deployment.")
    parser.add_argument("--base-url", default="http://localhost:8000")
    parser.add_argument("--token", default=os.environ.get("NTC_BENCHMARK_TOKEN"))
    parser.add_argument("--question", default="Chào bạn, hãy giới thiệu ngắn gọn khả năng của bạn.")
    parser.add_argument("--document-id", action="append", default=[])
    parser.add_argument("--mode", choices=("fast", "reasoning"), default="fast")
    parser.add_argument("-c", "--concurrency", type=int, default=1)
    parser.add_argument("-n", "--requests", type=int, default=5)
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--output", type=Path, default=Path("evals/reports/live-benchmark.json"))
    return parser.parse_args()


def main() -> int:
    args = _arguments()
    if not args.token:
        print(
            "Provide --token or NTC_BENCHMARK_TOKEN; fake credentials are forbidden.",
            file=sys.stderr,
        )
        return 2
    if args.concurrency <= 0 or args.requests <= 0:
        print("concurrency and requests must be positive", file=sys.stderr)
        return 2
    report = asyncio.run(_benchmark(args, args.token))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {key: report[key] for key in ("successful", "failed", "ttft_ms", "total_latency_ms")},
            ensure_ascii=False,
        )
    )
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
