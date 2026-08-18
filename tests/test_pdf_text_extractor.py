from __future__ import annotations

import base64
import os
from pathlib import Path
from types import SimpleNamespace

import fitz
import pytest

from icshps.agents.extraction.pdf_text_extractor import (
    PDFTextExtractor,
    extract_pdf_text,
)
from icshps.agents.extraction.vision_ocr import (
    DEFAULT_VISION_OCR_DPI,
    OpenAIVisionTranscriptionProvider,
    VISION_OCR_PROVIDER_NAME,
    VisionPageTranscription,
)


class FakeVisionProvider:
    provider_name = VISION_OCR_PROVIDER_NAME

    def __init__(self, text_by_page: dict[int, str]) -> None:
        self.text_by_page = text_by_page
        self.calls: list[dict[str, object]] = []

    def transcribe_page(
        self,
        *,
        image_bytes: bytes,
        page_number: int,
    ) -> VisionPageTranscription:
        self.calls.append(
            {
                "page_number": page_number,
                "is_png": image_bytes.startswith(b"\x89PNG"),
            }
        )
        text = self.text_by_page.get(page_number, "")
        if not text:
            raise RuntimeError("Vision provider returned no text")
        return VisionPageTranscription(page_number=page_number, text=text)


class FailingVisionProvider:
    provider_name = VISION_OCR_PROVIDER_NAME

    def __init__(self, message: str) -> None:
        self.message = message

    def transcribe_page(self, **kwargs) -> VisionPageTranscription:
        raise RuntimeError(self.message)


def test_missing_pdf_returns_controlled_failure(tmp_path: Path) -> None:
    result = extract_pdf_text(tmp_path / "missing.pdf")

    assert result.status == "missing_file"
    assert result.ok is False
    assert result.ocr_status == "not_needed"


def test_native_pdf_text_does_not_invoke_vision(tmp_path: Path) -> None:
    pdf_path = tmp_path / "native.pdf"
    _write_pdf(pdf_path, ["Jane Doe\nSkills: Python"])
    provider = FailingVisionProvider("Vision should not be called")

    result = PDFTextExtractor(
        vision_enabled=True,
        vision_provider=provider,
    ).extract(pdf_path)

    assert result.status == "success"
    assert "Jane Doe" in result.text
    assert result.pages[0].extraction_method == "native_pdf"
    assert result.ocr_status == "not_needed"
    assert result.scan_detected_pages == ()
    assert result.ocr_attempted_pages == ()


