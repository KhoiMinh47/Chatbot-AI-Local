"""Deterministic Nemotron reasoning and output-budget routing."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace
from typing import Literal

from app.domain.rag import ModePolicy, RagMode, RagRequest, ResponseDepth, policy_for

_TECHNICAL = re.compile(
    r"\b(?:debug|lỗi|error|architecture|kiến trúc|phân tích|analy[sz]e|"
    r"so sánh|compare|tại sao|why|triển khai|implement|code|cấu hình|config)\b",
    re.IGNORECASE,
)
_COMPOUND = re.compile(
    r"\b(?:nhiều file|các tài liệu|multi[- ]?document|tổng hợp|synthesis|"
    r"đối chiếu|conflict|mâu thuẫn)\b",
    re.IGNORECASE,
)
_SUMMARY = re.compile(
    r"\b(?:tóm tắt|tom tat|tổng quan|overview|summari[sz]e|toàn bộ|nội dung chính)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ReasoningDecision:
    policy: ModePolicy
    complexity: Literal["direct", "technical", "multi_document"]
    thinking_budget_tokens: int


class ReasoningPolicy:
    """Respect the user-selected mode, then bound difficult reasoning deterministically.

    The current NVIDIA NIM API exposes ``/think`` rather than a separate thinking-budget
    field. ``thinking_budget_tokens`` is therefore telemetry/audit metadata; the hard
    safety bound remains the request's total ``max_tokens``.
    """

    def select(self, request: RagRequest) -> ReasoningDecision:
        base = policy_for(request.mode)
        if request.selected_document_ids and _SUMMARY.search(request.question):
            return ReasoningDecision(
                policy=replace(
                    base,
                    max_subqueries=3,
                    max_dense_candidates=144,
                    candidate_limit_per_query=48,
                    rerank_limit=48,
                    final_context_limit=20,
                    context_token_cap=24_000,
                    max_output_tokens=1_536,
                    safety_tokens=2_048,
                ),
                complexity="technical",
                thinking_budget_tokens=2_048,
            )
        if request.mode is RagMode.FAST:
            if request.selected_document_ids and request.response_depth is ResponseDepth.DETAILED:
                base = replace(base, max_output_tokens=1_024)
            return ReasoningDecision(
                policy=base,
                complexity="direct",
                thinking_budget_tokens=0,
            )

        multi_document = len(request.selected_document_ids) > 1 or bool(
            _COMPOUND.search(request.question)
        )
        if multi_document:
            return ReasoningDecision(
                policy=replace(
                    base,
                    context_window_tokens=65_536,
                    context_token_cap=32_768,
                    max_output_tokens=2_048,
                    safety_tokens=4_096,
                ),
                complexity="multi_document",
                thinking_budget_tokens=4_096,
            )

        technical = (
            bool(_TECHNICAL.search(request.question))
            or len(request.question) >= 500
            or bool(request.recent_messages)
        )
        return ReasoningDecision(
            policy=base,
            complexity="technical" if technical else "direct",
            thinking_budget_tokens=2_048 if technical else 1_024,
        )
