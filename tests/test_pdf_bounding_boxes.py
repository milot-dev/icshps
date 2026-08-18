from __future__ import annotations

from pathlib import Path

import fitz

from icshps.agents.extraction.pdf_bounding_boxes import (
    find_text_bounding_box,
    use_vision_page_index,
)
from icshps.agents.extraction.pdf_text_extractor import ExtractedPDFPage


def test_missing_pdf_path_does_not_crash_bounding_box_lookup():
    result = find_text_bounding_box(Path("missing_resume.pdf"), "Jane Doe")

    assert result.page_number is None
    assert result.bounding_box is None


def test_empty_snippet_does_not_crash_bounding_box_lookup(tmp_path):
    pdf_path = tmp_path / "resume.pdf"
    _write_test_pdf(pdf_path, "Jane Doe")

    result = find_text_bounding_box(pdf_path, "")

    assert result.page_number is None
    assert result.bounding_box is None


def test_snippet_not_found_returns_null_bounding_box(tmp_path):
    pdf_path = tmp_path / "resume.pdf"
    _write_test_pdf(pdf_path, "Jane Doe")

    result = find_text_bounding_box(pdf_path, "Python")

    assert result.page_number is None
    assert result.bounding_box is None


def test_found_snippet_returns_page_number_and_bounding_box(tmp_path):
    pdf_path = tmp_path / "resume.pdf"
    _write_test_pdf(pdf_path, "Jane Doe")

    result = find_text_bounding_box(pdf_path, "Jane Doe")

    assert result.page_number == 1
    assert result.bounding_box is not None
    assert result.bounding_box["unit"] == "points"
    assert result.bounding_box["x0"] < result.bounding_box["x1"]
    assert result.bounding_box["y0"] < result.bounding_box["y1"]
    assert result.source_method == "native_pdf"


def test_vision_page_index_returns_page_without_bounding_box(tmp_path):
    pdf_path = tmp_path / "scanned.pdf"
    _write_test_pdf(pdf_path, "")
    pages = (
        ExtractedPDFPage(
            page_number=1,
            text="Jane Doe\nSkills: Python",
            extraction_method="llm_vision_ocr",
            manual_review_required=True,
        ),
    )

    with use_vision_page_index(pdf_path, pages):
        result = find_text_bounding_box(pdf_path, "Jane Doe")

    assert result.page_number == 1
    assert result.source_method == "llm_vision_ocr"
    assert result.bounding_box is None


def test_vision_page_index_is_scoped_and_rejects_unanchored_text(tmp_path):
    pdf_path = tmp_path / "scanned.pdf"
    _write_test_pdf(pdf_path, "")
    pages = (
        ExtractedPDFPage(
            page_number=1,
            text="Python",
            extraction_method="llm_vision_ocr",
            manual_review_required=True,
        ),
    )

    with use_vision_page_index(pdf_path, pages):
        unsupported = find_text_bounding_box(pdf_path, "Kubernetes")
    outside_scope = find_text_bounding_box(pdf_path, "Python")

    assert unsupported.bounding_box is None
    assert unsupported.source_method == "llm_vision_ocr"
    assert outside_scope.bounding_box is None
    assert outside_scope.source_method is None


def _write_test_pdf(path: Path, text: str) -> None:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    document.save(path)
    document.close()