def test_image_pdf_remains_controlled_when_vision_disabled(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scanned.pdf"
    _write_image_based_pdf(pdf_path, "Jane Doe Skills Python")

    result = PDFTextExtractor(vision_enabled=False).extract(pdf_path)

    assert result.status == "pdf_text_empty"
    assert result.ocr_status == "disabled"
    assert result.scan_detected_pages == (1,)
    assert result.ocr_attempted_pages == ()
    assert result.ocr_metrics()["scan_detected"] is True
    assert "Enable LLM vision OCR" in result.issues[0]


def test_image_pdf_uses_vision_transcription(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scanned.pdf"
    _write_image_based_pdf(pdf_path, "Jane Doe Skills Python")
    provider = FakeVisionProvider({1: "Jane Doe\nSkills: Python"})

    result = PDFTextExtractor(
        vision_enabled=True,
        vision_dpi=200,
        vision_provider=provider,
    ).extract(pdf_path)

    assert result.status == "success"
    assert result.text == "Jane Doe\nSkills: Python"
    assert result.pages[0].extraction_method == "llm_vision_ocr"
    assert result.pages[0].manual_review_required is True
    assert result.ocr_status == "success"
    assert result.ocr_available is True
    assert result.scan_detected_pages == (1,)
    assert result.ocr_attempted_pages == (1,)
    assert result.ocr_succeeded_pages == (1,)
    assert result.ocr_provider == VISION_OCR_PROVIDER_NAME
    assert result.ocr_manual_review_required is True
    assert result.ocr_metrics()["extraction_methods"] == ["llm_vision_ocr"]
    assert provider.calls == [{"page_number": 1, "is_png": True}]


def test_image_dominant_page_with_little_native_text_uses_vision(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "image-dominant-low-text.pdf"
    _write_image_based_pdf(
        pdf_path,
        "Jane Doe experienced Python engineer",
        overlay_text="Page 1",
    )
    vision_text = (
        "Jane Doe\nExperienced Python software engineer with backend systems "
        "experience, SQL, Docker, FastAPI, testing, deployment, and cloud skills."
    )
    provider = FakeVisionProvider({1: vision_text})

    result = PDFTextExtractor(
        vision_enabled=True,
        vision_provider=provider,
    ).extract(pdf_path)

    assert result.status == "success"
    assert result.pages[0].extraction_method == "llm_vision_ocr"
    assert result.text == vision_text
    assert [call["page_number"] for call in provider.calls] == [1]


def test_mixed_pdf_transcribes_only_image_pages_and_preserves_order(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "mixed.pdf"
    _write_mixed_pdf(pdf_path)
    provider = FakeVisionProvider({2: "Scanned middle page"})

    result = PDFTextExtractor(
        vision_enabled=True,
        vision_provider=provider,
    ).extract(pdf_path)

    assert result.status == "success"
    assert result.text == "Native page\n\nScanned middle page\n\nFinal native page"
    assert [page.extraction_method for page in result.pages] == [
        "native_pdf",
        "llm_vision_ocr",
        "native_pdf",
    ]
    assert [call["page_number"] for call in provider.calls] == [2]


def test_blank_page_is_skipped_instead_of_sent_to_vision(tmp_path: Path) -> None:
    pdf_path = tmp_path / "blank-trailing-page.pdf"
    _write_pdf(pdf_path, ["Jane Doe Skills Python", None])
    provider = FailingVisionProvider("Blank page should not be sent")

    result = PDFTextExtractor(
        vision_enabled=True,
        vision_provider=provider,
    ).extract(pdf_path)

    assert result.status == "success"
    assert result.text == "Jane Doe Skills Python"
    assert result.ocr_attempted_pages == ()
    assert result.ocr_status == "not_needed"


def test_missing_openai_key_is_reported_without_crashing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    pdf_path = tmp_path / "scanned.pdf"
    _write_image_based_pdf(pdf_path, "Jane Doe Skills Python")

    result = PDFTextExtractor(vision_enabled=True).extract(pdf_path)

    assert result.status == "pdf_text_empty"
    assert result.ocr_status == "unavailable"
    assert result.ocr_available is False
    assert result.scan_detected_pages == (1,)
    assert result.ocr_failed_pages == (1,)
    assert result.ocr_manual_review_required is False
    assert "OPENAI_API_KEY is not configured" in result.issues[0]


def test_responses_permission_failure_is_controlled(tmp_path: Path) -> None:
    pdf_path = tmp_path / "scanned.pdf"
    _write_image_based_pdf(pdf_path, "Jane Doe Skills Python")

    result = PDFTextExtractor(
        vision_enabled=True,
        vision_provider=FailingVisionProvider("status code: 403 permission denied"),
    ).extract(pdf_path)

    assert result.status == "pdf_text_empty"
    assert result.ocr_status == "unavailable"
    assert result.ocr_failed_pages == (1,)
    assert "permission denied" in result.issues[0]


def test_partial_multi_page_vision_failure_keeps_successful_text(
    tmp_path: Path,
) -> None:
    pdf_path = tmp_path / "partial.pdf"
    _write_two_image_page_pdf(pdf_path)

    class PartialProvider(FakeVisionProvider):
        def transcribe_page(self, *, image_bytes: bytes, page_number: int):
            if page_number == 2:
                raise RuntimeError("temporary API failure")
            return super().transcribe_page(
                image_bytes=image_bytes,
                page_number=page_number,
            )

    result = PDFTextExtractor(
        vision_enabled=True,
        vision_provider=PartialProvider({1: "Jane Doe Skills Python"}),
    ).extract(pdf_path)

    assert result.status == "success"
    assert result.text == "Jane Doe Skills Python"
    assert result.ocr_status == "partial_success"
    assert result.ocr_succeeded_pages == (1,)
    assert result.ocr_failed_pages == (2,)
    assert result.ocr_manual_review_required is True


def test_invalid_vision_dpi_env_uses_default(monkeypatch) -> None:
    monkeypatch.setenv("ICSHPS_VISION_OCR_DPI", "not-a-number")

    extractor = PDFTextExtractor()

    assert extractor.vision_dpi == DEFAULT_VISION_OCR_DPI


def test_openai_provider_sends_base64_png_to_responses_api() -> None:
    captured: dict[str, object] = {}

    class FakeResponses:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(output_text="Jane Doe\nSkills: Python")

    client = SimpleNamespace(responses=FakeResponses())
    provider = OpenAIVisionTranscriptionProvider(client=client)

    result = provider.transcribe_page(
        image_bytes=b"\x89PNG\r\n\x1a\nimage-bytes",
        page_number=3,
    )

    assert result.page_number == 3
    assert result.text == "Jane Doe\nSkills: Python"
    assert captured["model"] == "gpt-4o-mini"
    content = captured["input"][0]["content"]
    image_item = content[1]
    assert image_item["type"] == "input_image"
    assert image_item["detail"] == "high"
    encoded = image_item["image_url"].split(",", 1)[1]
    assert base64.b64decode(encoded).startswith(b"\x89PNG")


@pytest.mark.live_api
@pytest.mark.skipif(
    os.getenv("ICSHPS_RUN_VISION_OCR_SMOKE_TEST", "").lower() != "true",
    reason="Set ICSHPS_RUN_VISION_OCR_SMOKE_TEST=true to allow a live API call.",
)
def test_live_openai_vision_ocr_smoke(tmp_path: Path) -> None:
    pdf_path = tmp_path / "vision-smoke.pdf"
    _write_image_based_pdf(pdf_path, "Jane Doe Skills Python")

    result = PDFTextExtractor(vision_enabled=True).extract(pdf_path)

    assert result.status == "success"
    assert "Jane Doe" in result.text
    assert result.ocr_status == "success"


def _write_pdf(path: Path, page_texts: list[str | None]) -> None:
    document = fitz.open()
    for text in page_texts:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
    document.save(path)
    document.close()


def _render_text_image(text: str) -> bytes:
    source = fitz.open()
    source_page = source.new_page()
    source_page.insert_text((72, 72), text, fontsize=18)
    image_bytes = source_page.get_pixmap(dpi=150, alpha=False).tobytes("png")
    source.close()
    return image_bytes


def _write_image_based_pdf(
    path: Path,
    image_text: str,
    *,
    overlay_text: str | None = None,
) -> None:
    scanned = fitz.open()
    scanned_page = scanned.new_page()
    scanned_page.insert_image(scanned_page.rect, stream=_render_text_image(image_text))
    if overlay_text:
        scanned_page.insert_text((72, 820), overlay_text)
    scanned.save(path)
    scanned.close()


def _write_mixed_pdf(path: Path) -> None:
    document = fitz.open()
    first = document.new_page()
    first.insert_text((72, 72), "Native page")
    middle = document.new_page()
    middle.insert_image(middle.rect, stream=_render_text_image("Scanned middle page"))
    final = document.new_page()
    final.insert_text((72, 72), "Final native page")
    document.save(path)
    document.close()


def _write_two_image_page_pdf(path: Path) -> None:
    document = fitz.open()
    for text in ("Jane Doe Skills Python", "Second scanned page"):
        page = document.new_page()
        page.insert_image(page.rect, stream=_render_text_image(text))
    document.save(path)
    document.close()
