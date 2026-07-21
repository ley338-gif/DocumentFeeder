from pathlib import Path

from fastapi.testclient import TestClient

import document_core.api as api_module
from document_core.config import Settings
from document_core.connectors import FilesystemConnector
from document_core.models import JobStatus
from document_core.pipeline import DocumentPipeline
from document_core.store import JobStore
from tests.test_pdf_processing import text_pdf_bytes


def configure_api(tmp_path: Path, monkeypatch) -> Settings:
    settings = Settings(data_dir=tmp_path)
    settings.create_directories()
    store = JobStore("sqlite://")
    pipeline = DocumentPipeline(settings, store, FilesystemConnector(settings.output_dir))
    monkeypatch.setattr(api_module, "settings", settings)
    monkeypatch.setattr(api_module, "store", store)
    monkeypatch.setattr(api_module, "pipeline", pipeline)
    return settings


def process_next_job():
    job = api_module.store.claim_next("test-worker", 60)
    assert job is not None
    return api_module.pipeline.process(job)


def test_pdf_upload_reaches_connector_through_http_api(tmp_path: Path, monkeypatch):
    settings = configure_api(tmp_path, monkeypatch)
    pdf = text_pdf_bytes(
        [
            ["Bericht", "Betreff: Beispielobjekt"],
            ["Datum: 12.03.2026", "Referenz: API-42"],
        ]
    )

    with TestClient(api_module.app) as client:
        response = client.post(
            "/v1/documents", files={"file": ("bericht.pdf", pdf, "application/pdf")}
        )

    assert response.status_code == 202
    assert response.json()["status"] == JobStatus.RECEIVED
    job = process_next_job().model_dump(mode="json")
    assert job["status"] == JobStatus.DELIVERED
    assert job["document_type"] == "report"
    assert job["metadata"]["subject_name"] == "Beispielobjekt"
    assert job["metadata"]["extraction_method"] == "pdf_text"
    destination = settings.output_dir / "report" / job["id"]
    assert (destination / "bericht.pdf").exists()
    assert (destination / "metadata.json").exists()


def test_unknown_pdf_is_quarantined_through_http_api(tmp_path: Path, monkeypatch):
    settings = configure_api(tmp_path, monkeypatch)
    pdf = text_pdf_bytes([["Dies ist ein synthetisches Dokument ohne bekannte Klassifikation."]])

    with TestClient(api_module.app) as client:
        response = client.post(
            "/v1/documents", files={"file": ("unknown.pdf", pdf, "application/pdf")}
        )

    assert response.status_code == 202
    job = process_next_job().model_dump(mode="json")
    assert job["status"] == JobStatus.QUARANTINED
    assert (settings.quarantine_dir / f"{job['id']}-unknown.pdf").exists()


def test_broken_pdf_fails_with_diagnostic_error(tmp_path: Path, monkeypatch):
    configure_api(tmp_path, monkeypatch)
    api_module.pipeline.settings.worker_retry_base_seconds = 0

    with TestClient(api_module.app) as client:
        response = client.post(
            "/v1/documents",
            files={"file": ("broken.pdf", b"not a pdf", "application/pdf")},
        )

    assert response.status_code == 202
    job = None
    for _ in range(api_module.pipeline.settings.worker_max_attempts):
        job = process_next_job().model_dump(mode="json")
    assert job["status"] == JobStatus.FAILED
    assert job["errors"]
    assert "PDF konnte nicht gelesen werden" in job["errors"][0]


