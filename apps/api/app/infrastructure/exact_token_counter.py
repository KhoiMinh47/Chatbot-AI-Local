"""Hash-bound exact tokenizer adapter; it never loads model weights or uses network I/O."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from transformers import AutoTokenizer

from app.application.ai_clients import ChatMessage

_TOKENIZER_FILES = frozenset(
    {
        "added_tokens.json",
        "chat_template.jinja",
        "merges.txt",
        "sentencepiece.bpe.model",
        "special_tokens_map.json",
        "spiece.model",
        "tokenizer.json",
        "tokenizer.model",
        "tokenizer_config.json",
        "vocab.json",
        "vocab.txt",
    }
)


class ExactHuggingFaceTokenCounter:
    """Count with the active model's local chat template and verified tokenizer files."""

    def __init__(
        self,
        *,
        tokenizer_path: Path,
        tokenizer_id: str,
        expected_sha256: str,
    ) -> None:
        if not tokenizer_id.strip():
            raise ValueError("tokenizer_id must not be blank")
        if not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
            raise ValueError("expected_sha256 must be a lowercase SHA-256 digest")
        resolved = tokenizer_path.expanduser().resolve(strict=True)
        if not resolved.is_dir():
            raise ValueError("tokenizer_path must be a local directory")
        observed = self.fingerprint(resolved)
        if observed != expected_sha256:
            raise ValueError("local tokenizer fingerprint does not match expected_sha256")
        tokenizer: Any = AutoTokenizer.from_pretrained(
            resolved,
            local_files_only=True,
            trust_remote_code=False,
        )
        if not getattr(tokenizer, "chat_template", None):
            raise ValueError("the active tokenizer does not define an exact chat template")
        self._tokenizer = tokenizer
        self._tokenizer_id = tokenizer_id
        self._tokenizer_sha256 = observed

    @property
    def tokenizer_id(self) -> str:
        return self._tokenizer_id

    @property
    def tokenizer_sha256(self) -> str:
        return self._tokenizer_sha256

    @property
    def exact(self) -> bool:
        return True

    def count_text(self, text: str) -> int:
        encoded = self._tokenizer.encode(text, add_special_tokens=False)
        return len(encoded)

    def count_messages(self, messages: tuple[ChatMessage, ...]) -> int:
        rendered = [{"role": message.role, "content": message.content} for message in messages]
        token_ids = self._tokenizer.apply_chat_template(
            rendered,
            tokenize=True,
            add_generation_prompt=True,
            return_dict=False,
        )
        if isinstance(token_ids, Mapping):
            token_ids = token_ids.get("input_ids")
        if token_ids is None or isinstance(token_ids, (str, bytes)):
            raise RuntimeError("chat template did not return token IDs")
        if not isinstance(token_ids, Sequence):
            raise RuntimeError("chat template returned an unsupported token structure")
        if token_ids and isinstance(token_ids[0], Sequence):
            if len(token_ids) != 1:
                raise RuntimeError("chat template unexpectedly returned multiple sequences")
            token_ids = token_ids[0]
        if any(
            isinstance(token_id, bool) or not isinstance(token_id, int) for token_id in token_ids
        ):
            raise RuntimeError("chat template returned non-integer token IDs")
        return len(token_ids)

    @staticmethod
    def fingerprint(tokenizer_path: Path) -> str:
        files = sorted(
            path
            for path in tokenizer_path.rglob("*")
            if path.is_file() and path.name in _TOKENIZER_FILES
        )
        if not files:
            raise ValueError("no supported tokenizer artifacts were found")
        digest = hashlib.sha256()
        for path in files:
            relative = path.relative_to(tokenizer_path).as_posix().encode("utf-8")
            content = path.read_bytes()
            digest.update(relative)
            digest.update(b"\0")
            digest.update(str(len(content)).encode("ascii"))
            digest.update(b"\0")
            digest.update(content)
        return digest.hexdigest()
