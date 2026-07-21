from pathlib import Path
import json

from document_core.config import Settings
from document_core.connectors import FilesystemConnector
from document_core.models import JobStatus, TargetSystem
from document_core.pipeline import DocumentPipeline
from document_core.store import JobStore


def test_text_document_reaches_filesystem_connector(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    settings.create_directories()
    source = tmp_path / "bericht.txt"
    source.write_text("Bericht\nBetreff: Beispiel\nReferenz: X-1", encoding="utf-8")
    pipeline = DocumentPipeline(settings, JobStore("sqlite://"), FilesystemConnector(settings.output_dir))

    queued = pipeline.ingest(source, "test")
    job = pipeline.process(pipeline.store.claim_next("test-worker", 60))

    assert queued.status == JobStatus.RECEIVED
    assert job.status == JobStatus.DELIVERED
    assert Path(job.metadata["destination_reference"]).exists()
    assert (settings.output_dir / "report" / job.id / "metadata.json").exists()

    duplicate = pipeline.ingest(source, "test")
    assert duplicate.id == job.id
    assert len(pipeline.store.list()) == 1


def test_document_reaches_configured_http_target(tmp_path: Path, monkeypatch):
    settings = Settings(data_dir=tmp_path)
    settings.create_directories()
    source = tmp_path / "bericht-http.txt"
    source.write_text("Bericht\nBetreff: HTTP Ziel\nReferenz: H-1", encoding="utf-8")
    store = JobStore("sqlite://")
    target = TargetSystem(
        name="HTTP Sandbox",
        kind="http",
        endpoint_url="http://example.test/documents",
        bearer_token="secret",
        is_default=True,
    )
    store.save_target_system(target)
    captured = {}

    class Response:
        status = 201
        headers = {}

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def read(self):
            return b'{"reference":"remote:42"}'

    def fake_urlopen(request, timeout):
        captured["payload"] = json.loads(request.data)
        captured["authorization"] = request.headers["Authorization"]
        captured["timeout"] = timeout
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    pipeline = DocumentPipeline(settings, store, FilesystemConnector(settings.output_dir))

    queued = pipeline.ingest(source, "test")
    job = pipeline.process(store.claim_next("worker", 60))

    assert queued.target_system_id == target.id
    assert job.status == JobStatus.DELIVERED
    assert job.metadata["destination_reference"] == "remote:42"
    assert captured["payload"]["document_type"] == "report"
    assert captured["authorization"] == "Bearer secret"
    assert store.get_target_system(target.id).last_delivery_at is not None
