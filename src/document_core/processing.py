import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    method: str
    page_count: int = 1
    ocr_pages: list[int] = field(default_factory=list)

    def metadata(self) -> dict[str, Any]:
        return {
            "extraction_method": self.method,
            "page_count": self.page_count,
            "ocr_pages": self.ocr_pages,
        }


class TextExtractor:
    """Extract text without coupling the pipeline to a specific OCR product."""

    TEXT_SUFFIXES = {".txt", ".csv", ".json", ".xml"}

    def __init__(self, language: str = "deu+eng"):
        self.language = language

    MIN_NATIVE_TEXT_CHARACTERS = 20

    def extract(self, path: Path) -> ExtractionResult:
        if path.suffix.lower() in self.TEXT_SUFFIXES:
            return ExtractionResult(
                text=path.read_text(encoding="utf-8", errors="replace"), method="plain_text"
            )
        if path.suffix.lower() == ".pdf":
            return self._extract_pdf(path)
        return ExtractionResult(text=self._ocr_image(path), method="image_ocr")

    def _extract_pdf(self, path: Path) -> ExtractionResult:
        try:
            from pypdf import PdfReader

            reader = PdfReader(path)
        except Exception as exc:
            raise RuntimeError(f"PDF konnte nicht gelesen werden: {exc}") from exc

        if not reader.pages:
            raise RuntimeError("PDF enthält keine Seiten")

        texts: list[str] = []
        ocr_pages: list[int] = []
        for page_number, page in enumerate(reader.pages, start=1):
            try:
                native_text = page.extract_text() or ""
            except Exception:
                native_text = ""
            if len(native_text.strip()) >= self.MIN_NATIVE_TEXT_CHARACTERS:
                texts.append(native_text)
            else:
                texts.append(self._ocr_pdf_page(path, page_number - 1))
                ocr_pages.append(page_number)

        if not ocr_pages:
            method = "pdf_text"
        elif len(ocr_pages) == len(reader.pages):
            method = "pdf_ocr"
        else:
            method = "pdf_text+ocr"
        return ExtractionResult(
            text="\n\n".join(texts),
            method=method,
            page_count=len(reader.pages),
            ocr_pages=ocr_pages,
        )

    def _ocr_pdf_page(self, path: Path, zero_based_page: int) -> str:
        try:
            import pypdfium2 as pdfium

            document = pdfium.PdfDocument(path)
            page = document[zero_based_page]
            image = page.render(scale=2.5).to_pil()
            try:
                return self._ocr_image(image)
            finally:
                image.close()
                page.close()
                document.close()
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(
                f"OCR für PDF-Seite {zero_based_page + 1} fehlgeschlagen: {exc}"
            ) from exc

    def _ocr_image(self, image: Any) -> str:
        try:
            import pytesseract

            if isinstance(image, Path):
                from PIL import Image

                with Image.open(image) as opened_image:
                    return pytesseract.image_to_string(opened_image, lang=self.language)
            return pytesseract.image_to_string(image, lang=self.language)
        except (ImportError, OSError) as exc:
            raise RuntimeError(f"OCR nicht verfügbar: {exc}") from exc


class RuleBasedProcessor:
    """Deterministic baseline. AI implementations will conform to the same output shape."""

    DOCUMENT_TYPES = {
        "arztbrief": ("arztbrief", "entlassungsbericht", "anamnese"),
        "laborbefund": ("laborbefund", "laborwerte", "referenzbereich"),
        "rezept": ("rezept", "verordnung", "wirkstoff"),
        "rechnung": ("rechnung", "rechnungsnummer", "gesamtbetrag"),
    }
    PATTERNS = {
        "patient_name": r"(?im)^\s*Patient(?:in)?\s*:\s*([^\r\n]+)",
        "birth_date": r"(?im)^\s*Geburtsdatum\s*:\s*(\d{1,2}\.\d{1,2}\.\d{4})",
        "case_id": r"(?im)^\s*(?:Fallnummer|Fall-ID)\s*:\s*([\w-]+)",
    }

    def process(self, text: str) -> tuple[str, dict[str, str]]:
        lowered = text.lower()
        scores = {
            name: sum(keyword in lowered for keyword in keywords)
            for name, keywords in self.DOCUMENT_TYPES.items()
        }
        document_type = max(scores, key=scores.get) if scores and max(scores.values()) else "unknown"
        metadata: dict[str, str] = {}
        for key, pattern in self.PATTERNS.items():
            if match := re.search(pattern, text):
                metadata[key] = match.group(1).strip()
        return document_type, metadata


class WorkflowRules:
    def __init__(self, require_patient: bool = False):
        self.require_patient = require_patient

    def validate(self, document_type: str, metadata: dict[str, str]) -> list[str]:
        errors = []
        if document_type == "unknown":
            errors.append("Dokumenttyp konnte nicht bestimmt werden")
        if self.require_patient and not metadata.get("patient_name"):
            errors.append("Patient konnte nicht bestimmt werden")
        return errors
