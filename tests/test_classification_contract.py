from pathlib import Path

import pytest

from document_core.config import Settings
from document_core.connectors import FilesystemConnector
from document_core.models import JobStatus
from document_core.pipeline import DocumentPipeline
from document_core.processing import (
    ClassificationResult,
    DocumentClassifier,
    RuleBasedDocumentClassifier,
)
from document_core.store import JobStore


class SyntheticClassifier(DocumentClassifier):
    def classify(self, text: str) -> ClassificationResult:
        assert "beliebiger Inhalt" in text
        return ClassificationResult(
            document_type="form",
            confidence=0.82,
            evidence=["synthetic:test-case"],
            provider="synthetic",
            model_version="contract-v1",
        )


def test_document_classifier_requires_an_implementation():
    with pytest.raises(TypeError):
        DocumentClassifier()


def test_rule_classifier_exposes_evidence_and_version():
    result = RuleBasedDocumentClassifier().classify(
        "Rechnung\nRechnungsnummer: R-42\nGesamtbetrag: 12 Euro"
    )

    assert result.document_type == "invoice"
    assert result.confidence == 1.0
    assert result.evidence == ["rechnung", "rechnungsnummer", "gesamtbetrag"]
    assert result.provider == "rules"
    assert result.model_version == "rules-v1"


def test_pipeline_uses_injected_document_classifier(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    settings.create_directories()
    source = tmp_path / "document.txt"
    source.write_text("beliebiger Inhalt", encoding="utf-8")
    store = JobStore("sqlite://")
    pipeline = DocumentPipeline(
        settings,
        store,
        FilesystemConnector(settings.output_dir),
        classifier=SyntheticClassifier(),
    )

    pipeline.ingest(source, "contract-test")
    job = pipeline.process(store.claim_next("worker", 60))

    assert job.status == JobStatus.DELIVERED
    assert job.document_type == "form"
    assert job.metadata["classification"] == {
        "document_type": "form",
        "confidence": 0.82,
        "evidence": ["synthetic:test-case"],
        "provider": "synthetic",
        "model_version": "contract-v1",
    }
    event = next(
        item for item in store.list_events(job.id) if item.event_type == "classification_completed"
    )
    assert event.details["provider"] == "synthetic"
