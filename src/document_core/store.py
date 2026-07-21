from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy import JSON, DateTime, String, Text, create_engine, select, update
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

    def healthcheck(self) -> bool:
        try:
            with self.sessions() as session:
                session.execute(select(1))
            return True
        except Exception:
            return False
