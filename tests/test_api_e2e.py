from pathlib import Path

from fastapi.testclient import TestClient

import document_core.api as api_module
from document_core.config import Settings
from document_core.connectors import FilesystemConnector
from document_core.file_validation import MalwareDetectedError
from document_core.malware import MalwareScanner
from document_core.models import JobStatus
from document_core.pipeline import DocumentPipeline
from document_core.store import JobStore, TargetSystemRow
from tests.test_pdf_processing import text_pdf_bytes


def configure_api(tmp_path: Path, monkeypatch) -> Settings:
    settings = Settings(data_dir=tmp_path, auth_enabled=False)
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


def test_duplicate_upload_returns_existing_job_with_duplicate_marker(tmp_path: Path, monkeypatch):
    configure_api(tmp_path, monkeypatch)
    content = b"Bericht\nBetreff: Doppelter Inhalt"

    with TestClient(api_module.app) as client:
        first = client.post(
            "/v1/documents", files={"file": ("original.txt", content, "text/plain")}
        ).json()
        duplicate = client.post(
            "/v1/documents", files={"file": ("kopie.txt", content, "text/plain")}
        ).json()

    assert first["duplicate"] is False
    assert duplicate["duplicate"] is True
    assert duplicate["id"] == first["id"]
    assert len(api_module.store.list()) == 1
    assert not (tmp_path / "inbox" / f"{first['sha256'][:12]}-kopie.txt").exists()


def test_upload_rejects_oversized_file_before_ingestion(tmp_path: Path, monkeypatch):
    settings = configure_api(tmp_path, monkeypatch)
    settings.max_file_size_bytes = 8

    with TestClient(api_module.app) as client:
        response = client.post(
            "/v1/documents",
            files={"file": ("large.txt", b"more than eight bytes", "text/plain")},
        )

    assert response.status_code == 413
    assert api_module.store.list() == []
    assert list(settings.inbox_dir.iterdir()) == []


def test_upload_rejects_content_that_does_not_match_extension(tmp_path: Path, monkeypatch):
    settings = configure_api(tmp_path, monkeypatch)

    with TestClient(api_module.app) as client:
        response = client.post(
            "/v1/documents",
            files={"file": ("fake.pdf", b"plain text", "application/pdf")},
        )

    assert response.status_code == 415
    assert api_module.store.list() == []
    assert list(settings.inbox_dir.iterdir()) == []


def test_upload_returns_rejection_from_malware_scanner(tmp_path: Path, monkeypatch):
    settings = configure_api(tmp_path, monkeypatch)

    class RejectingScanner(MalwareScanner):
        def scan(self, path: Path):
            raise MalwareDetectedError("Malware erkannt: Test-Signatur")

    api_module.pipeline.malware_scanner = RejectingScanner()

    with TestClient(api_module.app) as client:
        response = client.post(
            "/v1/documents",
            files={"file": ("infected.txt", b"synthetic content", "text/plain")},
        )

    assert response.status_code == 422
    assert "Test-Signatur" in response.json()["detail"]
    assert api_module.store.list() == []
    assert list(settings.inbox_dir.iterdir()) == []


