import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import delete

from document_core.models import DocumentJob, JobStatus
from document_core.store import JobRow, JobStore


POSTGRES_URL = os.getenv("DOCUMENT_CORE_TEST_POSTGRES_URL")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not POSTGRES_URL, reason="PostgreSQL test URL not configured"),
]


def test_postgres_repository_contract():
    store = JobStore(POSTGRES_URL, create_schema=False)
    unique = uuid4().hex
    job = DocumentJob(
        id=str(uuid4()),
        status=JobStatus.QUARANTINED,
        source="postgres-contract-test",
        original_filename="synthetic.txt",
        stored_path=Path("synthetic.txt"),
        sha256=unique.ljust(64, "0"),
        created_at=datetime.now(UTC),
    )
    duplicate = job.model_copy(update={"id": str(uuid4())})
    try:
        persisted, created = store.create_if_absent(job)
        deduplicated, duplicate_created = store.create_if_absent(duplicate)

        assert created is True
        assert duplicate_created is False
        assert deduplicated.id == persisted.id
        assert store.claim_delivery(job.id) is True
        assert store.claim_delivery(job.id) is False
        assert store.get(job.id).status == JobStatus.DELIVERING
    finally:
        with store.engine.begin() as connection:
            connection.execute(delete(JobRow).where(JobRow.id.in_([job.id, duplicate.id])))
