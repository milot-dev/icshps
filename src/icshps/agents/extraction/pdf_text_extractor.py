from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Literal

import fitz

from icshps.agents.extraction.vision_ocr import (
    OpenAIVisionTranscriptionProvider,
    VisionTranscriptionProvider,
    vision_ocr_dpi,
    vision_ocr_enabled,
)

MIN_USABLE_NATIVE_ALNUM_CHARACTERS = 80
MIN_USABLE_NATIVE_WORDS = 12
IMAGE_DOMINANCE_THRESHOLD = 0.50

ExtractionStatus = Literal[
    "success",
    "missing_file",
    "unsupported_file",
    "empty_pdf",
    "pdf_text_empty",
    "corrupted_pdf",
    "extraction_error",
]
PageExtractionMethod = Literal["native_pdf", "llm_vision_ocr"]
OCRStatus = Literal[
    "not_needed",
    "disabled",
    "success",
    "partial_success",
    "unavailable",
    "failed",
]


@dataclass(frozen=True)
class ExtractedPDFPage:
    """Text extracted from one PDF page, with 1-based page numbering."""

    page_number: int
    text: str
    extraction_method: PageExtractionMethod = "native_pdf"
    manual_review_required: bool = False


@dataclass(frozen=True)
class PDFTextExtractionResult:
    """Controlled PDF text result used by downstream profile extraction."""

    source_path: str
    status: ExtractionStatus
    text: str = ""
    pages: tuple[ExtractedPDFPage, ...] = ()
    page_count: int = 0
    issues: tuple[str, ...] = field(default_factory=tuple)
    ocr_enabled: bool = False
    ocr_available: bool | None = None
    ocr_status: OCRStatus = "not_needed"
    scan_detected_pages: tuple[int, ...] = ()
    ocr_attempted_pages: tuple[int, ...] = ()
    ocr_succeeded_pages: tuple[int, ...] = ()
    ocr_failed_pages: tuple[int, ...] = ()
    ocr_provider: str | None = None
    ocr_manual_review_required: bool = False

    @property
    def ok(self) -> bool:
        return self.status == "success"

    def ocr_metrics(self) -> dict[str, object]:
        extraction_methods = sorted(
            {page.extraction_method for page in self.pages if page.text}
        )
        return {
            "enabled": self.ocr_enabled,
            "available": self.ocr_available,
            "status": self.ocr_status,
            "scan_detected": bool(self.scan_detected_pages),
            "scan_detected_page_count": len(self.scan_detected_pages),
            "scan_detected_pages": list(self.scan_detected_pages),
            "attempted": bool(self.ocr_attempted_pages),
            "attempted_page_count": len(self.ocr_attempted_pages),
            "succeeded_page_count": len(self.ocr_succeeded_pages),
            "failed_page_count": len(self.ocr_failed_pages),
            "attempted_pages": list(self.ocr_attempted_pages),
            "succeeded_pages": list(self.ocr_succeeded_pages),
            "failed_pages": list(self.ocr_failed_pages),
            "provider": self.ocr_provider,
            "manual_review_required": self.ocr_manual_review_required,
            "extraction_methods": extraction_methods,
        }


