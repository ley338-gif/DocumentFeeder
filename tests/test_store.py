from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from document_core.models import DocumentJob, InputChannel, JobStatus
from document_core.store import JobStore


def make_job(job_id: str, sha256: str) -> DocumentJob:
    return DocumentJob(
        id=job_id,
        source="test",
        original_filename="document.txt",
        stored_path=Path("document.txt"),
        sha256=sha256,
        created_at=datetime.now(UTC),
    )


def test_create_if_absent_deduplicates_by_hash():
    store = JobStore("sqlite://")
    first, first_created = store.create_if_absent(make_job("job-1", "a" * 64))
    second, second_created = store.create_if_absent(make_job("job-2", "a" * 64))

    assert first_created is True
    assert second_created is False
    assert second.id == first.id
    assert len(store.list()) == 1


def test_only_one_parallel_delivery_claim_succeeds():
    store = JobStore("sqlite://")
    job = make_job("job-1", "b" * 64)
    job.status = JobStatus.QUARANTINED
    store.create_if_absent(job)

    with ThreadPoolExecutor(max_workers=2) as executor:
        claims = list(executor.map(lambda _: store.claim_delivery(job.id), range(2)))

    assert sorted(claims) == [False, True]
    assert store.get(job.id).status == JobStatus.DELIVERING


def test_job_round_trip_preserves_structured_fields():
    store = JobStore("sqlite://")
    job = make_job("job-1", "c" * 64)
    job.metadata = {"nested": {"value": 42}}
    store.create_if_absent(job)

    loaded = store.get(job.id)

    assert loaded is not None
    assert loaded.metadata == job.metadata
    assert loaded.stored_path == job.stored_path


def test_claim_next_recovers_expired_processing_lease():
    store = JobStore("sqlite://")
    job = make_job("job-1", "d" * 64)
    store.create_if_absent(job)

    first = store.claim_next("worker-1", -1)
    recovered = store.claim_next("worker-2", 60)

    assert first.worker_id == "worker-1"
    assert recovered.id == job.id
    assert recovered.worker_id == "worker-2"
    assert recovered.attempt_count == 2


def test_claim_next_returns_each_received_job_once():
    store = JobStore("sqlite://")
    store.create_if_absent(make_job("job-1", "e" * 64))

    claimed = store.claim_next("worker-1", 60)

    assert claimed.status == JobStatus.PROCESSING
    assert claimed.attempt_count == 1
    assert store.claim_next("worker-2", 60) is None


def test_only_failed_job_can_be_requeued():
    store = JobStore("sqlite://")
    job = make_job("job-1", "f" * 64)
    job.status = JobStatus.FAILED
    job.attempt_count = 3
    job.last_error = "synthetic failure"
    store.create_if_absent(job)

    retried = store.retry_failed(job.id)

    assert retried.status == JobStatus.RECEIVED
    assert retried.attempt_count == 0
    assert retried.last_error is None
    assert store.retry_failed(job.id) is None


def test_input_channel_round_trip_and_enabled_filter():
    store = JobStore("sqlite://")
    active = InputChannel(name="Scanner", directory="scanner", patterns=["*.pdf"])
    paused = InputChannel(name="Import", directory="import", enabled=False)

    store.save_channel(active)
    store.save_channel(paused)

    loaded = store.get_channel(active.id)
    assert loaded is not None
    assert loaded.name == active.name
    assert loaded.directory == active.directory
    assert loaded.patterns == active.patterns
    assert [channel.id for channel in store.list_channels(enabled_only=True)] == [active.id]
    assert store.delete_channel(paused.id) is True
    assert store.get_channel(paused.id) is None


def test_failed_and_processing_jobs_can_be_deleted_without_resurrection():
    store = JobStore("sqlite://")
    failed = make_job("failed", "1" * 64)
    failed.status = JobStatus.FAILED
    store.create_if_absent(failed)
    active = make_job("active", "2" * 64)
    store.create_if_absent(active)
    store.claim_next("worker", 60)

    assert store.delete_stalled_job(failed.id).id == failed.id
    active_row = store.get(active.id)
    assert store.delete_stalled_job(active.id).id == active.id
    store.save(active_row)
    assert store.get(active.id) is None
