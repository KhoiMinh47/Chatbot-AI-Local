"""Unit tests for Phase 4 document parsers."""

import hashlib
from io import BytesIO
from uuid import uuid4

import pytest
from openpyxl import Workbook
from worker.domain import ElementType, NormalizedDocument
from worker.parsers import (
    CSVParser,
    DoclingParser,
    PlainTextParser,
    SourceCodeParser,
    XLSXParser,
    parser_registry,
)


class TestPlainTextParser:
    """Test plain text parser."""

    @pytest.mark.anyio
    async def test_parse_simple_text(self) -> None:
        """Test parsing simple plain text."""
        parser = PlainTextParser()

        content = b"# Heading 1\n\nThis is a paragraph.\n\nAnother paragraph."

        doc = await parser.parse(
            content=content,
            filename="test.txt",
            mime_type="text/plain",
            document_id=uuid4(),
            version_id=uuid4(),
            tenant_id=uuid4(),
        )

        assert isinstance(doc, NormalizedDocument)
        assert len(doc.elements) == 3  # heading + 2 paragraphs
        assert doc.elements[0].type == ElementType.HEADING
        assert doc.elements[1].type == ElementType.PARAGRAPH
        assert doc.content_hash == hashlib.sha256(content).hexdigest()

    @pytest.mark.anyio
    async def test_parse_markdown(self) -> None:
        """Test parsing markdown file."""
        parser = PlainTextParser()

        content = b"# Title\n\n## Subtitle\n\nParagraph content."

        doc = await parser.parse(
            content=content,
            filename="test.md",
            mime_type="text/markdown",
            document_id=uuid4(),
            version_id=uuid4(),
            tenant_id=uuid4(),
        )

        assert len(doc.elements) >= 2
        assert doc.elements[0].type == ElementType.HEADING


class TestCSVParser:
    """Test CSV parser."""

    @pytest.mark.anyio
    async def test_parse_simple_csv(self) -> None:
        """Test parsing simple CSV file."""
        parser = CSVParser()

        content = b"Name,Age,City\nJohn,30,NYC\nJane,25,LA"

        doc = await parser.parse(
            content=content,
            filename="test.csv",
            mime_type="text/csv",
            document_id=uuid4(),
            version_id=uuid4(),
            tenant_id=uuid4(),
        )

        assert isinstance(doc, NormalizedDocument)
        assert len(doc.elements) >= 1
        assert all(elem.type == ElementType.TABLE for elem in doc.elements)

        # Check table format
        table_text = doc.elements[0].text
        assert "Name" in table_text
        assert "Age" in table_text
        assert "John" in table_text

    @pytest.mark.anyio
    async def test_parse_large_csv(self) -> None:
        """Test parsing large CSV with chunking."""
        parser = CSVParser()

        # Create CSV with 50 rows (should create multiple table chunks)
        rows = ["Name,Age,City"]
        for i in range(50):
            rows.append(f"Person{i},{20 + i},City{i}")

        content = "\n".join(rows).encode("utf-8")

        doc = await parser.parse(
            content=content,
            filename="large.csv",
            mime_type="text/csv",
            document_id=uuid4(),
            version_id=uuid4(),
            tenant_id=uuid4(),
        )

        # Should create multiple table elements (20 rows per chunk)
        assert len(doc.elements) >= 2


class TestStructuredParsers:
    @pytest.mark.anyio
    async def test_xlsx_retains_sheet_cell_range_and_formula(self) -> None:
        workbook = Workbook()
        worksheet = workbook.active
        worksheet.title = "Doanh thu"
        worksheet.append(["Tháng", "Tổng"])
        worksheet.append(["07", "=SUM(10,20)"])
        payload = BytesIO()
        workbook.save(payload)
        workbook.close()

        document = await XLSXParser().parse(
            content=payload.getvalue(),
            filename="bao-cao.xlsx",
            mime_type=("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
            document_id=uuid4(),
            version_id=uuid4(),
            tenant_id=uuid4(),
        )

        assert document.metadata["expected_unit_count"] == 1
        assert document.metadata["covered_unit_count"] == 1
        assert document.elements[0].sheet == "Doanh thu"
        assert document.elements[0].cell_range == "A2:B2"
        assert "=SUM(10,20)" in document.elements[0].text

    @pytest.mark.anyio
    async def test_source_code_retains_stable_line_provenance(self) -> None:
        document_id = uuid4()
        version_id = uuid4()
        document = await SourceCodeParser().parse(
            content=b"import os\n\ndef optimize_model():\n    return 'nemotron'\n",
            filename="runtime.py",
            mime_type="text/x-python",
            document_id=document_id,
            version_id=version_id,
            tenant_id=uuid4(),
        )

        element = document.elements[0]
        assert element.line_start == 1
        assert element.line_end == 4
        assert element.section_path == ["runtime.py", "optimize_model"]
        assert str(version_id) in element.element_id


class TestParserRegistry:
    """Test parser registry."""

    def test_get_parser_for_csv(self) -> None:
        """Test registry returns CSV parser."""
        parser = parser_registry.get_parser("text/csv")
        assert isinstance(parser, CSVParser)

    def test_get_parser_for_text(self) -> None:
        """Test registry returns plain text parser."""
        parser = parser_registry.get_parser("text/plain")
        assert isinstance(parser, PlainTextParser)

    def test_get_parser_for_pdf(self) -> None:
        """Test registry returns Docling parser for PDF."""
        parser = parser_registry.get_parser("application/pdf")
        assert isinstance(parser, DoclingParser)

    def test_get_parser_for_xlsx_and_source_code(self) -> None:
        assert isinstance(
            parser_registry.get_parser(
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            ),
            XLSXParser,
        )
        assert isinstance(parser_registry.get_parser("text/x-python"), SourceCodeParser)

    def test_unsupported_mime_type(self) -> None:
        """Test registry raises error for unsupported type."""
        with pytest.raises(ValueError, match="No parser available"):
            parser_registry.get_parser("application/octet-stream")