class PDFTextExtractor:
    """Extract native PDF text and use vision transcription only when needed."""

    def __init__(
        self,
        *,
        vision_enabled: bool | None = None,
        vision_dpi: int | None = None,
        vision_provider: VisionTranscriptionProvider | None = None,
    ) -> None:
        self.vision_enabled = (
            vision_enabled if vision_enabled is not None else vision_ocr_enabled()
        )
        self.vision_dpi = vision_dpi if vision_dpi is not None else vision_ocr_dpi()
        self.vision_provider = vision_provider or OpenAIVisionTranscriptionProvider()

    def extract(self, file_path: str | Path) -> PDFTextExtractionResult:
        path = Path(file_path)

        validation_failure = self._validate_path(path)
        if validation_failure is not None:
            return validation_failure

        try:
            with fitz.open(path) as document:
                if document.page_count == 0:
                    return PDFTextExtractionResult(
                        source_path=str(path),
                        status="empty_pdf",
                        page_count=0,
                        issues=("PDF has no pages.",),
                        ocr_enabled=self.vision_enabled,
                    )

                extracted_pages: list[ExtractedPDFPage] = []
                issues: list[str] = []
                attempted_pages: list[int] = []
                scan_detected_pages: list[int] = []
                succeeded_pages: list[int] = []
                failed_pages: list[int] = []
                provider_unavailable = False

                for page_index in range(document.page_count):
                    page_number = page_index + 1
                    page = document.load_page(page_index)
                    native_text = normalize_pdf_text(page.get_text("text"))
                    needs_vision = _page_needs_vision(page, native_text)
                    if not needs_vision:
                        extracted_pages.append(
                            ExtractedPDFPage(
                                page_number=page_number,
                                text=native_text,
                            )
                        )
                        continue

                    scan_detected_pages.append(page_number)

                    if not self.vision_enabled:
                        extracted_pages.append(
                            ExtractedPDFPage(
                                page_number=page_number,
                                text=native_text,
                            )
                        )
                        continue

                    attempted_pages.append(page_number)
                    try:
                        page_image = page.get_pixmap(
                            dpi=self.vision_dpi,
                            alpha=False,
                        ).tobytes("png")
                        transcription = self.vision_provider.transcribe_page(
                            image_bytes=page_image,
                            page_number=page_number,
                        )

                        succeeded_pages.append(page_number)
                        extracted_pages.append(
                            ExtractedPDFPage(
                                page_number=page_number,
                                text=normalize_pdf_text(transcription.text),
                                extraction_method="llm_vision_ocr",
                                manual_review_required=True,
                            )
                        )
                    except Exception as exc:
                        failed_pages.append(page_number)
                        provider_unavailable = provider_unavailable or (
                            _is_vision_provider_unavailable(exc)
                        )
                        issues.append(
                            f"LLM vision OCR failed for PDF page {page_number}: {exc}"
                        )
                        extracted_pages.append(
                            ExtractedPDFPage(
                                page_number=page_number,
                                text=native_text,
                            )
                        )

                combined_text = join_page_texts(extracted_pages)
                ocr_status = _ocr_status(
                    enabled=self.vision_enabled,
                    attempted_pages=attempted_pages,
                    succeeded_pages=succeeded_pages,
                    failed_pages=failed_pages,
                    dependency_unavailable=provider_unavailable,
                )
                ocr_available = _ocr_availability(
                    attempted_pages=attempted_pages,
                    succeeded_pages=succeeded_pages,
                    dependency_unavailable=provider_unavailable,
                )
                ocr_provider = (
                    self.vision_provider.provider_name if attempted_pages else None
                )
                ocr_manual_review_required = bool(succeeded_pages)

                if not combined_text:
                    if not issues:
                        issues.append(
                            "No usable text was extracted. The PDF may be scanned or "
                            "image-based. Enable LLM vision OCR to process image pages."
                        )
                    return PDFTextExtractionResult(
                        source_path=str(path),
                        status="pdf_text_empty",
                        pages=tuple(extracted_pages),
                        page_count=document.page_count,
                        issues=tuple(issues),
                        ocr_enabled=self.vision_enabled,
                        ocr_available=ocr_available,
                        ocr_status=ocr_status,
                        scan_detected_pages=tuple(scan_detected_pages),
                        ocr_attempted_pages=tuple(attempted_pages),
                        ocr_succeeded_pages=tuple(succeeded_pages),
                        ocr_failed_pages=tuple(failed_pages),
                        ocr_provider=ocr_provider,
                        ocr_manual_review_required=ocr_manual_review_required,
                    )

                return PDFTextExtractionResult(
                    source_path=str(path),
                    status="success",
                    text=combined_text,
                    pages=tuple(extracted_pages),
                    page_count=document.page_count,
                    issues=tuple(issues),
                    ocr_enabled=self.vision_enabled,
                    ocr_available=ocr_available,
                    ocr_status=ocr_status,
                    scan_detected_pages=tuple(scan_detected_pages),
                    ocr_attempted_pages=tuple(attempted_pages),
                    ocr_succeeded_pages=tuple(succeeded_pages),
                    ocr_failed_pages=tuple(failed_pages),
                    ocr_provider=ocr_provider,
                    ocr_manual_review_required=ocr_manual_review_required,
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

    def _validate_path(self, path: Path) -> PDFTextExtractionResult | None:
        if not path.exists():
            return self._failure(path, "missing_file", f"File does not exist: {path}")
        if not path.is_file():
            return self._failure(
                path, "unsupported_file", f"Path is not a file: {path}"
            )
        if path.suffix.lower() != ".pdf":
            return self._failure(
                path,
                "unsupported_file",
                f"Unsupported file type: {path.suffix or 'no extension'}",
            )
        if path.stat().st_size == 0:
            return self._failure(path, "empty_pdf", "PDF file is empty.")
        return None

    def _failure(
        self,
        path: Path,
        status: ExtractionStatus,
        issue: str,
    ) -> PDFTextExtractionResult:
        return PDFTextExtractionResult(
            source_path=str(path),
            status=status,
            issues=(issue,),
            ocr_enabled=self.vision_enabled,
        )


def normalize_pdf_text(text: str) -> str:
    """Normalize basic whitespace while preserving readable line breaks."""
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
    """Join non-empty page texts in original page order."""
    return "\n\n".join(page.text for page in pages if page.text).strip()


def extract_pdf_text(file_path: str | Path) -> PDFTextExtractionResult:
    """Convenience function for native extraction with optional vision OCR."""
    return PDFTextExtractor().extract(file_path)


def _is_vision_provider_unavailable(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "openai_api_key",
            "not configured",
            "not installed",
            "permission",
            "authentication",
            "api key",
            "status code: 401",
            "status code: 403",
            "error code: 401",
            "error code: 403",
        )
    )


