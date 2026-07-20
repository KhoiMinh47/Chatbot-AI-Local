"""Parse-quality coverage and warning regression tests."""

from uuid import uuid4

from worker.domain import ElementType, NormalizedDocument, NormalizedElement
from worker.quality import build_parse_quality_report


def document(*, expected: int, covered_pages: tuple[int, ...]) -> NormalizedDocument:
    document_id = uuid4()
    return NormalizedDocument(
        document_id=document_id,
        version_id=uuid4(),
        tenant_id=uuid4(),
        source_name="quality.pdf",
        mime_type="application/pdf",
        content_hash="a" * 64,
        elements=[
            NormalizedElement(
                element_id=f"{document_id}:{page}",
                type=ElementType.PARAGRAPH,
                text=f"Nội dung đủ dài trên trang {page} để kiểm tra chất lượng parser.",
                page=page,
            )
            for page in covered_pages
        ],
        metadata={
            "expected_unit_count": expected,
            "covered_unit_count": len(covered_pages),
            "ocr_enabled": False,
        },
    )


def test_low_page_coverage_is_visible_as_needs_review() -> None:
    report = build_parse_quality_report(document(expected=10, covered_pages=(1, 2, 3)))

    assert report.quality_status == "needs_review"
    assert report.coverage_ratio == 0.3
    assert report.empty_unit_count == 7
    assert "low_unit_coverage" in report.warnings


def test_complete_document_has_ready_quality_status() -> None:
    report = build_parse_quality_report(document(expected=2, covered_pages=(1, 2)))

    assert report.quality_status == "ready"
    assert report.coverage_ratio == 1.0
    assert report.warnings == []
