from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Iterator, Sequence

import fitz

from icshps.agents.extraction.pdf_text_extractor import ExtractedPDFPage


@dataclass(frozen=True)
class PDFBoundingBoxResult:
    """Best-effort source location for a text snippet in a PDF."""

    page_number: int | None
    bounding_box: dict[str, float | str] | None
    source_method: str | None = None


_VISION_PAGE_INDEX: ContextVar[dict[str, tuple[ExtractedPDFPage, ...]]] = ContextVar(
    "icshps_vision_page_index", default={}
)


@contextmanager
def use_vision_page_index(
    pdf_path: str | Path,
    pages: Sequence[ExtractedPDFPage],
) -> Iterator[None]:
    """Expose vision-transcribed page text during profile parsing."""
    key = _path_key(Path(pdf_path))
    current = dict(_VISION_PAGE_INDEX.get())
    current[key] = tuple(
        page for page in pages if page.extraction_method == "llm_vision_ocr"
    )
    token = _VISION_PAGE_INDEX.set(current)
    try:
        yield
    finally:
        _VISION_PAGE_INDEX.reset(token)


def find_text_bounding_box(
    pdf_path: str | Path | None,
    text_snippet: str | None,
) -> PDFBoundingBoxResult:
    """Locate a snippet in native text or a vision-transcribed PDF page."""
    if pdf_path is None or not text_snippet or not text_snippet.strip():
        return _empty_result()

    path = Path(pdf_path)
    if not path.exists() or not path.is_file() or path.suffix.lower() != ".pdf":
        return _empty_result()

    snippet = " ".join(text_snippet.split())
    if not snippet:
        return _empty_result()

    native_result = _find_native_text(path, snippet)
    if native_result.bounding_box is not None:
        return native_result

    return _find_vision_text(path, snippet)


def _find_native_text(path: Path, snippet: str) -> PDFBoundingBoxResult:
    try:
        with fitz.open(path) as document:
            for page_index in range(document.page_count):
                matches = document.load_page(page_index).search_for(snippet)
                if not matches:
                    continue
                return PDFBoundingBoxResult(
                    page_number=page_index + 1,
                    bounding_box=_rect_payload(matches[0]),
                    source_method="native_pdf",
                )
    except Exception:
        return _empty_result()
    return _empty_result()


def _find_vision_text(path: Path, snippet: str) -> PDFBoundingBoxResult:
    index = _VISION_PAGE_INDEX.get()
    path_key = _path_key(path)
    if path_key not in index:
        return _empty_result()

    pages = index[path_key]
    target = _normalized_match_text(snippet)
    if not pages or not target:
        return _unlocated_vision_result()

    for page in sorted(pages, key=lambda item: item.page_number):
        if target not in _normalized_match_text(page.text):
            continue
        return PDFBoundingBoxResult(
            page_number=page.page_number,
            bounding_box=None,
            source_method="llm_vision_ocr",
        )

    return _unlocated_vision_result()


def _normalized_match_text(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _path_key(path: Path) -> str:
    try:
        return str(path.resolve()).casefold()
    except OSError:
        return str(path.absolute()).casefold()


def _rect_payload(rect: fitz.Rect) -> dict[str, float | str]:
    return {
        "x0": float(rect.x0),
        "y0": float(rect.y0),
        "x1": float(rect.x1),
        "y1": float(rect.y1),
        "unit": "points",
    }


def _empty_result() -> PDFBoundingBoxResult:
    return PDFBoundingBoxResult(
        page_number=None,
        bounding_box=None,
        source_method=None,
    )


def _unlocated_vision_result() -> PDFBoundingBoxResult:
    return PDFBoundingBoxResult(
        page_number=None,
        bounding_box=None,
        source_method="llm_vision_ocr",
    )
