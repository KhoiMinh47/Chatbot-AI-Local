"""Approximate token counter for local/dev deployments without a local tokenizer."""

from __future__ import annotations

from app.application.ai_clients import ChatMessage

_CHARS_PER_TOKEN = 3.5
_OVERHEAD_PER_MESSAGE = 4  # role, formatting tokens


class ApproxTokenCounter:
    """Word-count approximation (~3.5 chars/token). Not exact but good enough for budget."""

    @property
    def tokenizer_id(self) -> str:
        return "approx-chars-v1"

    @property
    def tokenizer_sha256(self) -> str:
        # sha256(b"approx-chars-v1") - deterministic ID for this dev counter
        return "d59790a497242a98f1fafdc4b1481c2c79544773025c233d1f4d93bcde17af22"

    @property
    def exact(self) -> bool:
        # Returns False because it is only an approximation
        return False

    def count_text(self, text: str) -> int:
        return max(1, int(len(text) / _CHARS_PER_TOKEN))

    def count_messages(self, messages: tuple[ChatMessage, ...]) -> int:
        total = sum(
            int(len(m.content) / _CHARS_PER_TOKEN) + _OVERHEAD_PER_MESSAGE for m in messages
        )
        return max(1, total)
