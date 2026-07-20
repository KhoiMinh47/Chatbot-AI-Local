"""Focused contracts for the completed Phase 4 worker pipeline."""

from __future__ import annotations

import inspect
from itertools import pairwise
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest
from pydantic import SecretStr
from worker.celery_app import create_celery
from worker.chunking import Chunker
from worker.domain import ChunkConfig, ChunkType, ElementType, NormalizedDocument, NormalizedElement
from worker.normalization import normalize_document, normalized_json_bytes, preview_markdown_bytes
from worker.parsers import CSVParser, DoclingParser, ParserError, _document_converter
from worker.settings import BrokerSettings, IngestionSettings
from worker.tasks import (
    IngestionError,
    _artifact_location,
    _download_document,
    process_document_task,
)


def _document(text: str, *, page: int = 1) -> NormalizedDocument:
    return NormalizedDocument(
        document_id=uuid4(),
        version_id=uuid4(),
        tenant_id=uuid4(),
        source_name="policy.txt",
        mime_type="text/plain",
        language="en",
        content_hash="a" * 64,
        elements=[
            NormalizedElement(
                element_id="element-1",
                type=ElementType.PARAGRAPH,
                text=text,
                page=page,
                section_path=["Policy"],
            )
        ],
    )


def test_default_chunk_contract_is_embed300m_256_with_ten_percent_overlap() -> None:
    config = ChunkConfig()

    assert config.child_size == 256
    assert config.overlap_percent == 10
    assert config.index_version == "embed300m-v2_s256_o10"


def test_chunks_are_deterministic_overlap_and_never_exceed_child_budget() -> None:
    text = " ".join(f"item-{index}" for index in range(800))
    config = ChunkConfig(child_size=32, parent_size=128, overlap_percent=25)
    first = Chunker(config).chunk_document(_document(text))
    second = Chunker(config).chunk_document(_document(text))

    # Version identity is part of the deterministic ID, so compare replays of
    # the same authoritative document rather than separate logical versions.
    document = _document(text)
    replay_one = Chunker(config).chunk_document(document)
    replay_two = Chunker(config).chunk_document(document)
    assert [chunk.chunk_id for chunk in replay_one] == [chunk.chunk_id for chunk in replay_two]
    assert [chunk.content_hash for chunk in replay_one] == [
        chunk.content_hash for chunk in replay_two
    ]

    children = [chunk for chunk in first if chunk.chunk_type == ChunkType.CHILD]
    assert children
    assert all(chunk.token_count <= config.child_size for chunk in children)
    assert any(
        len(set(left.text.split()[-5:]).intersection(right.text.split()[:5])) >= 2
        for left, right in pairwise(children)
        if left.parent_chunk_id == right.parent_chunk_id
    )
    assert second  # A separate version remains valid and independently deterministic.


def test_chunker_does_not_merge_different_page_provenance() -> None:
    document = _document("First page")
    document.elements.append(
        NormalizedElement(
            element_id="element-2",
            type=ElementType.PARAGRAPH,
            text="Second page",
            page=2,
            section_path=["Policy"],
        )
    )

    chunks = Chunker(ChunkConfig(child_size=32, parent_size=64)).chunk_document(document)
    pages = {chunk.page for chunk in chunks if chunk.chunk_type == ChunkType.CHILD}

    assert pages == {1, 2}
    assert all(not ("First page" in chunk.text and "Second page" in chunk.text) for chunk in chunks)


def test_normalizer_removes_repeated_furniture_but_preserves_table_layout() -> None:
    document = _document("Body")
    header = NormalizedElement(
        element_id="header-1",
        type=ElementType.PARAGRAPH,
        text="Repeated header",
        page=1,
        metadata={"docling_label": "page_header"},
    )
    document.elements = [
        header,
        header.model_copy(update={"element_id": "header-2", "page": 2}),
        NormalizedElement(
            element_id="table",
            type=ElementType.TABLE,
            text="| A  | B |\n| --- | --- |\n| 1  | 2 |",
            page=2,
        ),
    ]

    normalized = normalize_document(document)
    payload = normalized_json_bytes(normalized)
    preview = preview_markdown_bytes(normalized)

    assert len(normalized.elements) == 1
    assert "| A  | B |" in normalized.elements[0].text
    assert b'"source_name":"policy.txt"' in payload
    assert b"page 2" in preview


@pytest.mark.anyio
async def test_csv_parser_reports_stable_actionable_error() -> None:
    parser = CSVParser()

    with pytest.raises(ParserError) as captured:
        await parser.parse(
            content=b"\xff\xfe",
            filename="bad.csv",
            mime_type="text/csv",
            document_id=uuid4(),
            version_id=uuid4(),
            tenant_id=uuid4(),
        )

    assert captured.value.code == "PARSER_INVALID_CSV"
    assert "UTF-8" in str(captured.value)


