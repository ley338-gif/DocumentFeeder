from __future__ import annotations

import os
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Protocol
from uuid import uuid4

from sqlalchemy import JSON, BigInteger, DateTime, Integer, String, Text, and_, create_engine, delete, func, inspect, or_, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker
from sqlalchemy.pool import StaticPool

from .models import (
    DeliveryRule, DocumentJob, InputChannel, JobEvent, JobStatus, TargetSystem,
    AuditEvent, UserAccount,
)
from .secrets import SecretCipher


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
    healthcheck_url: Mapped[str | None] = mapped_column(Text)
    directory: Mapped[str] = mapped_column(String(300), nullable=False)
    path_template: Mapped[str] = mapped_column(Text, nullable=False)
    bearer_token: Mapped[str | None] = mapped_column(Text)
    graph_tenant_id: Mapped[str | None] = mapped_column(String(200))
    graph_client_id: Mapped[str | None] = mapped_column(String(200))
    graph_client_secret: Mapped[str | None] = mapped_column(Text)
    graph_drive_id: Mapped[str | None] = mapped_column(String(300))
    graph_folder: Mapped[str] = mapped_column(Text, nullable=False, default="DocumentCore")
    timeout_seconds: Mapped[int] = mapped_column(Integer, nullable=False)
    max_response_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=65536)
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


