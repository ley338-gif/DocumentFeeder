from pathlib import Path
import signal
import threading

from document_core.config import Settings
from document_core.connectors import FilesystemConnector
from document_core.models import JobStatus
from document_core.pipeline import DocumentPipeline
from document_core.store import JobStore
from document_core.worker import install_shutdown_handlers


def test_technical_failure_retries_then_fails(tmp_path: Path, monkeypatch):
    settings = Settings(
        data_dir=tmp_path,
        worker_max_attempts=2,
        worker_retry_base_seconds=0,
    )
    settings.create_directories()
    source = tmp_path / "document.txt"
    source.write_text("synthetic", encoding="utf-8")
    store = JobStore("sqlite://")
    pipeline = DocumentPipeline(settings, store, FilesystemConnector(settings.output_dir))
    monkeypatch.setattr(
        pipeline.extractor, "extract", lambda _path: (_ for _ in ()).throw(RuntimeError("boom"))
    )

    queued = pipeline.ingest(source, "test")
    first = pipeline.process(store.claim_next("worker-1", 60))
    second = pipeline.process(store.claim_next("worker-1", 60))

    assert queued.status == JobStatus.RECEIVED
    assert first.status == JobStatus.RECEIVED
    assert first.attempt_count == 1
    assert second.status == JobStatus.FAILED
    assert second.attempt_count == 2
    assert second.last_error == "boom"


def test_shutdown_signal_requests_graceful_stop(monkeypatch):
    handlers = {}
    stopping = threading.Event()
    monkeypatch.setattr(signal, "signal", lambda signum, handler: handlers.update({signum: handler}))

    install_shutdown_handlers(stopping)
    handlers[signal.SIGTERM](signal.SIGTERM, None)

    assert stopping.is_set()


def test_worker_heartbeat_can_be_removed_after_shutdown():
    store = JobStore("sqlite://")
    store.heartbeat_worker("worker-to-stop", "job-1")

    store.remove_worker_heartbeat("worker-to-stop")

    assert store.list_worker_heartbeats() == []
