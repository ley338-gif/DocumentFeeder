from pathlib import Path
import json

from document_core.config import Settings
from document_core.connectors import FilesystemConnector
from document_core.models import DeliveryRule, JobStatus, TargetSystem
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
    events = pipeline.store.list_events(job.id)
    assert [event.event_type for event in events] == [
        "ingested",
        "processing_started",
        "delivery_started",
        "delivery_succeeded",
    ]
    delivered = events[-1]
    assert delivered.external_reference == job.metadata["destination_reference"]
    assert delivered.completed_at is not None

    duplicate = pipeline.ingest(source, "test")
    assert duplicate.id == job.id
    assert len(pipeline.store.list()) == 1


def test_extracted_null_bytes_are_removed_before_persistence(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    settings.create_directories()
    source = tmp_path / "nul.txt"
    source.write_bytes(b"Bericht\x00\nBetreff: Nullzeichen")
    pipeline = DocumentPipeline(
        settings, JobStore("sqlite://"), FilesystemConnector(settings.output_dir)
    )

    pipeline.ingest(source, "test")
    job = pipeline.process(pipeline.store.claim_next("worker", 60))

    assert job.status == JobStatus.DELIVERED
    assert "\x00" not in job.text_preview


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
    delivery = store.list_events(job.id)[-1]
    assert delivery.event_type == "delivery_succeeded"
    assert delivery.target_name == "HTTP Sandbox"
    assert delivery.external_reference == "remote:42"


def test_delivery_rule_routes_invoice_to_configured_folder(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    settings.create_directories()
    source = tmp_path / "rechnung.txt"
    source.write_text(
        "Telekom Deutschland GmbH\nRechnung\nRechnungsnummer 730 753 0647\n"
        "Datum: 21. Juni 2026\nReferenz: R-4711",
        encoding="utf-8",
    )
    store = JobStore("sqlite://")
    default = TargetSystem(name="Standard", kind="filesystem", is_default=True)
    invoices = TargetSystem(
        name="Rechnungsarchiv",
        kind="filesystem",
        directory="archive",
        path_template="invoices/{year}/{month}/{job_id}",
    )
    store.save_target_system(default)
    store.save_target_system(invoices)
    store.save_delivery_rule(
        DeliveryRule(
            name="Rechnungen ablegen",
            document_type="invoice",
            target_system_id=invoices.id,
            path_template=(
                "rechnungen/{year}/{month}/{supplier_name}/"
                "{year}-{month}_{supplier_name}_{invoice_number}{extension}"
            ),
        )
    )
    pipeline = DocumentPipeline(settings, store, FilesystemConnector(settings.output_dir))

    queued = pipeline.ingest(source, "test")
    job = pipeline.process(store.claim_next("worker", 60))

    assert queued.target_system_id == default.id
    assert job.target_system_id == invoices.id
    assert job.metadata["delivery_rule"] == "Rechnungen ablegen"
    assert job.metadata["supplier_name"] == "Telekom Deutschland GmbH"
    assert (
        tmp_path
        / "archive"
        / "rechnungen"
        / "2026"
        / "06"
        / "Telekom_Deutschland_GmbH"
        / "2026-06_Telekom_Deutschland_GmbH_7307530647.txt"
    ).exists()
    assert (
        tmp_path
        / "archive"
        / "rechnungen"
        / "2026"
        / "06"
        / "Telekom_Deutschland_GmbH"
        / "2026-06_Telekom_Deutschland_GmbH_7307530647.metadata.json"
    ).exists()
