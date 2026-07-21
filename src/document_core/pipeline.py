import hashlib
import shutil
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import Settings
from .connectors import FilesystemConnector, HttpConnector, TargetConnector
from .models import DocumentJob, JobEvent, JobStatus, ReviewEvent, ReviewRequest
from .processing import RuleBasedProcessor, TextExtractor, WorkflowRules
from .store import JobRepository


class DocumentPipeline:
    def __init__(self, settings: Settings, store: JobRepository, connector: TargetConnector):
        self.settings = settings
        self.store = store
        self.connector = connector
        self.extractor = TextExtractor(settings.tesseract_lang)
        self.processor = RuleBasedProcessor()
        self.rules = WorkflowRules(settings.require_routing_reference)

    def ingest(self, source_path: Path, source: str, original_filename: str | None = None) -> DocumentJob:
        content_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        filename = Path(original_filename or source_path.name).name
        job = DocumentJob(
            source=source,
            original_filename=filename,
            stored_path=self.settings.inbox_dir / f"{content_hash[:12]}-{filename}",
            sha256=content_hash,
            target_system_id=(
                target.id
                if (target := getattr(self.store, "get_default_target_system", lambda: None)())
                else None
            ),
        )
        shutil.copy2(source_path, job.stored_path)
        persisted, created = self.store.create_if_absent(job)
        if created:
            self._event(
                persisted,
                "ingested",
                "Dokument wurde angenommen",
                status=JobStatus.RECEIVED,
                details={"source": source, "filename": filename},
            )
        return persisted

    def process(self, job: DocumentJob) -> DocumentJob:
        if job.status == JobStatus.RECEIVED:
            job.status = JobStatus.PROCESSING
            job.attempt_count = max(job.attempt_count, 1)
            self.store.save(job)
        if job.status == JobStatus.PROCESSING:
            self._event(
                job,
                "processing_started",
                f"Verarbeitung gestartet (Versuch {job.attempt_count})",
                attempt=job.attempt_count,
            )
        try:
            extraction = self.extractor.extract(job.stored_path)
            clean_text = extraction.text.replace("\x00", "")
            job.text_preview = clean_text[:500]
            job.document_type, job.metadata = self.processor.process(clean_text)
            job.metadata.update(extraction.metadata())
            self._apply_delivery_rule(job)
            job.errors = self.rules.validate(job.document_type, job.routing_reference is not None)
            if job.errors:
                job.status = JobStatus.QUARANTINED
                target = self.settings.quarantine_dir / f"{job.id}-{job.original_filename}"
                shutil.copy2(job.stored_path, target)
                self._event(
                    job,
                    "review_required",
                    "Dokument benötigt eine manuelle Prüfung",
                    status=JobStatus.QUARANTINED,
                    attempt=job.attempt_count,
                    details={"reasons": job.errors},
                )
            else:
                job.metadata["destination_reference"] = self._deliver(job)
                job.status = JobStatus.DELIVERED
            job.last_error = None
            job.next_attempt_at = None
        except Exception as exc:
            error = str(exc)
            job.errors.append(error)
            job.last_error = error
            if job.attempt_count < self.settings.worker_max_attempts:
                delay = self.settings.worker_retry_base_seconds * (2 ** (job.attempt_count - 1))
                job.status = JobStatus.RECEIVED
                job.next_attempt_at = datetime.now(UTC) + timedelta(seconds=delay)
                self._event(
                    job,
                    "retry_scheduled",
                    f"Neuer Verarbeitungsversuch in {delay} Sekunden eingeplant",
                    status=JobStatus.RECEIVED,
                    attempt=job.attempt_count,
                    error=error,
                )
            else:
                job.status = JobStatus.FAILED
                job.next_attempt_at = None
                self._event(
                    job,
                    "processing_failed",
                    "Verarbeitung endgültig fehlgeschlagen",
                    status=JobStatus.FAILED,
                    attempt=job.attempt_count,
                    error=error,
                )
        job.worker_id = None
        job.lease_expires_at = None
        self.store.save(job)
        return job

    def review(self, job: DocumentJob, request: ReviewRequest) -> DocumentJob:
        changes: dict[str, object] = {}
        if request.document_type is not None and request.document_type != job.document_type:
            changes["document_type"] = {"from": job.document_type, "to": request.document_type}
            job.document_type = request.document_type
        if request.routing_reference is not None and request.routing_reference != job.routing_reference:
            changes["routing_reference"] = {
                "from": job.routing_reference.model_dump() if job.routing_reference else None,
                "to": request.routing_reference.model_dump(),
            }
            job.routing_reference = request.routing_reference
        if request.metadata:
            changes["metadata"] = request.metadata
            job.metadata.update(request.metadata)
        if request.target_system_id is not None and request.target_system_id != job.target_system_id:
            target = getattr(self.store, "get_target_system", lambda _id: None)(
                request.target_system_id
            )
            if target is None or not target.enabled:
                raise ValueError("Zielsystem ist nicht vorhanden oder deaktiviert")
            changes["target_system_id"] = {
                "from": job.target_system_id,
                "to": request.target_system_id,
            }
            job.target_system_id = request.target_system_id
            job.delivery_path_template = target.path_template
        elif request.document_type is not None:
            self._apply_delivery_rule(job)
        job.review_history.append(
            ReviewEvent(reviewer=request.reviewer, reason=request.reason, changes=changes)
        )
        self.store.save(job)
        self._event(
            job,
            "review_saved",
            f"Manuelle Prüfung durch {request.reviewer} gespeichert",
            details={"reason": request.reason, "changes": changes},
        )
        return job

    def release(self, job: DocumentJob) -> DocumentJob:
        if job.status == JobStatus.DELIVERED:
            return job
        job.errors = self.rules.validate(job.document_type, job.routing_reference is not None)
        if job.errors:
            job.status = JobStatus.QUARANTINED
            self.store.save(job)
            self._event(
                job,
                "release_rejected",
                "Freigabe wegen fehlender Angaben abgelehnt",
                status=JobStatus.QUARANTINED,
                details={"reasons": job.errors},
            )
            return job
        if not self.store.claim_delivery(job.id):
            return self.store.get(job.id) or job
        job.status = JobStatus.DELIVERING
        try:
            job.metadata["destination_reference"] = self._deliver(job)
            job.status = JobStatus.DELIVERED
        except Exception as exc:
            job.errors.append(str(exc))
            job.last_error = str(exc)
            job.status = JobStatus.FAILED
        self.store.save(job)
        return job

    def _connector_for(self, job: DocumentJob) -> TargetConnector:
        if not job.target_system_id:
            return self.connector
        target = getattr(self.store, "get_target_system", lambda _id: None)(job.target_system_id)
        if target is None or not target.enabled:
            raise RuntimeError("Konfiguriertes Zielsystem ist nicht vorhanden oder deaktiviert")
        if target.kind == "filesystem":
            return FilesystemConnector(
                self.settings.data_dir / target.directory,
                target.path_template,
            )
        if target.kind == "http":
            return HttpConnector(target)
        raise RuntimeError(f"Nicht unterstützter Connector-Typ: {target.kind}")

    def _deliver(self, job: DocumentJob) -> str:
        target = (
            getattr(self.store, "get_target_system", lambda _id: None)(job.target_system_id)
            if job.target_system_id
            else None
        )
        started_at = datetime.now(UTC)
        target_name = target.name if target is not None else type(self.connector).__name__
        event_details = {"path_template": job.delivery_path_template}
        self._event(
            job,
            "delivery_started",
            f"Zustellung an {target_name} gestartet",
            status=JobStatus.DELIVERING,
            attempt=job.attempt_count,
            target=target,
            details=event_details,
            started_at=started_at,
        )
        try:
            reference = self._connector_for(job).deliver(job)
            completed_at = datetime.now(UTC)
            if target is not None:
                target.last_delivery_at = completed_at
                target.last_error = None
                getattr(self.store, "save_target_system")(target)
            self._event(
                job,
                "delivery_succeeded",
                f"Dokument an {target_name} zugestellt",
                status=JobStatus.DELIVERED,
                attempt=job.attempt_count,
                target=target,
                external_reference=reference,
                details=event_details,
                started_at=started_at,
                completed_at=completed_at,
            )
            return reference
        except Exception as exc:
            completed_at = datetime.now(UTC)
            if target is not None:
                target.last_error = str(exc)
                getattr(self.store, "save_target_system")(target)
            self._event(
                job,
                "delivery_failed",
                f"Zustellung an {target_name} fehlgeschlagen",
                status=JobStatus.FAILED,
                attempt=job.attempt_count,
                target=target,
                error=str(exc),
                details=event_details,
                started_at=started_at,
                completed_at=completed_at,
            )
            raise

    def _event(
        self,
        job: DocumentJob,
        event_type: str,
        message: str,
        *,
        status: JobStatus | None = None,
        attempt: int | None = None,
        target=None,
        external_reference: str | None = None,
        error: str | None = None,
        details: dict | None = None,
        started_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        getattr(self.store, "save_event")(
            JobEvent(
                job_id=job.id,
                event_type=event_type,
                status=(status or job.status).value,
                message=message,
                attempt=attempt,
                target_system_id=target.id if target is not None else job.target_system_id,
                target_name=target.name if target is not None else None,
                delivery_rule=job.metadata.get("delivery_rule"),
                external_reference=external_reference,
                error=error,
                details=details or {},
                started_at=started_at or datetime.now(UTC),
                completed_at=completed_at,
            )
        )

    def _apply_delivery_rule(self, job: DocumentJob) -> None:
        rule = getattr(self.store, "find_delivery_rule", lambda _type: None)(job.document_type)
        if rule is not None:
            target = getattr(self.store, "get_target_system", lambda _id: None)(
                rule.target_system_id
            )
            if target is not None and target.enabled:
                job.target_system_id = target.id
                job.delivery_path_template = rule.path_template or target.path_template
                job.metadata["delivery_rule"] = rule.name
                return
        if job.target_system_id:
            target = getattr(self.store, "get_target_system", lambda _id: None)(
                job.target_system_id
            )
            if target is not None:
                job.delivery_path_template = target.path_template
