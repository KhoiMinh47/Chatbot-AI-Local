"""Regression tests for the hash-bound active-model tokenizer adapter."""

from pathlib import Path

from app.application.ai_clients import ChatMessage
from app.infrastructure.exact_token_counter import ExactHuggingFaceTokenCounter

TOKENIZER_SHA256 = "32bd2509c1acc93dc18bdd0f9a2d9a15e72fd3110f24cfc9ff3fb820f4e20b6b"


class MappingTokenizer:
    def __init__(self) -> None:
        self.rendered: object = None

    def apply_chat_template(self, *args: object, **_kwargs: object) -> dict[str, list[int]]:
        self.rendered = args[0]
        return {"input_ids": [11, 12, 13, 14], "attention_mask": [1, 1, 1, 1]}


def test_count_messages_counts_input_ids_not_mapping_keys() -> None:
    counter = object.__new__(ExactHuggingFaceTokenCounter)
    tokenizer = MappingTokenizer()
    counter._tokenizer = tokenizer  # type: ignore[attr-defined]

    observed = counter.count_messages(
        (
            ChatMessage(role="system", content="/think\n\nTrusted prompt"),
            ChatMessage(role="user", content="hello"),
        )
    )

    assert observed == 4
    assert tokenizer.rendered == [
        {"role": "system", "content": "/think\n\nTrusted prompt"},
        {"role": "user", "content": "hello"},
    ]


def test_active_nemotron_chat_template_renders_with_runtime_dependencies() -> None:
    tokenizer_path = Path(__file__).parents[1] / "app" / "infrastructure" / "tokenizer"
    counter = ExactHuggingFaceTokenCounter(
        tokenizer_path=tokenizer_path,
        tokenizer_id="nvidia/NVIDIA-Nemotron-Nano-9B-v2",
        expected_sha256=TOKENIZER_SHA256,
    )

    observed = counter.count_messages(
        (
            ChatMessage(role="system", content="/no_think\nYou are helpful."),
            ChatMessage(role="user", content="Xin chào"),
        )
    )

    assert observed == 23
