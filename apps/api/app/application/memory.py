"""Token-bounded, server-side working-memory selection."""

from __future__ import annotations

from dataclasses import dataclass

from app.application.ai_clients import ChatMessage
from app.application.rag import TokenCounter
from app.domain.rag import ConversationTurn


@dataclass(frozen=True, slots=True)
class WorkingMemorySelection:
    """A contiguous suffix of exact conversation turns that fits the prompt budget."""

    turns: tuple[ConversationTurn, ...]
    token_count: int
    dropped_turns: int


class WorkingMemorySelector:
    """Keep complete recent turns using the active model's exact chat tokenizer."""

    def __init__(
        self,
        *,
        token_counter: TokenCounter,
        max_tokens: int,
        max_turns: int,
    ) -> None:
        if not token_counter.exact:
            raise ValueError("working memory requires an exact tokenizer")
        if max_tokens <= 0 or max_turns <= 0:
            raise ValueError("working-memory limits must be positive")
        self._counter = token_counter
        self._max_tokens = max_tokens
        self._max_turns = max_turns

    def select(self, turns: tuple[ConversationTurn, ...]) -> WorkingMemorySelection:
        candidates = turns[-self._max_turns :]
        selected: tuple[ConversationTurn, ...] = ()
        selected_tokens = 0

        for turn in reversed(candidates):
            proposed = (turn, *selected)
            messages = tuple(ChatMessage(role=item.role, content=item.content) for item in proposed)
            proposed_tokens = self._counter.count_messages(messages)
            if proposed_tokens > self._max_tokens:
                # Keep a contiguous suffix. Skipping a newer oversized turn to include
                # older context would corrupt conversational chronology.
                break
            selected = proposed
            selected_tokens = proposed_tokens

        return WorkingMemorySelection(
            turns=selected,
            token_count=selected_tokens,
            dropped_turns=len(turns) - len(selected),
        )
