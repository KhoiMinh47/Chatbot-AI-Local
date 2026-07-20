"""Unit tests for Phase 4 chunking logic."""

from uuid import uuid4

from worker.chunking import Chunker
from worker.domain import (
    ChunkConfig,
    ChunkType,
    ElementType,
    NormalizedDocument,
    NormalizedElement,
)


class TestChunker:
    """Test structure-aware chunker."""

    def test_chunk_simple_document(self) -> None:
        """Test chunking a simple document."""
        doc = NormalizedDocument(
            document_id=uuid4(),
            version_id=uuid4(),
            tenant_id=uuid4(),
            source_name="test.txt",
            mime_type="text/plain",
            language="en",
            content_hash="abc123",
            elements=[
                NormalizedElement(
                    element_id="1",
                    type=ElementType.HEADING,
                    text="Introduction",
                    section_path=["Introduction"],
                ),
                NormalizedElement(
                    element_id="2",
                    type=ElementType.PARAGRAPH,
                    text="This is a short paragraph about the introduction.",
                    section_path=["Introduction"],
                ),
            ],
        )

        chunker = Chunker(ChunkConfig(child_size=100, parent_size=500))
        chunks = chunker.chunk_document(doc)

        assert len(chunks) >= 2  # At least 1 parent + 1 child

        # Check parent chunk exists
        parent_chunks = [c for c in chunks if c.chunk_type == ChunkType.PARENT]
        assert len(parent_chunks) >= 1

        # Check child chunks exist
        child_chunks = [c for c in chunks if c.chunk_type == ChunkType.CHILD]
        assert len(child_chunks) >= 1

        # Verify parent-child relationship
        for child in child_chunks:
            assert child.parent_chunk_id is not None

    def test_chunk_with_tables(self) -> None:
        """Test that tables are not split inappropriately."""
        table_text = "| Col1 | Col2 |\n|------|------|\n| A | B |\n| C | D |"

        doc = NormalizedDocument(
            document_id=uuid4(),
            version_id=uuid4(),
            tenant_id=uuid4(),
            source_name="test.csv",
            mime_type="text/csv",
            language="en",
            content_hash="def456",
            elements=[
                NormalizedElement(
                    element_id="1",
                    type=ElementType.TABLE,
                    text=table_text,
                    section_path=[],
                ),
            ],
        )

        chunker = Chunker(ChunkConfig(child_size=50, parent_size=200))
        chunks = chunker.chunk_document(doc)

        # Table should be kept together
        child_chunks = [c for c in chunks if c.chunk_type == ChunkType.CHILD]

        # Find chunk containing the table
        table_chunks = [c for c in child_chunks if "Col1" in c.text]
        assert len(table_chunks) >= 1

    def test_chunk_large_document(self) -> None:
        """Test chunking a large document with multiple sections."""
        # Create a document with 3 sections
        elements = []
        for i in range(3):
            section_name = f"Section {i + 1}"
            elements.append(
                NormalizedElement(
                    element_id=f"h{i}",
                    type=ElementType.HEADING,
                    text=section_name,
                    section_path=[section_name],
                )
            )

            # Add 5 paragraphs per section
            for j in range(5):
                text = f"Paragraph {j + 1} of {section_name}. " * 10  # ~10 words x 10 = 100 words
                elements.append(
                    NormalizedElement(
                        element_id=f"p{i}_{j}",
                        type=ElementType.PARAGRAPH,
                        text=text,
                        section_path=[section_name],
                    )
                )

        doc = NormalizedDocument(
            document_id=uuid4(),
            version_id=uuid4(),
            tenant_id=uuid4(),
            source_name="large.txt",
            mime_type="text/plain",
            language="en",
            content_hash="ghi789",
            elements=elements,
        )

        chunker = Chunker(ChunkConfig(child_size=512, parent_size=2000))
        chunks = chunker.chunk_document(doc)

        # Should create multiple parent-child chunk groups
        parent_chunks = [c for c in chunks if c.chunk_type == ChunkType.PARENT]
        child_chunks = [c for c in chunks if c.chunk_type == ChunkType.CHILD]

        assert len(parent_chunks) >= 1  # At least one parent per section
        assert len(child_chunks) >= 3  # Multiple children

        # Verify all chunks have valid token counts
        for chunk in chunks:
            assert chunk.token_count > 0
            assert chunk.token_count <= (2000 if chunk.chunk_type == ChunkType.PARENT else 1000)

    def test_token_counting(self) -> None:
        """Test token counting is accurate."""
        chunker = Chunker()

        text = "This is a simple test sentence."
        token_count = chunker.count_tokens(text)

        # Should be around 6-8 tokens
        assert 5 <= token_count <= 10

    def test_chunk_preserves_section_path(self) -> None:
        """Test that chunks preserve section path metadata."""
        doc = NormalizedDocument(
            document_id=uuid4(),
            version_id=uuid4(),
            tenant_id=uuid4(),
            source_name="test.txt",
            mime_type="text/plain",
            language="en",
            content_hash="jkl012",
            elements=[
                NormalizedElement(
                    element_id="1",
                    type=ElementType.PARAGRAPH,
                    text="Content in chapter 1, section 1.1",
                    section_path=["Chapter 1", "Section 1.1"],
                ),
            ],
        )

        chunker = Chunker()
        chunks = chunker.chunk_document(doc)

        # All chunks should have the section path
        for chunk in chunks:
            if "Content in chapter" in chunk.text:
                assert chunk.section_path == ["Chapter 1", "Section 1.1"]
