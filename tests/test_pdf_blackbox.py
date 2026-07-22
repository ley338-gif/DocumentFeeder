from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.pdfgen.canvas import Canvas

from document_core.processing import DefaultDocumentExtractor
from tests.test_pdf_processing import create_text_pdf


def test_truncated_pdf_is_rejected_with_diagnostic_error(tmp_path: Path):
    pdf = tmp_path / "truncated.pdf"
    pdf.write_bytes(b"%PDF-1.7\n1 0 obj\n<< /Type /Catalog")

    with pytest.raises(RuntimeError, match="PDF konnte nicht gelesen werden"):
        DefaultDocumentExtractor().extract(pdf)


def test_empty_pdf_is_rejected(tmp_path: Path):
    pdf = tmp_path / "empty.pdf"
    writer = PdfWriter()
    with pdf.open("wb") as target:
        writer.write(target)

    with pytest.raises(RuntimeError, match="keine Seiten"):
        DefaultDocumentExtractor().extract(pdf)


def test_rotated_page_preserves_native_text(tmp_path: Path):
    source = tmp_path / "source.pdf"
    rotated = tmp_path / "rotated.pdf"
    create_text_pdf(source, [["Bericht", "Betreff: Gedrehte Dokumentseite"]])
    writer = PdfWriter()
    page = PdfReader(source).pages[0]
    writer.add_page(page.rotate(90))
    with rotated.open("wb") as target:
        writer.write(target)

    result = DefaultDocumentExtractor().extract(rotated)

    assert result.method == "pdf_text"
    assert result.ocr_pages == []
    assert "Gedrehte Dokumentseite" in result.text


def test_mixed_pdf_uses_native_text_and_page_specific_ocr(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "mixed.pdf"
    create_text_pdf(pdf, [["Bericht", "Betreff: Textseite mit genug Inhalt"], []])
    extractor = DefaultDocumentExtractor()
    requested_pages: list[int] = []

    def fake_ocr(_path: Path, page: int) -> str:
        requested_pages.append(page)
        return "Referenz: OCR-2"

    monkeypatch.setattr(extractor, "_ocr_pdf_page", fake_ocr)

    result = extractor.extract(pdf)

    assert result.method == "pdf_text+ocr"
    assert result.page_count == 2
    assert result.ocr_pages == [2]
    assert requested_pages == [1]
    assert "Textseite" in result.text
    assert "OCR-2" in result.text


def test_large_pdf_page_is_rejected_before_rendering(tmp_path: Path):
    pdf = tmp_path / "oversized-page.pdf"
    canvas = Canvas(str(pdf), pagesize=(10_000, 10_000))
    canvas.showPage()
    canvas.save()

    with pytest.raises(RuntimeError, match="Gerenderte PDF-Seite.*Pixeln"):
        DefaultDocumentExtractor(max_image_pixels=1_000_000).extract(pdf)


def test_ocr_timeout_is_forwarded_to_tesseract(monkeypatch):
    captured: dict[str, int] = {}

    def fake_image_to_string(_image, *, lang: str, timeout: int) -> str:
        assert lang == "deu"
        captured["timeout"] = timeout
        raise RuntimeError("Tesseract process timeout")

    monkeypatch.setitem(
        sys.modules,
        "pytesseract",
        SimpleNamespace(image_to_string=fake_image_to_string),
    )
    image = Image.new("RGB", (10, 10), "white")
    try:
        with pytest.raises(RuntimeError, match="timeout"):
            DefaultDocumentExtractor(language="deu", ocr_timeout_seconds=7)._ocr_image(image)
    finally:
        image.close()

    assert captured["timeout"] == 7
