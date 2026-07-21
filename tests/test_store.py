from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

from document_core.models import DocumentJob, JobStatus
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
