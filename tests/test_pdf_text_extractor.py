from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Literal

import fitz


ExtractionStatus = Literal[
    "success",
    "missing_file",
    "unsupported_file",
    "empty_pdf",
    "pdf_text_empty",
    "corrupted_pdf",
    "extraction_error",
]


@dataclass(frozen=True)
class ExtractedPDFPage:
    """
    Text extracted from one PDF page.

    Page numbers are 1-based so they are easier to reference in audit logs
    and downstream evidence pointers.
    """

    page_number: int
    text: str


@dataclass(frozen=True)
class PDFTextExtractionResult:
    """
    Controlled result format for clean PDF resume text extraction.

    Example:
        from icshps.agents.extraction import extract_pdf_text

        result = extract_pdf_text("candidate_resume.pdf")
        if result.ok:
            print(result.text)
        else:
            print(result.status, result.issues)
    """

    source_path: str
    status: ExtractionStatus
    text: str = ""
    pages: tuple[ExtractedPDFPage, ...] = ()
    page_count: int = 0
    issues: tuple[str, ...] = field(default_factory=tuple)

    @property
    def ok(self) -> bool:
        return self.status == "success"


class PDFTextExtractor:
    """
    Extract text from clean, born-digital PDF resumes.

    Scope:
    - Supports selectable-text PDFs only.
    - Does not perform OCR.
    - Extracts pages in order.
    - Normalizes basic whitespace.
    - Returns controlled results for downstream processing.
    """

    def extract(self, file_path: str | Path) -> PDFTextExtractionResult:
        path = Path(file_path)

        if not path.exists():
            return self._failure(
                path,
                "missing_file",
                f"File does not exist: {path}",
            )

        if not path.is_file():
            return self._failure(
                path,
                "unsupported_file",
                f"Path is not a file: {path}",
            )

        if path.suffix.lower() != ".pdf":
            return self._failure(
                path,
                "unsupported_file",
                f"Unsupported file type: {path.suffix or 'no extension'}",
            )

        if path.stat().st_size == 0:
            return self._failure(
                path,
                "empty_pdf",
                "PDF file is empty.",
            )

        try:
            with fitz.open(path) as document:
                if document.page_count == 0:
                    return PDFTextExtractionResult(
                        source_path=str(path),
                        status="empty_pdf",
                        page_count=0,
                        issues=("PDF has no pages.",),
                    )

                extracted_pages: list[ExtractedPDFPage] = []

                for page_index in range(document.page_count):
                    page = document.load_page(page_index)
                    raw_text = page.get_text("text")
                    normalized_text = normalize_pdf_text(raw_text)

                    extracted_pages.append(
                        ExtractedPDFPage(
                            page_number=page_index + 1,
                            text=normalized_text,
                        )
                    )

                combined_text = join_page_texts(extracted_pages)

                if not combined_text:
                    return PDFTextExtractionResult(
                        source_path=str(path),
                        status="pdf_text_empty",
                        text="",
                        pages=tuple(extracted_pages),
                        page_count=document.page_count,
                        issues=(
                            "No selectable text was extracted. "
                            "The PDF may be scanned or image-based. OCR is out of scope for this task.",
                        ),
                    )

                return PDFTextExtractionResult(
                    source_path=str(path),
                    status="success",
                    text=combined_text,
                    pages=tuple(extracted_pages),
                    page_count=document.page_count,
                    issues=(),
                )

        except RuntimeError as exc:
            return self._failure(
                path,
                "corrupted_pdf",
                f"Could not read PDF. It may be corrupted or invalid. Details: {exc}",
            )
        except Exception as exc:
            return self._failure(
                path,
                "extraction_error",
                f"Unexpected PDF extraction error: {exc}",
            )

    @staticmethod
    def _failure(
        path: Path,
        status: ExtractionStatus,
        issue: str,
    ) -> PDFTextExtractionResult:
        return PDFTextExtractionResult(
            source_path=str(path),
            status=status,
            text="",
            pages=(),
            page_count=0,
            issues=(issue,),
        )


def normalize_pdf_text(text: str) -> str:
    """
    Normalize basic whitespace while preserving readable line breaks.

    This keeps extraction deterministic and suitable for downstream parsing.
    """
    if not text:
        return ""

    text = text.replace("\x00", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    lines = []
    for line in text.split("\n"):
        cleaned_line = re.sub(r"[ \t\f\v]+", " ", line).strip()
        if cleaned_line:
            lines.append(cleaned_line)

    return "\n".join(lines).strip()


def join_page_texts(pages: list[ExtractedPDFPage]) -> str:
    """
    Join page texts in original page order.

    Blank pages are skipped in the combined text but still preserved in the
    per-page result list.
    """
    non_empty_pages = [page.text for page in pages if page.text]
    return "\n\n".join(non_empty_pages).strip()


def extract_pdf_text(file_path: str | Path) -> PDFTextExtractionResult:
    """
    Convenience function for extracting text from a clean PDF resume.
    """
    return PDFTextExtractor().extract(file_path)
