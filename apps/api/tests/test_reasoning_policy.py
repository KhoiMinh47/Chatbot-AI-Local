from __future__ import annotations

from uuid import UUID

from app.application.reasoning_policy import ReasoningPolicy
from app.domain.rag import RagMode, RagRequest

USER_ID = UUID("10000000-0000-4000-8000-000000000001")


def _request(*, mode: RagMode, question: str, document_count: int = 0) -> RagRequest:
    return RagRequest(
        request_id=UUID("20000000-0000-4000-8000-000000000001"),
        user_id=USER_ID,
        tenant_id=UUID("30000000-0000-4000-8000-000000000001"),
        conversation_id=UUID("40000000-0000-4000-8000-000000000001"),
        mode=mode,
        question=question,
        language="vi",
        acl_principals=(f"user:{USER_ID}",),
        selected_document_ids=tuple(UUID(int=index + 1) for index in range(document_count)),
    )


def test_fast_mode_is_greedy_and_never_enables_hidden_reasoning() -> None:
    decision = ReasoningPolicy().select(
        _request(mode=RagMode.FAST, question="Debug và tổng hợp nhiều file")
    )

    assert decision.policy.temperature == 0
    assert decision.policy.top_p == 1
    assert decision.thinking_budget_tokens == 0


def test_reasoning_uses_nemotron_recommended_sampling_baseline() -> None:
    decision = ReasoningPolicy().select(
        _request(mode=RagMode.REASONING, question="Phân tích lỗi kiến trúc này")
    )

    assert decision.complexity == "technical"
    assert decision.policy.temperature == 0.6
    assert decision.policy.top_p == 0.95
    assert decision.policy.max_output_tokens == 1_024
    assert decision.thinking_budget_tokens == 2_048


def test_multi_document_reasoning_gets_larger_but_bounded_context_and_output() -> None:
    decision = ReasoningPolicy().select(
        _request(mode=RagMode.REASONING, question="Đối chiếu hai file", document_count=2)
    )

    assert decision.complexity == "multi_document"
    assert decision.policy.context_window_tokens == 65_536
    assert decision.policy.context_token_cap == 32_768
    assert decision.policy.max_output_tokens == 2_048
    assert (
        decision.policy.context_token_cap
        + decision.policy.max_output_tokens
        + decision.policy.safety_tokens
        < decision.policy.context_window_tokens
    )
