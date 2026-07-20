"""Regression tests for exact-token, contiguous conversation working memory."""

from app.application.ai_clients import ChatMessage
from app.application.memory import WorkingMemorySelector
from app.domain.rag import ConversationTurn


class ExactLengthCounter:
    tokenizer_id = "test-exact"
    tokenizer_sha256 = "a" * 64
    exact = True

    def count_text(self, text: str) -> int:
        return len(text)

    def count_messages(self, messages: tuple[ChatMessage, ...]) -> int:
        return sum(len(message.content) + 1 for message in messages)


class ApproximateCounter(ExactLengthCounter):
    exact = False


def test_working_memory_keeps_complete_recent_suffix_within_token_budget() -> None:
    turns = (
        ConversationTurn(role="user", content="old question"),
        ConversationTurn(role="assistant", content="old answer"),
        ConversationTurn(role="user", content="new"),
        ConversationTurn(role="assistant", content="reply"),
    )

    selected = WorkingMemorySelector(
        token_counter=ExactLengthCounter(),
        max_tokens=10,
        max_turns=4,
    ).select(turns)

    assert selected.turns == turns[-2:]
    assert selected.token_count == 10
    assert selected.dropped_turns == 2


def test_working_memory_does_not_truncate_an_oversized_latest_message() -> None:
    turns = (
        ConversationTurn(role="user", content="short"),
        ConversationTurn(role="assistant", content="x" * 20),
    )

    selected = WorkingMemorySelector(
        token_counter=ExactLengthCounter(),
        max_tokens=10,
        max_turns=4,
    ).select(turns)

    assert selected.turns == ()
    assert selected.dropped_turns == 2


def test_working_memory_rejects_approximate_tokenizer() -> None:
    try:
        WorkingMemorySelector(
            token_counter=ApproximateCounter(),
            max_tokens=10,
            max_turns=4,
        )
    except ValueError as error:
        assert "exact tokenizer" in str(error)
    else:
        raise AssertionError("approximate token counter was accepted")
