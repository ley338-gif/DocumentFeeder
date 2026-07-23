from datetime import UTC, datetime, timedelta
from email.message import Message
from io import BytesIO
from pathlib import Path
import urllib.error

import pytest

from document_core.config import Settings
from document_core.connectors import (
    DeliveryReceipt,
    HttpConnector,
    PermanentConnectorError,
    TargetConnector,
    TemporaryConnectorError,
    parse_retry_after,
)
from document_core.models import DocumentJob, JobStatus, TargetSystem
from document_core.pipeline import DocumentPipeline
from document_core.store import JobStore


def job(tmp_path: Path) -> DocumentJob:
    document = tmp_path / "report.txt"
    document.write_text("synthetic content", encoding="utf-8")
    return DocumentJob(
        source="test", original_filename=document.name, stored_path=document, sha256="a" * 64
    )


def headers(**values: str) -> Message:
    result = Message()
    for key, value in values.items():
        result[key.replace("_", "-")] = value
    return result


def test_retry_after_supports_seconds_and_http_date():
    now = datetime(2026, 7, 23, 10, 0, tzinfo=UTC)
    assert parse_retry_after("120", now) == 120
    assert parse_retry_after("Thu, 23 Jul 2026 10:02:00 GMT", now) == 120
    assert parse_retry_after("invalid", now) is None


@pytest.mark.parametrize("status", [408, 429, 500, 502, 503, 504])
def test_temporary_http_status_uses_retry_after(tmp_path: Path, monkeypatch, status: int):
    connector = HttpConnector(TargetSystem(
        name="HTTP", kind="http", endpoint_url="https://example.test/documents"
    ))
    error = urllib.error.HTTPError(
        connector.target.endpoint_url,
        status,
        "temporary",
        headers(Retry_After="90"),
        BytesIO(b"temporarily unavailable"),
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))

    with pytest.raises(TemporaryConnectorError) as raised:
        connector.deliver(job(tmp_path))

    assert raised.value.status_code == status
    assert raised.value.retry_after_seconds == 90


def test_client_error_is_permanent(tmp_path: Path, monkeypatch):
    target = TargetSystem(name="HTTP", kind="http", endpoint_url="https://example.test")
    error = urllib.error.HTTPError(
        target.endpoint_url, 422, "invalid", headers(), BytesIO(b"invalid document")
    )
    monkeypatch.setattr("urllib.request.urlopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(error))

    with pytest.raises(PermanentConnectorError) as raised:
        HttpConnector(target).deliver(job(tmp_path))

    assert raised.value.status_code == 422


class FailingConnector(TargetConnector):
    def __init__(self, error: Exception):
        self.error = error

    def deliver(self, _job: DocumentJob) -> DeliveryReceipt:
        raise self.error

    def healthcheck(self) -> bool:
        return False


def test_pipeline_honors_retry_after(tmp_path: Path):
    settings = Settings(data_dir=tmp_path, worker_retry_base_seconds=1)
    settings.create_directories()
    store = JobStore("sqlite://")
    pipeline = DocumentPipeline(
        settings,
        store,
        FailingConnector(TemporaryConnectorError("busy", retry_after_seconds=90)),
    )
    source = tmp_path / "source.txt"
    source.write_text("Bericht\nBetreff: Retry", encoding="utf-8")
    pipeline.ingest(source, "test")

    result = pipeline.process(store.claim_next("worker", 60))

    assert result.status == JobStatus.RECEIVED
    assert result.next_attempt_at >= datetime.now(UTC) + timedelta(seconds=88)


def test_pipeline_does_not_retry_permanent_delivery_error(tmp_path: Path):
    settings = Settings(data_dir=tmp_path)
    settings.create_directories()
    store = JobStore("sqlite://")
    pipeline = DocumentPipeline(
        settings, store, FailingConnector(PermanentConnectorError("invalid", status_code=422))
    )
    source = tmp_path / "source.txt"
    source.write_text("Bericht\nBetreff: Permanent", encoding="utf-8")
    pipeline.ingest(source, "test")

    result = pipeline.process(store.claim_next("worker", 60))

    assert result.status == JobStatus.FAILED
    assert result.next_attempt_at is None
