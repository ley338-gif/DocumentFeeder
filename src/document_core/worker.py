import logging
import signal
import socket
import threading
from contextlib import contextmanager
from types import FrameType
from uuid import uuid4

from .config import Settings
from .connectors import FilesystemConnector
from .pipeline import DocumentPipeline
from .store import JobStore
from .secrets import SecretCipher


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@contextmanager
def lease_heartbeat(store: JobStore, job_id: str, worker_id: str, lease_seconds: int):
    stopped = threading.Event()

    def renew() -> None:
        interval = max(1.0, lease_seconds / 3)
        while not stopped.wait(interval):
            store.heartbeat_worker(worker_id, job_id)
            if not store.renew_lease(job_id, worker_id, lease_seconds):
                logger.warning("Lease for job %s could not be renewed", job_id)
                return

    heartbeat = threading.Thread(target=renew, daemon=True)
    heartbeat.start()
    try:
        yield
    finally:
        stopped.set()
        heartbeat.join(timeout=1)


def install_shutdown_handlers(stop_event: threading.Event) -> None:
    def request_shutdown(signum: int, _frame: FrameType | None) -> None:
        logger.info("Shutdown signal %s received; finishing the current job", signum)
        stop_event.set()

    signal.signal(signal.SIGTERM, request_shutdown)
    signal.signal(signal.SIGINT, request_shutdown)


def run(stop_event: threading.Event | None = None, *, handle_signals: bool = True) -> None:
    stopping = stop_event or threading.Event()
    if handle_signals:
        install_shutdown_handlers(stopping)
    settings = Settings()
    settings.create_directories()
    store = JobStore(
        settings.database_url,
        create_schema=settings.database_auto_create,
        secret_cipher=SecretCipher.from_csv(settings.connector_secret_key_material),
    )
    store.migrate_or_rotate_target_secrets()
    store.ensure_installation_id()
    pipeline = DocumentPipeline(settings, store, FilesystemConnector(settings.output_dir))
    worker_id = f"{socket.gethostname()}-{uuid4().hex[:8]}"
    logger.info("Worker %s started", worker_id)

    try:
        store.heartbeat_worker(worker_id)
        while not stopping.is_set():
            job = store.claim_next(worker_id, settings.worker_lease_seconds)
            if job is None:
                stopping.wait(settings.worker_poll_interval)
                if not stopping.is_set():
                    store.heartbeat_worker(worker_id)
                continue
            logger.info("Processing job %s, attempt %s", job.id, job.attempt_count)
            store.heartbeat_worker(worker_id, job.id)
            with lease_heartbeat(store, job.id, worker_id, settings.worker_lease_seconds):
                result = pipeline.process(job)
            logger.info("Job %s finished with status %s", result.id, result.status)
            store.heartbeat_worker(worker_id)
    finally:
        store.remove_worker_heartbeat(worker_id)
        logger.info("Worker %s stopped cleanly", worker_id)


if __name__ == "__main__":
    run()
