import re
from pathlib import Path


class TextExtractor:
    """Extract text without coupling the pipeline to a specific OCR product."""

    TEXT_SUFFIXES = {".txt", ".csv", ".json", ".xml"}

    def __init__(self, language: str = "deu+eng"):
        self.language = language

    def extract(self, path: Path) -> str:
        if path.suffix.lower() in self.TEXT_SUFFIXES:
            return path.read_text(encoding="utf-8", errors="replace")
        try:
            import pytesseract
            from PIL import Image

            return pytesseract.image_to_string(Image.open(path), lang=self.language)
        except (ImportError, OSError) as exc:
            raise RuntimeError(f"OCR für {path.suffix or 'Dateityp'} nicht verfügbar: {exc}") from exc


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