class UserRow(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    username: Mapped[str] = mapped_column(String(100), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    active: Mapped[bool] = mapped_column(nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class SessionRow(Base):
    __tablename__ = "user_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AuditEventRow(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    actor_user_id: Mapped[str | None] = mapped_column(String(36), index=True)
    actor_username: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    resource_id: Mapped[str | None] = mapped_column(String(100))
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)
    details: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    chain_index: Mapped[int | None] = mapped_column(BigInteger, unique=True, index=True)
    previous_hash: Mapped[str | None] = mapped_column(String(64))
    entry_hash: Mapped[str | None] = mapped_column(String(64), unique=True)


class WorkerHeartbeatRow(Base):
    __tablename__ = "worker_heartbeats"
    worker_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    current_job_id: Mapped[str | None] = mapped_column(String(36))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class SystemSettingRow(Base):
    __tablename__ = "system_settings"
    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobStore:
    """SQL-backed job repository used with PostgreSQL and SQLite."""

    def __init__(
        self,
        database_url: str,
        create_schema: bool = True,
        secret_cipher: SecretCipher | None = None,
    ):
        engine_options: dict = {"pool_pre_ping": True}
        if database_url in {"sqlite://", "sqlite:///:memory:"}:
            engine_options.update(
                connect_args={"check_same_thread": False}, poolclass=StaticPool
            )
        self.engine = create_engine(database_url, **engine_options)
        self.sessions = sessionmaker(self.engine, expire_on_commit=False)
        self.secret_cipher = secret_cipher or SecretCipher.from_csv(
            os.getenv("DOCUMENT_CORE_CONNECTOR_SECRET_KEYS", "")
        )
        if create_schema:
            Base.metadata.create_all(self.engine)
            self.migrate_or_rotate_target_secrets()
            self.initialize_audit_chain()

    def migrate_or_rotate_target_secrets(self) -> None:
        if "target_systems" not in inspect(self.engine).get_table_names():
            return
        with self.sessions.begin() as session:
            rows = session.scalars(select(TargetSystemRow)).all()
            for row in rows:
                if row.bearer_token:
                    row.bearer_token = self.secret_cipher.migrate_or_rotate(row.bearer_token)
                if row.graph_client_secret:
                    row.graph_client_secret = self.secret_cipher.migrate_or_rotate(
                        row.graph_client_secret
                    )
                row.last_error = self.redact(row.last_error)
            for row in session.scalars(select(JobRow)).all():
                row.last_error = self.redact(row.last_error)
                row.errors = self.redact(row.errors)
            for row in session.scalars(select(JobEventRow)).all():
                row.error = self.redact(row.error)
                row.details = self.redact(row.details)
            for row in session.scalars(select(AuditEventRow)).all():
                row.details = self.redact(row.details)

    def redact(self, value):
        return self.secret_cipher.redact(value)

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

    @staticmethod
    def _user_model(row: UserRow) -> UserAccount:
        return UserAccount.model_validate({key: getattr(row, key) for key in (
            "id", "username", "display_name", "role", "active", "password_hash",
            "last_login_at", "created_at", "updated_at",
        )})

    def list_users(self) -> list[UserAccount]:
        with self.sessions() as session:
            rows = session.scalars(select(UserRow).order_by(UserRow.username)).all()
            return [self._user_model(row) for row in rows]

    def get_user(self, user_id: str) -> UserAccount | None:
        with self.sessions() as session:
            row = session.get(UserRow, user_id)
            return self._user_model(row) if row else None

    def get_user_by_username(self, username: str) -> UserAccount | None:
        with self.sessions() as session:
            row = session.scalar(select(UserRow).where(UserRow.username == username.lower()))
            return self._user_model(row) if row else None

    def save_user(self, user: UserAccount) -> UserAccount:
        user.username = user.username.lower()
        user.updated_at = datetime.now(UTC)
        values = user.model_dump()
        values["password_hash"] = user.password_hash
        with self.sessions.begin() as session:
            row = session.get(UserRow, user.id)
            if row is None:
                session.add(UserRow(**values))
            else:
                for key, value in values.items():
                    setattr(row, key, value)
        return user

    def create_session(self, token_hash: str, user_id: str, expires_at: datetime) -> None:
        with self.sessions.begin() as session:
            session.add(SessionRow(token_hash=token_hash, user_id=user_id, expires_at=expires_at))

    def get_session_user(self, token_hash: str) -> UserAccount | None:
        now = datetime.now(UTC)
        with self.sessions() as session:
            row = session.get(SessionRow, token_hash)
            if row is None or row.expires_at.replace(tzinfo=UTC) <= now:
                return None
            user = session.get(UserRow, row.user_id)
            return self._user_model(user) if user and user.active else None

    def delete_session(self, token_hash: str) -> None:
        with self.sessions.begin() as session:
            session.execute(delete(SessionRow).where(SessionRow.token_hash == token_hash))

    def delete_user_sessions(self, user_id: str) -> None:
        with self.sessions.begin() as session:
            session.execute(delete(SessionRow).where(SessionRow.user_id == user_id))

    def recent_failed_logins(self, username: str, since: datetime) -> int:
        with self.sessions() as session:
            rows = session.scalars(
                select(AuditEventRow)
                .where(
                    AuditEventRow.action == "LOGIN",
                    AuditEventRow.actor_username == username.lower(),
                    AuditEventRow.created_at >= since,
                )
                .order_by(AuditEventRow.created_at.desc())
            ).all()
            failures = 0
            for row in rows:
                if row.outcome == "success":
                    break
                failures += 1
            return failures

    @staticmethod
    def _audit_hash(previous_hash: str, values: dict) -> str:
        created_at = values["created_at"]
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)
        canonical = {
            "id": values["id"],
            "actor_user_id": values.get("actor_user_id"),
            "actor_username": values["actor_username"],
            "action": values["action"],
            "resource_type": values["resource_type"],
            "resource_id": values.get("resource_id"),
            "outcome": values["outcome"],
            "status_code": values["status_code"],
            "details": values["details"],
            "created_at": created_at.astimezone(UTC).isoformat(timespec="microseconds"),
        }
        payload = json.dumps(
            canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        return hashlib.sha256(f"{previous_hash}\n{payload}".encode()).hexdigest()

    @staticmethod
    def _audit_row_values(row: AuditEventRow) -> dict:
        return {
            key: getattr(row, key) for key in (
                "id", "actor_user_id", "actor_username", "action", "resource_type",
                "resource_id", "outcome", "status_code", "details", "created_at",
            )
        }

    @staticmethod
    def _session_setting(session, key: str, default: str = "") -> str:
        row = session.get(SystemSettingRow, key)
        return row.value if row else default

    @staticmethod
    def _set_session_setting(session, key: str, value: str) -> None:
        row = session.get(SystemSettingRow, key)
        if row is None:
            session.add(
                SystemSettingRow(key=key, value=value, updated_at=datetime.now(UTC))
            )
        else:
            row.value = value
            row.updated_at = datetime.now(UTC)

    def _lock_audit_chain(self, session) -> None:
        if self.engine.dialect.name == "postgresql":
            session.execute(text("SELECT pg_advisory_xact_lock(823746123)"))

    def initialize_audit_chain(self) -> None:
        if "audit_events" not in inspect(self.engine).get_table_names():
            return
        columns = {item["name"] for item in inspect(self.engine).get_columns("audit_events")}
        if "entry_hash" not in columns:
            return
        with self.sessions.begin() as session:
            self._lock_audit_chain(session)
            rows = session.scalars(
                select(AuditEventRow).order_by(
                    AuditEventRow.created_at, AuditEventRow.id
                )
            ).all()
            if not rows or any(row.entry_hash for row in rows):
                return
            previous_hash = self._session_setting(
                session, "audit_chain_anchor_hash", "0" * 64
            )
            chain_index = int(self._session_setting(
                session, "audit_chain_anchor_index", "0"
            ))
            for row in rows:
                chain_index += 1
                row.chain_index = chain_index
                row.previous_hash = previous_hash
                row.entry_hash = self._audit_hash(
                    previous_hash, self._audit_row_values(row)
                )
                previous_hash = row.entry_hash

    def save_audit_event(self, event: AuditEvent) -> AuditEvent:
        event.details = self.redact(event.details)
        with self.sessions.begin() as session:
            self._lock_audit_chain(session)
            last = session.scalar(
                select(AuditEventRow)
                .where(AuditEventRow.chain_index.is_not(None))
                .order_by(AuditEventRow.chain_index.desc())
                .limit(1)
                .with_for_update()
            )
            if last:
                previous_hash = last.entry_hash or "0" * 64
                chain_index = (last.chain_index or 0) + 1
            else:
                previous_hash = self._session_setting(
                    session, "audit_chain_anchor_hash", "0" * 64
                )
                chain_index = int(self._session_setting(
                    session, "audit_chain_anchor_index", "0"
                )) + 1
            values = event.model_dump()
            entry_hash = self._audit_hash(previous_hash, values)
            session.add(AuditEventRow(
                **values,
                chain_index=chain_index,
                previous_hash=previous_hash,
                entry_hash=entry_hash,
            ))
        return event

    def verify_audit_chain(self) -> dict:
        with self.sessions() as session:
            previous_hash = self._session_setting(
                session, "audit_chain_anchor_hash", "0" * 64
            )
            expected_index = int(self._session_setting(
                session, "audit_chain_anchor_index", "0"
            )) + 1
            checked = 0
            rows = session.scalars(
                select(AuditEventRow).order_by(AuditEventRow.chain_index)
            )
            for row in rows:
                expected_hash = self._audit_hash(
                    previous_hash, self._audit_row_values(row)
                )
                if (
                    row.chain_index != expected_index
                    or row.previous_hash != previous_hash
                    or row.entry_hash != expected_hash
                ):
                    return {
                        "status": "invalid",
                        "checked": checked,
                        "first_invalid_index": row.chain_index,
                        "detail": "Audit-Hashkette ist unterbrochen oder verändert",
                    }
                checked += 1
                expected_index += 1
                previous_hash = row.entry_hash or ""
            return {
                "status": "ok",
                "checked": checked,
                "first_invalid_index": None,
                "detail": None,
            }

    def list_audit_events(self) -> list[AuditEvent]:
        items, _ = self.search_audit_events(limit=10000)
        return items

    @staticmethod
    def _audit_filters(q: str | None = None, outcome: str | None = None) -> list:
        filters = []
        if outcome:
            filters.append(AuditEventRow.outcome == outcome)
        if q:
            pattern = f"%{q.strip()}%"
            filters.append(or_(
                AuditEventRow.actor_username.ilike(pattern),
                AuditEventRow.action.ilike(pattern),
                AuditEventRow.resource_type.ilike(pattern),
                AuditEventRow.resource_id.ilike(pattern),
            ))
        return filters

    @staticmethod
    def _audit_model(row: AuditEventRow) -> AuditEvent:
        return AuditEvent.model_validate({
            key: getattr(row, key) for key in (
                "id", "actor_user_id", "actor_username", "action", "resource_type",
                "resource_id", "outcome", "status_code", "details", "created_at",
            )
        })

    def search_audit_events(
        self,
        q: str | None = None,
        outcome: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[AuditEvent], int]:
        filters = self._audit_filters(q, outcome)
        with self.sessions() as session:
            rows = session.scalars(
                select(AuditEventRow)
                .where(*filters)
                .order_by(AuditEventRow.created_at.desc())
                .limit(limit)
                .offset(offset)
            ).all()
            total = session.scalar(
                select(func.count()).select_from(AuditEventRow).where(*filters)
            ) or 0
            return [self._audit_model(row) for row in rows], total

    def iter_audit_events(
        self, q: str | None = None, outcome: str | None = None
    ):
        filters = self._audit_filters(q, outcome)
        with self.sessions() as session:
            rows = session.scalars(
                select(AuditEventRow)
                .where(*filters)
                .order_by(AuditEventRow.created_at.desc())
                .execution_options(yield_per=500)
            )
            for row in rows:
                yield self._audit_model(row)

    def delete_audit_events_before(self, cutoff: datetime) -> int:
        with self.sessions.begin() as session:
            self._lock_audit_chain(session)
            first_retained = session.scalar(
                select(AuditEventRow)
                .where(AuditEventRow.created_at >= cutoff)
                .order_by(AuditEventRow.chain_index)
                .limit(1)
            )
            boundary = (first_retained.chain_index - 1) if first_retained else session.scalar(
                select(func.max(AuditEventRow.chain_index))
            )
            if not boundary:
                return 0
            anchor = session.scalar(
                select(AuditEventRow).where(AuditEventRow.chain_index == boundary)
            )
            if anchor is None:
                return 0
            self._set_session_setting(
                session, "audit_chain_anchor_hash", anchor.entry_hash or "0" * 64
            )
            self._set_session_setting(
                session, "audit_chain_anchor_index", str(anchor.chain_index or 0)
            )
            result = session.execute(
                delete(AuditEventRow).where(AuditEventRow.chain_index <= boundary)
            )
            return result.rowcount or 0

    def heartbeat_worker(self, worker_id: str, current_job_id: str | None = None) -> None:
        now = datetime.now(UTC)
        with self.sessions.begin() as session:
            row = session.get(WorkerHeartbeatRow, worker_id)
            if row is None:
                session.add(WorkerHeartbeatRow(
                    worker_id=worker_id, current_job_id=current_job_id,
                    started_at=now, last_seen_at=now,
                ))
            else:
                row.current_job_id = current_job_id
                row.last_seen_at = now

    def remove_worker_heartbeat(self, worker_id: str) -> None:
        with self.sessions.begin() as session:
            session.execute(
                delete(WorkerHeartbeatRow).where(WorkerHeartbeatRow.worker_id == worker_id)
            )

    def list_worker_heartbeats(self) -> list[dict]:
        with self.sessions() as session:
            rows = session.scalars(
                select(WorkerHeartbeatRow).order_by(WorkerHeartbeatRow.last_seen_at.desc())
            ).all()
            return [{
                "worker_id": row.worker_id,
                "current_job_id": row.current_job_id,
                "started_at": row.started_at,
                "last_seen_at": row.last_seen_at,
            } for row in rows]

    def get_system_setting(self, key: str, default: str | None = None) -> str | None:
        with self.sessions() as session:
            row = session.get(SystemSettingRow, key)
            return row.value if row else default

    def set_system_setting(self, key: str, value: str) -> None:
        with self.sessions.begin() as session:
            row = session.get(SystemSettingRow, key)
            if row is None:
                session.add(SystemSettingRow(key=key, value=value, updated_at=datetime.now(UTC)))
            else:
                row.value = value
                row.updated_at = datetime.now(UTC)

    def ensure_installation_id(self) -> str:
        installation_id = self.get_system_setting("installation_id")
        if installation_id:
            return installation_id
        installation_id = str(uuid4())
        self.set_system_setting("installation_id", installation_id)
        return installation_id

    def schema_version(self) -> str:
        try:
            with self.engine.connect() as connection:
                return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())
        except Exception:
            return "unbekannt"

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
    def _target_values(row: TargetSystemRow) -> dict:
        return {column.name: getattr(row, column.name) for column in row.__table__.columns}

    def _target_model(self, row: TargetSystemRow) -> TargetSystem:
        values = self._target_values(row)
        values["bearer_token"] = self.secret_cipher.decrypt(values["bearer_token"])
        values["graph_client_secret"] = self.secret_cipher.decrypt(
            values["graph_client_secret"]
        )
        return TargetSystem.model_validate(values)

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
        values["bearer_token"] = self.secret_cipher.encrypt(target.bearer_token)
        values["graph_client_secret"] = self.secret_cipher.encrypt(target.graph_client_secret)
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