def _page_needs_vision(page: fitz.Page, native_text: str) -> bool:
    if not native_text:
        return _page_has_visual_content(page)
    if _native_text_is_usable(native_text):
        return False
    return _page_is_image_dominant(page)


def _native_text_is_usable(text: str) -> bool:
    alphanumeric_count = sum(character.isalnum() for character in text)
    word_count = len(re.findall(r"\b\w+\b", text, flags=re.UNICODE))
    return (
        alphanumeric_count >= MIN_USABLE_NATIVE_ALNUM_CHARACTERS
        or word_count >= MIN_USABLE_NATIVE_WORDS
    )


def _page_is_image_dominant(page: fitz.Page) -> bool:
    page_area = float(page.rect.width * page.rect.height)
    if page_area <= 0:
        return False

    image_area = 0.0
    try:
        for image in page.get_images(full=True):
            xref = int(image[0])
            for rect in page.get_image_rects(xref):
                clipped = rect & page.rect
                if clipped.is_empty:
                    continue
                image_area += float(clipped.width * clipped.height)
    except Exception:
        return False

    return min(image_area, page_area) / page_area >= IMAGE_DOMINANCE_THRESHOLD


def _page_has_visual_content(page: fitz.Page) -> bool:
    try:
        if page.get_images(full=True):
            return True
    except Exception:
        pass

    try:
        return bool(page.get_drawings())
    except Exception:
        return False


def _ocr_status(
    *,
    enabled: bool,
    attempted_pages: list[int],
    succeeded_pages: list[int],
    failed_pages: list[int],
    dependency_unavailable: bool,
) -> OCRStatus:
    if not attempted_pages:
        return "not_needed" if enabled else "disabled"
    if succeeded_pages and failed_pages:
        return "partial_success"
    if succeeded_pages:
        return "success"
    if dependency_unavailable:
        return "unavailable"
    return "failed"


def _ocr_availability(
    *,
    attempted_pages: list[int],
    succeeded_pages: list[int],
    dependency_unavailable: bool,
) -> bool | None:
    if not attempted_pages:
        return None
    if succeeded_pages:
        return True
    if dependency_unavailable:
        return False
    return True
