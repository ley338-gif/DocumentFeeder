from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol

from sqlalchemy import JSON, DateTime, Integer, String, Text, and_, create_engine, delete, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import DeliveryRule, DocumentJob, InputChannel, JobEvent, JobStatus, TargetSystem


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

    def delete_stalled_job(self, job_id: str) -> DocumentJob | None: ...

    def save_event(self, event: JobEvent) -> JobEvent: ...

    def list_events(self, job_id: str) -> list[JobEvent]: ...

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
    target_system_id: Mapped[str | None] = mapped_column(String(36), nullable=True, index=True)
    delivery_path_template: Mapped[str | None] = mapped_column(Text)
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


class InputChannelRow(Base):
    __tablename__ = "input_channels"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    directory: Mapped[str] = mapped_column(String(300), nullable=False, unique=True)
    patterns: Mapped[list] = mapped_column(JSON, nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False)
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class TargetSystemRow(Base):
    __tablename__ = "target_systems"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    endpoint_url: Mapped[str | None] = mapped_column(Text)
    directory: Mapped[str] = mapped_column(String(300), nullable=False)
    path_template: Mapped[str] = mapped_column(Text, nullable=False)
    bearer_token: Mapped[str | None] = mapped_column(Text)
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    enabled: Mapped[bool] = mapped_column(nullable=False)
    is_default: Mapped[bool] = mapped_column(nullable=False, index=True)
    last_delivery_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class DeliveryRuleRow(Base):
    __tablename__ = "delivery_rules"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    document_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    target_system_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    path_template: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobEventRow(Base):
    __tablename__ = "job_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    job_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    attempt: Mapped[int | None] = mapped_column(Integer)
    target_system_id: Mapped[str | None] = mapped_column(String(36), index=True)
    target_name: Mapped[str | None] = mapped_column(String(100))
    delivery_rule: Mapped[str | None] = mapped_column(String(100))
    external_reference: Mapped[str | None] = mapped_column(Text)
    error: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict] = mapped_column(JSON, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
            "target_system_id": job.target_system_id,
            "delivery_path_template": job.delivery_path_template,
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
                "target_system_id": row.target_system_id,
                "delivery_path_template": row.delivery_path_template,
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
                return
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

    def delete_stalled_job(self, job_id: str) -> DocumentJob | None:
        with self.sessions.begin() as session:
            row = session.scalar(
                select(JobRow).where(JobRow.id == job_id).with_for_update()
            )
            if row is None:
                return None
            deletable_statuses = {
                JobStatus.FAILED.value,
                JobStatus.PROCESSING.value,
                JobStatus.QUARANTINED.value,
            }
            if row.status not in deletable_statuses:
                return None
            job = self._model(row)
            session.execute(delete(JobEventRow).where(JobEventRow.job_id == job_id))
            session.delete(row)
            return job

    @staticmethod
    def _event_model(row: JobEventRow) -> JobEvent:
        return JobEvent.model_validate(
            {
                "id": row.id,
                "job_id": row.job_id,
                "event_type": row.event_type,
                "status": row.status,
                "message": row.message,
                "attempt": row.attempt,
                "target_system_id": row.target_system_id,
                "target_name": row.target_name,
                "delivery_rule": row.delivery_rule,
                "external_reference": row.external_reference,
                "error": row.error,
                "details": row.details,
                "started_at": row.started_at,
                "completed_at": row.completed_at,
            }
        )

    def save_event(self, event: JobEvent) -> JobEvent:
        with self.sessions.begin() as session:
            session.add(JobEventRow(**event.model_dump()))
        return event

    def list_events(self, job_id: str) -> list[JobEvent]:
        with self.sessions() as session:
            rows = session.scalars(
                select(JobEventRow)
                .where(JobEventRow.job_id == job_id)
                .order_by(
                    JobEventRow.started_at,
                    JobEventRow.completed_at,
                    JobEventRow.id,
                )
            ).all()
            return [self._event_model(row) for row in rows]

    def healthcheck(self) -> bool:
        try:
            with self.sessions() as session:
                session.execute(select(1))
            return True
        except Exception:
            return False

    @staticmethod
    def _channel_model(row: InputChannelRow) -> InputChannel:
        return InputChannel.model_validate(
            {
                "id": row.id,
                "name": row.name,
                "kind": row.kind,
                "directory": row.directory,
                "patterns": row.patterns,
                "enabled": row.enabled,
                "last_ingested_at": row.last_ingested_at,
                "last_error": row.last_error,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
            }
        )

    def list_channels(self, enabled_only: bool = False) -> list[InputChannel]:
        with self.sessions() as session:
            statement = select(InputChannelRow).order_by(InputChannelRow.name)
            if enabled_only:
                statement = statement.where(InputChannelRow.enabled.is_(True))
            return [self._channel_model(row) for row in session.scalars(statement).all()]

    def get_channel(self, channel_id: str) -> InputChannel | None:
        with self.sessions() as session:
            row = session.get(InputChannelRow, channel_id)
            return self._channel_model(row) if row else None

    def save_channel(self, channel: InputChannel) -> InputChannel:
        channel.updated_at = datetime.now(UTC)
        values = channel.model_dump()
        with self.sessions.begin() as session:
            row = session.get(InputChannelRow, channel.id)
            if row is None:
                session.add(InputChannelRow(**values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        return channel

    def delete_channel(self, channel_id: str) -> bool:
        with self.sessions.begin() as session:
            row = session.get(InputChannelRow, channel_id)
            if row is None:
                return False
            session.delete(row)
            return True

    def ensure_default_channel(self) -> InputChannel:
        with self.sessions() as session:
            row = session.scalar(
                select(InputChannelRow).where(InputChannelRow.directory == "hotfolder")
            )
            if row:
                return self._channel_model(row)
        return self.save_channel(InputChannel(name="Standard-Hotfolder", directory="hotfolder"))

    @staticmethod
    def _target_model(row: TargetSystemRow) -> TargetSystem:
        return TargetSystem.model_validate({column.name: getattr(row, column.name) for column in row.__table__.columns})

    def list_target_systems(self, enabled_only: bool = False) -> list[TargetSystem]:
        with self.sessions() as session:
            statement = select(TargetSystemRow).order_by(TargetSystemRow.name)
            if enabled_only:
                statement = statement.where(TargetSystemRow.enabled.is_(True))
            return [self._target_model(row) for row in session.scalars(statement).all()]

    def get_target_system(self, target_id: str) -> TargetSystem | None:
        with self.sessions() as session:
            row = session.get(TargetSystemRow, target_id)
            return self._target_model(row) if row else None

    def get_default_target_system(self) -> TargetSystem | None:
        with self.sessions() as session:
            row = session.scalar(
                select(TargetSystemRow).where(
                    TargetSystemRow.is_default.is_(True), TargetSystemRow.enabled.is_(True)
                )
            )
            return self._target_model(row) if row else None

    def save_target_system(self, target: TargetSystem) -> TargetSystem:
        target.updated_at = datetime.now(UTC)
        values = target.model_dump()
        with self.sessions.begin() as session:
            if target.is_default:
                session.execute(
                    update(TargetSystemRow)
                    .where(TargetSystemRow.id != target.id)
                    .values(is_default=False, updated_at=target.updated_at)
                )
            row = session.get(TargetSystemRow, target.id)
            if row is None:
                session.add(TargetSystemRow(**values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        return target

    def delete_target_system(self, target_id: str) -> bool:
        with self.sessions.begin() as session:
            row = session.get(TargetSystemRow, target_id)
            if row is None or row.is_default:
                return False
            session.delete(row)
            return True

    def ensure_default_target_system(self) -> TargetSystem:
        existing = self.get_default_target_system()
        if existing:
            return existing
        return self.save_target_system(
            TargetSystem(name="Dateisystem", kind="filesystem", enabled=True, is_default=True)
        )

    @staticmethod
    def _rule_model(row: DeliveryRuleRow) -> DeliveryRule:
        return DeliveryRule.model_validate(
            {column.name: getattr(row, column.name) for column in row.__table__.columns}
        )

    def list_delivery_rules(self) -> list[DeliveryRule]:
        with self.sessions() as session:
            rows = session.scalars(
                select(DeliveryRuleRow).order_by(DeliveryRuleRow.priority, DeliveryRuleRow.name)
            ).all()
            return [self._rule_model(row) for row in rows]

    def get_delivery_rule(self, rule_id: str) -> DeliveryRule | None:
        with self.sessions() as session:
            row = session.get(DeliveryRuleRow, rule_id)
            return self._rule_model(row) if row else None

    def find_delivery_rule(self, document_type: str) -> DeliveryRule | None:
        with self.sessions() as session:
            row = session.scalar(
                select(DeliveryRuleRow)
                .where(
                    DeliveryRuleRow.document_type == document_type,
                    DeliveryRuleRow.enabled.is_(True),
                )
                .order_by(DeliveryRuleRow.priority)
                .limit(1)
            )
            return self._rule_model(row) if row else None

    def save_delivery_rule(self, rule: DeliveryRule) -> DeliveryRule:
        rule.updated_at = datetime.now(UTC)
        values = rule.model_dump()
        with self.sessions.begin() as session:
            row = session.get(DeliveryRuleRow, rule.id)
            if row is None:
                session.add(DeliveryRuleRow(**values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        return rule

    def delete_delivery_rule(self, rule_id: str) -> bool:
        with self.sessions.begin() as session:
            row = session.get(DeliveryRuleRow, rule_id)
            if row is None:
                return False
            session.delete(row)
            return True
