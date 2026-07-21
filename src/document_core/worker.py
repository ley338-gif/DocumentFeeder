import logging
import socket
import threading
import time
from contextlib import contextmanager
from uuid import uuid4

from .config import Settings
from .connectors import FilesystemConnector
from .pipeline import DocumentPipeline
from .store import JobStore


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)


@contextmanager
def lease_heartbeat(store: JobStore, job_id: str, worker_id: str, lease_seconds: int):
    stopped = threading.Event()

    def renew() -> None:
        interval = max(1.0, lease_seconds / 3)
        while not stopped.wait(interval):
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


def run() -> None:
    settings = Settings()
    settings.create_directories()
    store = JobStore(settings.database_url, create_schema=settings.database_auto_create)
    pipeline = DocumentPipeline(settings, store, FilesystemConnector(settings.output_dir))
    worker_id = f"{socket.gethostname()}-{uuid4().hex[:8]}"
    logger.info("Worker %s started", worker_id)

    while True:
        job = store.claim_next(worker_id, settings.worker_lease_seconds)
        if job is None:
            time.sleep(settings.worker_poll_interval)
            continue
        logger.info("Processing job %s, attempt %s", job.id, job.attempt_count)
        with lease_heartbeat(store, job.id, worker_id, settings.worker_lease_seconds):
            result = pipeline.process(job)
        logger.info("Job %s finished with status %s", result.id, result.status)


if __name__ == "__main__":
    run()