def test_quarantined_document_can_be_reviewed_and_released(tmp_path: Path, monkeypatch):
    settings = configure_api(tmp_path, monkeypatch)
    pdf = text_pdf_bytes([["Unbekannter Inhalt mit ausreichend Text für die Extraktion."]])

    with TestClient(api_module.app) as client:
        uploaded = client.post(
            "/v1/documents", files={"file": ("review.pdf", pdf, "application/pdf")}
        ).json()
        assert uploaded["status"] == JobStatus.RECEIVED
        uploaded = process_next_job().model_dump(mode="json")
        assert uploaded["status"] == JobStatus.QUARANTINED

        reviewed_response = client.patch(
            f"/v1/jobs/{uploaded['id']}/review",
            json={
                "reviewer": "test-reviewer",
                "reason": "Dokument manuell zugeordnet",
                "document_type": "report",
                "routing_reference": {
                    "namespace": "test-system",
                    "type": "record",
                    "value": "R-9000",
                },
                "metadata": {"subject_name": "Manuell geprüft"},
            },
        )
        assert reviewed_response.status_code == 200
        reviewed = reviewed_response.json()
        assert reviewed["review_history"][0]["reviewer"] == "test-reviewer"
        assert reviewed["routing_reference"]["value"] == "R-9000"

        released_response = client.post(f"/v1/jobs/{uploaded['id']}/release")
        released_again = client.post(f"/v1/jobs/{uploaded['id']}/release")

    assert released_response.status_code == 200
    released = released_response.json()
    assert released["status"] == JobStatus.DELIVERED
    assert released_again.json()["metadata"]["destination_reference"] == released["metadata"][
        "destination_reference"
    ]
    destination = settings.output_dir / "report" / uploaded["id"]
    assert (destination / "review.pdf").exists()
    assert (destination / "metadata.json").exists()


def test_non_quarantined_document_cannot_be_reviewed(tmp_path: Path, monkeypatch):
    configure_api(tmp_path, monkeypatch)
    pdf = text_pdf_bytes([["Bericht", "Betreff: Bereits klassifiziert"]])

    with TestClient(api_module.app) as client:
        job = client.post(
            "/v1/documents", files={"file": ("delivered.pdf", pdf, "application/pdf")}
        ).json()
        assert job["status"] == JobStatus.RECEIVED
        job = process_next_job().model_dump(mode="json")
        response = client.patch(
            f"/v1/jobs/{job['id']}/review",
            json={"reviewer": "test-reviewer", "reason": "Nicht erlaubt"},
        )

    assert job["status"] == JobStatus.DELIVERED
    assert response.status_code == 409


def test_frontend_job_api_supports_stats_pagination_and_content(tmp_path: Path, monkeypatch):
    configure_api(tmp_path, monkeypatch)
    source = b"Bericht\nBetreff: Frontend API\nReferenz: UI-1"

    with TestClient(api_module.app) as client:
        home = client.get("/")
        uploaded = client.post(
            "/v1/documents", files={"file": ("frontend.txt", source, "text/plain")}
        ).json()
        listing = client.get("/v1/jobs", params={"status": "received", "limit": 1})
        stats = client.get("/v1/jobs/stats")
        content = client.get(f"/v1/jobs/{uploaded['id']}/content")
        download = client.get(
            f"/v1/jobs/{uploaded['id']}/content", params={"download": "true"}
        )

    assert home.status_code == 200
    assert "Document Core" in home.text
    assert listing.status_code == 200
    assert listing.json()["total"] == 1
    assert listing.json()["items"][0]["id"] == uploaded["id"]
    assert stats.json()["by_status"]["received"] == 1
    assert content.content == source
    assert content.headers["content-disposition"].startswith("inline")
    assert download.headers["content-disposition"].startswith("attachment")


def test_failed_job_can_be_requeued_from_api(tmp_path: Path, monkeypatch):
    configure_api(tmp_path, monkeypatch)
    api_module.pipeline.settings.worker_max_attempts = 1

    with TestClient(api_module.app) as client:
        uploaded = client.post(
            "/v1/documents",
            files={"file": ("broken.pdf", b"not a pdf", "application/pdf")},
        ).json()
        failed = process_next_job()
        response = client.post(f"/v1/jobs/{uploaded['id']}/retry")

    assert failed.status == JobStatus.FAILED
    assert response.status_code == 202
    retried = response.json()
    assert retried["status"] == JobStatus.RECEIVED
    assert retried["attempt_count"] == 0
    assert retried["last_error"] is None
