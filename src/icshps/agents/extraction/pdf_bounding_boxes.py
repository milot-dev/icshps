from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import fitz


@dataclass(frozen=True)
class PDFBoundingBoxResult:
    """Best-effort source location for a text snippet in a PDF."""

    page_number: int | None
    bounding_box: dict[str, float | str] | None


def find_text_bounding_box(
    pdf_path: str | Path | None,
    text_snippet: str | None,
) -> PDFBoundingBoxResult:
    """
    Locate selectable text in a born-digital PDF.

    This is intentionally best-effort and never performs OCR. Missing files,
    empty snippets, scanned PDFs, and PyMuPDF errors all return a null location.
    """
    if pdf_path is None or not text_snippet or not text_snippet.strip():
        return PDFBoundingBoxResult(page_number=None, bounding_box=None)

    path = Path(pdf_path)
    if not path.exists() or not path.is_file() or path.suffix.lower() != ".pdf":
        return PDFBoundingBoxResult(page_number=None, bounding_box=None)

    snippet = " ".join(text_snippet.split())
    if not snippet:
        return PDFBoundingBoxResult(page_number=None, bounding_box=None)

    try:
        with fitz.open(path) as document:
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                matches = page.search_for(snippet)
                if not matches:
                    continue

                rect = matches[0]
                return PDFBoundingBoxResult(
                    page_number=page_index + 1,
                    bounding_box={
                        "x0": float(rect.x0),
                        "y0": float(rect.y0),
                        "x1": float(rect.x1),
                        "y1": float(rect.y1),
                        "unit": "points",
                    },
                )
    except Exception:
        return PDFBoundingBoxResult(page_number=None, bounding_box=None)

    return PDFBoundingBoxResult(page_number=None, bounding_box=None)
