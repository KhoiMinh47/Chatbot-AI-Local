"""Deterministic, token-bounded, structure-aware parent-child chunking."""

from __future__ import annotations

import hashlib
from uuid import UUID, uuid5

import tiktoken

from worker.domain import (
    Chunk,
    ChunkConfig,
    ChunkType,
    ElementType,
    NormalizedDocument,
    NormalizedElement,
)

_CHUNK_NAMESPACE = UUID("908ddaba-abf8-5c52-91c6-87c13fc6da27")


class Chunker:
    """Create replay-stable parent/child chunks with a hard child budget."""

    def __init__(self, config: ChunkConfig | None = None) -> None:
        self.config = config or ChunkConfig()
        self.encoding = tiktoken.get_encoding("cl100k_base")

    def count_tokens(self, text: str) -> int:
        return len(self.encoding.encode(text))

    def _token_windows(self, text: str, limit: int, overlap_percent: int) -> list[str]:
        token_ids = self.encoding.encode(text)
        if not token_ids:
            return []
        windows: list[str] = []
        start = 0
        while start < len(token_ids):
            # A token slice can start/end inside a multi-byte character. After
            # decoding and stripping, re-encoding that text may therefore use
            # slightly more tokens than the original slice. Shrink the end
            # until the public hard-budget contract is true for the exact text
            # that will be stored.
            end = min(len(token_ids), start + limit)
            window = self.encoding.decode(token_ids[start:end]).strip()
            while end > start and window and self.count_tokens(window) > limit:
                end -= 1
                window = self.encoding.decode(token_ids[start:end]).strip()
            if window:
                windows.append(window)
            if end >= len(token_ids):
                break
            if end <= start:
                raise RuntimeError("chunk tokenizer could not make progress")
            consumed = end - start
            overlap = min(consumed - 1, int(limit * overlap_percent / 100))
            start = max(start + 1, end - overlap)
        return windows

    @staticmethod
    def _group_elements(elements: list[NormalizedElement]) -> list[list[NormalizedElement]]:
        """Never merge different page, slide or section provenance into one group."""

        groups: list[list[NormalizedElement]] = []
        current: list[NormalizedElement] = []
        current_key: (
            tuple[
                int | None,
                int | None,
                str | None,
                str | None,
                int | None,
                int | None,
                tuple[str, ...],
            ]
            | None
        ) = None
        for element in elements:
            key = (
                element.page,
                element.slide,
                element.sheet,
                element.cell_range,
                element.line_start,
                element.line_end,
                tuple(element.section_path),
            )
            starts_section = element.type == ElementType.HEADING and bool(current)
            if current and (key != current_key or starts_section):
                groups.append(current)
                current = []
            current.append(element)
            current_key = key
        if current:
            groups.append(current)
        return groups

    def _render_group(self, elements: list[NormalizedElement]) -> str:
        body = "\n\n".join(element.text for element in elements if element.text.strip())
        section_path = elements[0].section_path
        if self.config.include_section_prefix and section_path:
            prefix = "Section: " + " > ".join(section_path)
            if not body.startswith(prefix):
                return f"{prefix}\n\n{body}"
        return body

    def _chunk_id(
        self,
        document: NormalizedDocument,
        chunk_type: ChunkType,
        chunk_index: int,
        text: str,
    ) -> UUID:
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        identity = (
            f"{document.version_id}:{self.config.index_version}:"
            f"{chunk_type.value}:{chunk_index}:{content_hash}"
        )
        return uuid5(_CHUNK_NAMESPACE, identity)

    def _build_chunk(
        self,
        *,
        document: NormalizedDocument,
        metadata: NormalizedElement,
        chunk_type: ChunkType,
        chunk_index: int,
        text: str,
        parent_id: UUID | None,
    ) -> Chunk:
        content_hash = hashlib.sha256(text.encode()).hexdigest()
        return Chunk(
            chunk_id=self._chunk_id(document, chunk_type, chunk_index, text),
            document_id=document.document_id,
            version_id=document.version_id,
            parent_chunk_id=parent_id,
            chunk_type=chunk_type,
            chunk_index=chunk_index,
            text=text,
            token_count=self.count_tokens(text),
            content_hash=content_hash,
            index_version=self.config.index_version,
            page=metadata.page,
            slide=metadata.slide,
            sheet=metadata.sheet,
            cell_range=metadata.cell_range,
            line_start=metadata.line_start,
            line_end=metadata.line_end,
            section_path=list(metadata.section_path),
            language=document.language,
        )

    def chunk_document(self, document: NormalizedDocument) -> list[Chunk]:
        """Return deterministic chunks; every child obeys ``child_size`` exactly."""

        chunks: list[Chunk] = []
        chunk_index = 0
        for elements in self._group_elements(document.elements):
            rendered = self._render_group(elements)
            parent_windows = self._token_windows(rendered, self.config.parent_size, 0)
            for parent_text in parent_windows:
                parent = self._build_chunk(
                    document=document,
                    metadata=elements[0],
                    chunk_type=ChunkType.PARENT,
                    chunk_index=chunk_index,
                    text=parent_text,
                    parent_id=None,
                )
                chunks.append(parent)
                chunk_index += 1

                # Token windows are the hard fallback for oversized paragraphs,
                # lists and tables. Smaller structures remain intact.
                child_windows = self._token_windows(
                    parent_text,
                    self.config.child_size,
                    self.config.overlap_percent,
                )
                for child_text in child_windows:
                    child = self._build_chunk(
                        document=document,
                        metadata=elements[0],
                        chunk_type=ChunkType.CHILD,
                        chunk_index=chunk_index,
                        text=child_text,
                        parent_id=parent.chunk_id,
                    )
                    if child.token_count > self.config.child_size:
                        raise RuntimeError("chunk tokenizer violated the configured hard budget")
                    chunks.append(child)
                    chunk_index += 1
        return chunks


__all__ = ["Chunker"]
