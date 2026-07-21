from pathlib import Path

from document_core.config import Settings
from document_core.connectors import FilesystemConnector
from document_core.models import JobStatus
from document_core.pipeline import DocumentPipeline
from document_core.store import JobStore


def test_text_document_reaches_filesystem_connector(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    settings.create_directories()
    source = tmp_path / "bericht.txt"
    source.write_text("Bericht\nBetreff: Beispiel\nReferenz: X-1", encoding="utf-8")
    pipeline = DocumentPipeline(settings, JobStore("sqlite://"), FilesystemConnector(settings.output_dir))

    job = pipeline.ingest(source, "test")

    assert job.status == JobStatus.DELIVERED
    assert Path(job.metadata["destination_reference"]).exists()
    assert (settings.output_dir / "report" / job.id / "metadata.json").exists()

    duplicate = pipeline.ingest(source, "test")
    assert duplicate.id == job.id
    assert len(pipeline.store.list()) == 1
