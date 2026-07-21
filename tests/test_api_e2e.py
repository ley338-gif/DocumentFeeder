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
    store = JobStore(settings.jobs_dir)
    pipeline = DocumentPipeline(settings, store, FilesystemConnector(settings.output_dir))
    monkeypatch.setattr(api_module, "settings", settings)
    monkeypatch.setattr(api_module, "store", store)
    monkeypatch.setattr(api_module, "pipeline", pipeline)
    return settings


def test_pdf_upload_reaches_connector_through_http_api(tmp_path: Path, monkeypatch):
    settings = configure_api(tmp_path, monkeypatch)
    pdf = text_pdf_bytes(
        [
            ["Arztbrief", "Patient: Erika Mustermann"],
            ["Geburtsdatum: 12.03.1980", "Fallnummer: API-42"],
        ]
    )

    with TestClient(api_module.app) as client:
        response = client.post(
            "/v1/documents", files={"file": ("arztbrief.pdf", pdf, "application/pdf")}
        )

    assert response.status_code == 201
    job = response.json()
    assert job["status"] == JobStatus.DELIVERED
    assert job["document_type"] == "arztbrief"
    assert job["metadata"]["patient_name"] == "Erika Mustermann"
    assert job["metadata"]["extraction_method"] == "pdf_text"
    destination = settings.output_dir / "arztbrief" / job["id"]
    assert (destination / "arztbrief.pdf").exists()
    assert (destination / "metadata.json").exists()


def test_unknown_pdf_is_quarantined_through_http_api(tmp_path: Path, monkeypatch):
    settings = configure_api(tmp_path, monkeypatch)
    pdf = text_pdf_bytes([["Dies ist ein synthetisches Dokument ohne bekannte Klassifikation."]])

    with TestClient(api_module.app) as client:
        response = client.post(
            "/v1/documents", files={"file": ("unknown.pdf", pdf, "application/pdf")}
        )

    assert response.status_code == 201
    job = response.json()
    assert job["status"] == JobStatus.QUARANTINED
    assert (settings.quarantine_dir / f"{job['id']}-unknown.pdf").exists()


def test_broken_pdf_fails_with_diagnostic_error(tmp_path: Path, monkeypatch):
    configure_api(tmp_path, monkeypatch)

    with TestClient(api_module.app) as client:
        response = client.post(
            "/v1/documents",
            files={"file": ("broken.pdf", b"not a pdf", "application/pdf")},
        )

    assert response.status_code == 201
    job = response.json()
    assert job["status"] == JobStatus.FAILED
    assert job["errors"]
    assert "PDF konnte nicht gelesen werden" in job["errors"][0]
