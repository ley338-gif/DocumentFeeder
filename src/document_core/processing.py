import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ExtractionResult:
    text: str
    method: str
    page_count: int = 1
    ocr_pages: list[int] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def metadata(self) -> dict[str, Any]:
        return {
            "extraction_method": self.method,
            "page_count": self.page_count,
            "ocr_pages": self.ocr_pages,
            "extraction_warnings": self.warnings,
        }


class DocumentExtractor(ABC):
    """Provider-neutral contract for extracting text from a document."""

    @abstractmethod
    def extract(self, path: Path) -> ExtractionResult:
        """Return normalized text and diagnostic extraction metadata."""


class DefaultDocumentExtractor(DocumentExtractor):
    """Built-in plain-text, PDF text-layer and Tesseract OCR extractor."""

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


@dataclass(frozen=True)
class ClassificationResult:
    document_type: str
    confidence: float
    evidence: list[str] = field(default_factory=list)
    provider: str = "rules"
    model_version: str = "rules-v1"

    def metadata(self) -> dict[str, Any]:
        return {
            "document_type": self.document_type,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "provider": self.provider,
            "model_version": self.model_version,
        }


class DocumentClassifier(ABC):
    """Provider-neutral contract for suggesting a document type."""

    @abstractmethod
    def classify(self, text: str) -> ClassificationResult:
        """Return a suggestion with confidence, evidence and version information."""


class RuleBasedDocumentClassifier(DocumentClassifier):
    DOCUMENT_TYPES = {
        "correspondence": ("anschreiben", "korrespondenz", "brief", "letter"),
        "report": ("bericht", "protokoll", "auswertung", "report"),
        "invoice": ("rechnung", "rechnungsnummer", "gesamtbetrag", "invoice"),
        "form": ("formular", "antrag", "fragebogen", "form"),
    }

    def classify(self, text: str) -> ClassificationResult:
        lowered = text.lower()
        matches = {
            name: [keyword for keyword in keywords if keyword in lowered]
            for name, keywords in self.DOCUMENT_TYPES.items()
        }
        document_type = max(matches, key=lambda name: len(matches[name]))
        evidence = matches[document_type]
        if not evidence:
            return ClassificationResult(document_type="unknown", confidence=0.0)
        total_matches = sum(len(values) for values in matches.values())
        return ClassificationResult(
            document_type=document_type,
            confidence=round(len(evidence) / total_matches, 3),
            evidence=evidence,
        )


class RuleBasedProcessor:
    """Deterministic metadata extraction kept separate from classification."""
    PATTERNS = {
        "subject_name": r"(?im)^\s*(?:Betreff|Objekt|Name)\s*:\s*([^\r\n]+)",
        "document_date": r"(?im)^\s*(?:Dokumentdatum|Datum)\s*:\s*([^\r\n]+)",
        "reference_id": r"(?im)^\s*(?:Referenz|Vorgangsnummer|Aktenzeichen)\s*:\s*([\w-]+)",
    }
    SUPPLIER_PATTERN = re.compile(
        r"(?im)^\s*([^\r\n]{2,150}?\b(?:GmbH(?:\s*&\s*Co\.\s*KG)?|AG|"
        r"UG(?:\s*\(haftungsbeschränkt\))?|KG|OHG|e\.K\.|Ltd\.?|Inc\.?))\b"
    )
    NUMERIC_DATE_PATTERN = re.compile(r"\b(\d{1,2}\.\d{1,2}\.(?:\d{2}|\d{4}))\b")
    NAMED_DATE_PATTERN = re.compile(
        r"(?i)\b((?:\d{1,2}\.\s*)?(?:Januar|Februar|März|Maerz|April|Mai|Juni|"
        r"Juli|August|September|Oktober|November|Dezember)\s+\d{4})\b"
    )
    INVOICE_NUMBER_PATTERN = re.compile(
        r"(?im)^\s*(?:Rechnungsnummer|Rechnungsnr\.?)\s*:?\s*"
        r"([A-Z0-9][A-Z0-9 ./_-]{2,50})\s*$"
    )

    def extract_metadata(self, text: str, document_type: str) -> dict[str, Any]:
        metadata: dict[str, Any] = {}
        for key, pattern in self.PATTERNS.items():
            if match := re.search(pattern, text):
                metadata[key] = match.group(1).strip()
        if document_type == "invoice" and (supplier := self.SUPPLIER_PATTERN.search(text)):
            metadata["supplier_name"] = supplier.group(1).strip(" ,.-")
        if document_type == "invoice" and "document_date" not in metadata:
            date_match = self.NUMERIC_DATE_PATTERN.search(text)
            if date_match is None:
                date_match = self.NAMED_DATE_PATTERN.search(text)
            if date_match is not None:
                metadata["document_date"] = date_match.group(1).strip()
        if document_type == "invoice" and (
            invoice_number := self.INVOICE_NUMBER_PATTERN.search(text)
        ):
            metadata["invoice_number"] = invoice_number.group(1).strip()
        return metadata

    def process(self, text: str) -> tuple[str, dict[str, Any]]:
        """Compatibility helper for the original combined processor API."""
        result = RuleBasedDocumentClassifier().classify(text)
        return result.document_type, self.extract_metadata(text, result.document_type)


class WorkflowRules:
    def __init__(self, require_routing_reference: bool = False):
        self.require_routing_reference = require_routing_reference

    def validate(self, document_type: str, has_routing_reference: bool = False) -> list[str]:
        errors = []
        if document_type == "unknown":
            errors.append("Dokumenttyp konnte nicht bestimmt werden")
        if self.require_routing_reference and not has_routing_reference:
            errors.append("Routing-Referenz fehlt")
        return errors
