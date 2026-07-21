from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import JSON, DateTime, Integer, String, Text, and_, create_engine, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import DocumentJob, JobStatus


class JobRepository(Protocol):
    def save(self, job: DocumentJob) -> None: ...

    def create_if_absent(self, job: DocumentJob) -> tuple[DocumentJob, bool]: ...

    def get(self, job_id: str) -> DocumentJob | None: ...

    def list(self) -> list[DocumentJob]: ...

    def find_by_hash(self, sha256: str) -> DocumentJob | None: ...

    def claim_delivery(self, job_id: str) -> bool: ...

    def claim_next(self, worker_id: str, lease_seconds: int) -> DocumentJob | None: ...

    def renew_lease(self, job_id: str, worker_id: str, lease_seconds: int) -> bool: ...

    def retry_failed(self, job_id: str) -> DocumentJob | None: ...

    def healthcheck(self) -> bool: ...


class Base(DeclarativeBase):
    pass


class JobRow(Base):
    __tablename__ = "document_jobs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False)
    original_filename: Mapped[str] = mapped_column(String(500), nullable=False)
    stored_path: Mapped[str] = mapped_column(Text, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    document_type: Mapped[str] = mapped_column(String(100), nullable=False)
    routing_reference: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    metadata_json: Mapped[dict] = mapped_column("metadata", JSON, nullable=False)
    review_history: Mapped[list] = mapped_column(JSON, nullable=False)
    text_preview: Mapped[str] = mapped_column(Text, nullable=False)
    errors: Mapped[list] = mapped_column(JSON, nullable=False)
    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    worker_id: Mapped[str | None] = mapped_column(String(200))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobStore:
    """SQL-backed job repository used with PostgreSQL and SQLite."""

    def __init__(self, database_url: str, create_schema: bool = True):
        engine_options: dict = {"pool_pre_ping": True}
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            engine_options.update(
                connect_args={"check_same_thread": False}, poolclass=StaticPool
            )
        self.engine = create_engine(database_url, **engine_options)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        if create_schema:
            Base.metadata.create_all(self.engine)

    @staticmethod
    def _values(job: DocumentJob) -> dict:
        return {
            "id": job.id,
            "status": job.status.value,
            "source": job.source,
            "original_filename": job.original_filename,
            "stored_path": str(job.stored_path),
            "sha256": job.sha256,
            "document_type": job.document_type,
            "routing_reference": (
                job.routing_reference.model_dump(mode="json") if job.routing_reference else None
            ),
            "metadata_json": job.metadata,
            "review_history": [event.model_dump(mode="json") for event in job.review_history],
            "text_preview": job.text_preview,
            "errors": job.errors,
            "attempt_count": job.attempt_count,
            "next_attempt_at": job.next_attempt_at,
            "lease_expires_at": job.lease_expires_at,
            "worker_id": job.worker_id,
            "last_error": job.last_error,
            "created_at": job.created_at,
            "updated_at": job.updated_at,
        }

    @staticmethod
    def _model(row: JobRow) -> DocumentJob:
        return DocumentJob.model_validate(
            {
                "id": row.id,
                "status": row.status,
                "source": row.source,
                "original_filename": row.original_filename,
                "stored_path": row.stored_path,
                "sha256": row.sha256,
                "document_type": row.document_type,
                "routing_reference": row.routing_reference,
                "metadata": row.metadata_json,
                "review_history": row.review_history,
                "text_preview": row.text_preview,
                "errors": row.errors,
                "attempt_count": row.attempt_count,
                "next_attempt_at": row.next_attempt_at,
                "lease_expires_at": row.lease_expires_at,
                "worker_id": row.worker_id,
                "last_error": row.last_error,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )

    def save(self, job: DocumentJob) -> None:
        job.updated_at = datetime.now(UTC)
        values = self._values(job)
        with self.sessions.begin() as session:
            row = session.get(JobRow, job.id)
            if row is None:
                session.add(JobRow(**values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)

    def create_if_absent(self, job: DocumentJob) -> tuple[DocumentJob, bool]:
        with self.sessions() as session:
            try:
                session.add(JobRow(**self._values(job)))
                session.commit()
                return job, True
            except IntegrityError:
                session.rollback()
                existing = session.scalar(select(JobRow).where(JobRow.sha256 == job.sha256))
                if existing is None:
                    raise
                return self._model(existing), False

    def get(self, job_id: str) -> DocumentJob | None:
        with self.sessions() as session:
            row = session.get(JobRow, job_id)
            return self._model(row) if row else None

    def list(self) -> list[DocumentJob]:
        with self.sessions() as session:
            rows = session.scalars(select(JobRow).order_by(JobRow.created_at.desc())).all()
            return [self._model(row) for row in rows]

    def find_by_hash(self, sha256: str) -> DocumentJob | None:
        with self.sessions() as session:
            row = session.scalar(select(JobRow).where(JobRow.sha256 == sha256))
            return self._model(row) if row else None

    def claim_delivery(self, job_id: str) -> bool:
        with self.sessions.begin() as session:
            result = session.execute(
                update(JobRow)
                .where(JobRow.id == job_id, JobRow.status == JobStatus.QUARANTINED.value)
                .values(status=JobStatus.DELIVERING.value, updated_at=datetime.now(UTC))
            )
            return result.rowcount == 1

    def claim_next(self, worker_id: str, lease_seconds: int) -> DocumentJob | None:
        now = datetime.now(UTC)
        due = or_(
            and_(
                JobRow.status == JobStatus.RECEIVED.value,
                or_(JobRow.next_attempt_at.is_(None), JobRow.next_attempt_at <= now),
            ),
            and_(
                JobRow.status == JobStatus.PROCESSING.value,
                JobRow.lease_expires_at.is_not(None),
                JobRow.lease_expires_at <= now,
            ),
        )
        with self.sessions.begin() as session:
            row = session.scalar(
                select(JobRow)
                .where(due)
                .order_by(JobRow.created_at)
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if row is None:
                return None
            row.status = JobStatus.PROCESSING.value
            row.worker_id = worker_id
            row.lease_expires_at = now + timedelta(seconds=lease_seconds)
            row.next_attempt_at = None
            row.attempt_count += 1
            row.updated_at = now
            session.flush()
            return self._model(row)

    def renew_lease(self, job_id: str, worker_id: str, lease_seconds: int) -> bool:
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            result = session.execute(
                update(JobRow)
                .where(
                    JobRow.id == job_id,
                    JobRow.status == JobStatus.PROCESSING.value,
                    JobRow.worker_id == worker_id,
                )
                .values(
                    lease_expires_at=now + timedelta(seconds=lease_seconds), updated_at=now
                )
            )
            return result.rowcount == 1

    def retry_failed(self, job_id: str) -> DocumentJob | None:
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            result = session.execute(
                update(JobRow)
                .where(JobRow.id == job_id, JobRow.status == JobStatus.FAILED.value)
                .values(
                    status=JobStatus.RECEIVED.value,
                    attempt_count=0,
                    next_attempt_at=None,
                    lease_expires_at=None,
                    worker_id=None,
                    last_error=None,
                    updated_at=now,
                )
            )
            if result.rowcount != 1:
                return None
        return self.get(job_id)

    def healthcheck(self) -> bool:
        try:
            with self.sessions() as session:
                session.execute(select(1))
            return True
        except Exception:
            return False
