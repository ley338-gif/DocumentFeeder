from pathlib import Path

import pytest

from document_core.config import Settings
from document_core.connectors import FilesystemConnector
from document_core.models import JobStatus
from document_core.pipeline import DocumentPipeline
from document_core.processing import DocumentExtractor, ExtractionResult
from document_core.store import JobStore


class SyntheticExtractor(DocumentExtractor):
    def __init__(self):
        self.received_path: Path | None = None

    def extract(self, path: Path) -> ExtractionResult:
        self.received_path = path
        return ExtractionResult(
            text="Bericht\nBetreff: Austauschbarer Extraktor",
            method="synthetic_adapter",
            page_count=2,
            warnings=["synthetische Warnung"],
        )


def test_document_extractor_requires_an_implementation():
    with pytest.raises(TypeError):
        DocumentExtractor()


def test_pipeline_uses_injected_document_extractor(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    settings.create_directories()
    source = tmp_path / "input.bin"
    source.write_bytes(b"not readable by the default extractor")
    extractor = SyntheticExtractor()
    store = JobStore("sqlite://")
    pipeline = DocumentPipeline(
        settings,
        store,
        FilesystemConnector(settings.output_dir),
        extractor=extractor,
    )

    queued = pipeline.ingest(source, "contract-test")
    job = pipeline.process(store.claim_next("worker", 60))

    assert job.status == JobStatus.DELIVERED
    assert extractor.received_path == queued.stored_path
    assert job.metadata["extraction_method"] == "synthetic_adapter"
    assert job.metadata["page_count"] == 2
    assert job.metadata["extraction_warnings"] == ["synthetische Warnung"]