def test_broken_pdf_fails_with_diagnostic_error(tmp_path: Path, monkeypatch):
    configure_api(tmp_path, monkeypatch)
    api_module.pipeline.settings.worker_retry_base_seconds = 0

    with TestClient(api_module.app) as client:
        response = client.post(
            "/v1/documents",
            files={"file": ("broken.pdf", b"%PDF-broken", "application/pdf")},
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
        events = client.get(f"/v1/jobs/{uploaded['id']}/events")
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
    assert events.status_code == 200
    assert events.json()[0]["event_type"] == "ingested"
    assert content.headers["content-disposition"].startswith("inline")
    assert download.headers["content-disposition"].startswith("attachment")


def test_failed_job_can_be_requeued_from_api(tmp_path: Path, monkeypatch):
    configure_api(tmp_path, monkeypatch)
    api_module.pipeline.settings.worker_max_attempts = 1

    with TestClient(api_module.app) as client:
        uploaded = client.post(
            "/v1/documents",
            files={"file": ("broken.pdf", b"%PDF-broken", "application/pdf")},
        ).json()
        failed = process_next_job()
        response = client.post(f"/v1/jobs/{uploaded['id']}/retry")

    assert failed.status == JobStatus.FAILED
    assert response.status_code == 202
    retried = response.json()
    assert retried["status"] == JobStatus.RECEIVED
    assert retried["attempt_count"] == 0
    assert retried["last_error"] is None
    assert api_module.store.list_events(uploaded["id"])[-1].event_type == "manual_retry"


def test_input_channels_can_be_managed_through_api(tmp_path: Path, monkeypatch):
    configure_api(tmp_path, monkeypatch)

    with TestClient(api_module.app) as client:
        initial = client.get("/v1/input-channels")
        created = client.post(
            "/v1/input-channels",
            json={
                "name": "Scanner",
                "directory": "scanner/incoming",
                "patterns": ["*.pdf", "scan-*.tif"],
                "enabled": True,
            },
        )
        channel = created.json()
        paused = client.patch(
            f"/v1/input-channels/{channel['id']}", json={"enabled": False}
        )
        duplicate = client.post(
            "/v1/input-channels",
            json={"name": "Scanner", "directory": "another", "patterns": ["*"]},
        )
        deleted = client.delete(f"/v1/input-channels/{channel['id']}")

    assert initial.status_code == 200
    assert initial.json()[0]["directory"] == "hotfolder"
    assert created.status_code == 201
    assert (tmp_path / "scanner" / "incoming").is_dir()
    assert paused.json()["enabled"] is False
    assert duplicate.status_code == 409
    assert deleted.status_code == 204


def test_input_channel_rejects_paths_outside_data_directory(tmp_path: Path, monkeypatch):
    configure_api(tmp_path, monkeypatch)

    with TestClient(api_module.app) as client:
        traversal = client.post(
            "/v1/input-channels",
            json={"name": "Unsafe", "directory": "../outside", "patterns": ["*"]},
        )
        nested_pattern = client.post(
            "/v1/input-channels",
            json={"name": "Unsafe pattern", "directory": "safe", "patterns": ["*/x.pdf"]},
        )

    assert traversal.status_code == 422
    assert nested_pattern.status_code == 422


def test_target_systems_can_be_managed_without_exposing_tokens(tmp_path: Path, monkeypatch):
    configure_api(tmp_path, monkeypatch)

    with TestClient(api_module.app) as client:
        modules = client.get("/v1/connector-modules")
        initial = client.get("/v1/target-systems")
        created = client.post(
            "/v1/target-systems",
            json={
                "name": "Sandbox API",
                "kind": "http",
                "endpoint_url": "http://mock-target:8090/documents",
                "bearer_token": "top-secret",
                "timeout_seconds": 10,
                "enabled": True,
                "is_default": True,
            },
        )
        target = created.json()
        listing = client.get("/v1/target-systems")
        delete_default = client.delete(f"/v1/target-systems/{target['id']}")
        uninstalled = client.post(
            "/v1/target-systems", json={"name": "Missing", "kind": "not-installed"}
        )

    assert {item["id"] for item in modules.json()} == {"filesystem", "http"}
    assert all(item["licensed"] for item in modules.json())
    assert initial.json()[0]["kind"] == "filesystem"
    assert created.status_code == 201
    assert target["has_bearer_token"] is True
    assert "bearer_token" not in target
    assert all("bearer_token" not in item for item in listing.json())
    with api_module.store.sessions() as session:
        stored_token = session.get(TargetSystemRow, target["id"]).bearer_token
    assert stored_token.startswith("enc:v1:")
    assert "top-secret" not in stored_token
    assert delete_default.status_code == 409
    assert uninstalled.status_code == 422
    assert "nicht installiert" in uninstalled.json()["detail"]


def test_http_target_requires_valid_endpoint(tmp_path: Path, monkeypatch):
    configure_api(tmp_path, monkeypatch)

    with TestClient(api_module.app) as client:
        response = client.post(
            "/v1/target-systems",
            json={"name": "Broken", "kind": "http", "endpoint_url": "not-a-url"},
        )

    assert response.status_code == 422


def test_delivery_rules_can_be_managed_through_api(tmp_path: Path, monkeypatch):
    configure_api(tmp_path, monkeypatch)

    with TestClient(api_module.app) as client:
        target = client.get("/v1/target-systems").json()[0]
        created = client.post(
            "/v1/delivery-rules",
            json={
                "name": "Rechnungsablage",
                "document_type": "invoice",
                "target_system_id": target["id"],
                "path_template": "rechnungen/{year}/{month}/{job_id}",
                "enabled": True,
                "priority": 10,
            },
        )
        rule = created.json()
        listing = client.get("/v1/delivery-rules")
        paused = client.patch(
            f"/v1/delivery-rules/{rule['id']}", json={"enabled": False}
        )
        unsafe = client.post(
            "/v1/delivery-rules",
            json={
                "name": "Unsafe",
                "document_type": "report",
                "target_system_id": target["id"],
                "path_template": "../outside/{job_id}",
            },
        )

    assert created.status_code == 201
    assert listing.json()[0]["name"] == "Rechnungsablage"
    assert paused.json()["enabled"] is False
    assert unsafe.status_code == 422


def test_failed_document_can_be_deleted_with_working_copy(tmp_path: Path, monkeypatch):
    settings = configure_api(tmp_path, monkeypatch)
    api_module.pipeline.settings.worker_max_attempts = 1

    with TestClient(api_module.app) as client:
        uploaded = client.post(
            "/v1/documents",
            files={"file": ("delete-me.pdf", b"%PDF-broken", "application/pdf")},
        ).json()
        failed = process_next_job()
        stored_path = failed.stored_path
        response = client.delete(f"/v1/jobs/{uploaded['id']}")
        missing = client.get(f"/v1/jobs/{uploaded['id']}")

    assert failed.status == JobStatus.FAILED
    assert stored_path.parent == settings.inbox_dir
    assert response.status_code == 204
    assert missing.status_code == 404
    assert not stored_path.exists()


def test_active_processing_document_can_be_deleted(tmp_path: Path, monkeypatch):
    configure_api(tmp_path, monkeypatch)

    with TestClient(api_module.app) as client:
        uploaded = client.post(
            "/v1/documents",
            files={"file": ("active.txt", b"Bericht", "text/plain")},
        ).json()
        api_module.store.claim_next("active-worker", 60)
        response = client.delete(f"/v1/jobs/{uploaded['id']}")
        missing = client.get(f"/v1/jobs/{uploaded['id']}")

    assert response.status_code == 204
    assert missing.status_code == 404


def test_quarantined_document_can_be_deleted(tmp_path: Path, monkeypatch):
    configure_api(tmp_path, monkeypatch)

    with TestClient(api_module.app) as client:
        uploaded = client.post(
            "/v1/documents",
            files={"file": ("unknown.txt", b"synthetic unknown content", "text/plain")},
        ).json()
        quarantined = process_next_job()
        response = client.delete(f"/v1/jobs/{uploaded['id']}")

    assert quarantined.status == JobStatus.QUARANTINED
    assert response.status_code == 204
    assert not quarantined.stored_path.exists()
