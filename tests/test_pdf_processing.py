from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas
from pypdf import PdfReader, PdfWriter
import pytest

from document_core.processing import DefaultDocumentExtractor


def create_text_pdf(path: Path, pages: list[list[str]]) -> None:
    canvas = Canvas(str(path), pagesize=A4)
    for lines in pages:
        y = 800
        for line in lines:
            canvas.drawString(72, y, line)
            y -= 24
        canvas.showPage()
    canvas.save()


def text_pdf_bytes(pages: list[list[str]]) -> bytes:
    buffer = BytesIO()
    canvas = Canvas(buffer, pagesize=A4)
    for lines in pages:
        y = 800
        for line in lines:
            canvas.drawString(72, y, line)
            y -= 24
        canvas.showPage()
    canvas.save()
    return buffer.getvalue()


def test_extracts_native_text_from_multi_page_pdf(tmp_path: Path):
    pdf = tmp_path / "bericht.pdf"
    create_text_pdf(
        pdf,
        [["Bericht", "Betreff: Beispielobjekt"], ["Referenz: PDF-42", "Auswertung folgt"]],
    )

    result = DefaultDocumentExtractor().extract(pdf)

    assert result.method == "pdf_text"
    assert result.page_count == 2
    assert result.ocr_pages == []
    assert "Beispielobjekt" in result.text
    assert "PDF-42" in result.text


def test_uses_ocr_for_pdf_page_without_text_layer(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "scan.pdf"
    create_text_pdf(pdf, [[]])
    extractor = DefaultDocumentExtractor()
    monkeypatch.setattr(
        extractor,
        "_ocr_pdf_page",
        lambda _path, _page: "Bericht\nBetreff: OCR Objekt\nReferenz: OCR-1",
    )

    result = extractor.extract(pdf)

    assert result.method == "pdf_ocr"
    assert result.ocr_pages == [1]
    assert "OCR Objekt" in result.text


def test_rejects_pdf_above_page_limit(tmp_path: Path):
    pdf = tmp_path / "too-many-pages.pdf"
    create_text_pdf(pdf, [["Bericht mit ausreichend langem Text"]] * 2)

    with pytest.raises(RuntimeError, match="Limit von 1 Seiten"):
        DefaultDocumentExtractor(max_pdf_pages=1).extract(pdf)


def test_rejects_encrypted_pdf_with_clear_error(tmp_path: Path):
    source = tmp_path / "source.pdf"
    encrypted = tmp_path / "encrypted.pdf"
    create_text_pdf(source, [["Bericht mit ausreichend langem Text"]])
    writer = PdfWriter()
    for page in PdfReader(source).pages:
        writer.add_page(page)
    writer.encrypt("secret")
    with encrypted.open("wb") as target:
        writer.write(target)

    with pytest.raises(RuntimeError, match="verschlüsselt"):
        DefaultDocumentExtractor().extract(encrypted)


def test_rejects_image_above_pixel_limit():
    class Image:
        size = (11, 10)

    with pytest.raises(RuntimeError, match="100 Pixeln"):
        DefaultDocumentExtractor(max_image_pixels=100)._validate_image_size(Image())