def test_docling_converter_is_cached_and_rapidocr_is_explicit() -> None:
    from docling.datamodel.base_models import InputFormat

    first = _document_converter()
    second = _document_converter()
    pdf_options = first.format_to_options[InputFormat.PDF].pipeline_options

    assert first is second
    assert pdf_options.do_ocr is False
    assert type(pdf_options.ocr_options).__name__ == "RapidOcrOptions"
    assert pdf_options.ocr_options.force_full_page_ocr is False


@pytest.mark.anyio
async def test_docling_parser_includes_tables_and_provenance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import worker.parsers as parser_module

    class Provenance:
        page_no = 2
        bbox = SimpleNamespace(l=1.0, t=2.0, r=3.0, b=4.0)

    class Item:
        def __init__(self, label: str, text: str) -> None:
            self.label = label
            self.text = text
            self.prov = [Provenance()]
            self.meta = None

    class TableItem(Item):
        def export_to_markdown(self, *, doc: object) -> str:
            del doc
            return "| A | B |\n|---|---|\n| 1 | 2 |"

    class Document:
        def iterate_items(self) -> list[tuple[Item, int]]:
            return [
                (Item("section_header", "Benefits"), 0),
                (Item("text", "Coverage starts immediately."), 1),
                (TableItem("table", ""), 1),
            ]

    class Result:
        document = Document()

    class Converter:
        def convert(self, path: object) -> Result:
            del path
            return Result()

    monkeypatch.setattr(parser_module, "_document_converter", lambda: Converter())
    parsed = await DoclingParser().parse(
        content=b"fake-pptx-content",
        filename="benefits.pptx",
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        document_id=uuid4(),
        version_id=uuid4(),
        tenant_id=uuid4(),
    )

    assert [element.type for element in parsed.elements] == [
        ElementType.HEADING,
        ElementType.PARAGRAPH,
        ElementType.TABLE,
    ]
    assert parsed.elements[1].slide == 2
    assert parsed.elements[1].page is None
    assert parsed.elements[1].section_path == ["Benefits"]
    assert parsed.elements[2].bbox == [1.0, 2.0, 3.0, 4.0]
    assert parsed.metadata["ocr_engine"] == "rapidocr-onnxruntime"


class _Response:
    def __init__(self, content: bytes) -> None:
        self.content = content
        self.closed = False
        self.released = False

    def read(self, amount: int) -> bytes:
        return self.content[:amount]

    def close(self) -> None:
        self.closed = True

    def release_conn(self) -> None:
        self.released = True


class _Minio:
    def __init__(self, response: _Response) -> None:
        self.response = response

    def get_object(self, bucket: str, object_name: str) -> _Response:
        assert bucket == "documents"
        assert object_name == "raw/file.pdf"
        return self.response


def test_download_always_closes_and_releases_minio_response() -> None:
    response = _Response(b"content")

    content = _download_document(cast(Any, _Minio(response)), "documents/raw/file.pdf", 100)

    assert content == b"content"
    assert response.closed
    assert response.released


@pytest.mark.parametrize(
    "path",
    ["missing-object", "bucket/../secret", "/object", "bucket//object"],
)
def test_artifact_path_rejects_ambiguous_or_traversing_paths(path: str) -> None:
    with pytest.raises(IngestionError, match="storage path is invalid"):
        _artifact_location(path)


def test_task_public_signature_accepts_only_authoritative_job_id() -> None:
    assert tuple(inspect.signature(process_document_task.run).parameters) == ("job_id",)


def test_celery_routes_ingestion_to_durable_dead_letter_queue() -> None:
    app = create_celery(BrokerSettings(broker_url=SecretStr("amqp://broker.invalid:5672//")))
    queues = {queue.name: queue for queue in app.conf.task_queues}

    assert set(queues) == {"ingestion", "ingestion.dead"}
    assert queues["ingestion"].queue_arguments == {
        "x-dead-letter-exchange": "ingestion.dead",
        "x-dead-letter-routing-key": "document.failed",
    }
    assert app.conf.task_acks_late is True
    assert app.conf.task_reject_on_worker_lost is True


def test_ingestion_settings_redact_database_and_object_store_secrets() -> None:
    settings = IngestionSettings(
        database_url=SecretStr("postgresql+psycopg://user:pw@db/ntc"),
        minio_access_key=SecretStr("access-key"),
        minio_secret_key=SecretStr("secret-key"),
    )

    rendered = repr(settings)
    assert "password" not in rendered
    assert "access-key" not in rendered
    assert "secret-key" not in rendered
