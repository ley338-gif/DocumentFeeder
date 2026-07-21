from io import BytesIO
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen.canvas import Canvas

from document_core.processing import TextExtractor


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
    pdf = tmp_path / "arztbrief.pdf"
    create_text_pdf(
        pdf,
        [["Arztbrief", "Patient: Erika Mustermann"], ["Fallnummer: PDF-42", "Befund folgt"]],
    )

    result = TextExtractor().extract(pdf)

    assert result.method == "pdf_text"
    assert result.page_count == 2
    assert result.ocr_pages == []
    assert "Erika Mustermann" in result.text
    assert "PDF-42" in result.text


def test_uses_ocr_for_pdf_page_without_text_layer(tmp_path: Path, monkeypatch):
    pdf = tmp_path / "scan.pdf"
    create_text_pdf(pdf, [[]])
    extractor = TextExtractor()
    monkeypatch.setattr(
        extractor,
        "_ocr_pdf_page",
        lambda _path, _page: "Arztbrief\nPatient: OCR Patient\nFallnummer: OCR-1",
    )

    result = extractor.extract(pdf)

    assert result.method == "pdf_ocr"
    assert result.ocr_pages == [1]
    assert "OCR Patient" in result.text
