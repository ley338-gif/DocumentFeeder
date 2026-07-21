import hashlib
import shutil
from pathlib import Path

from .config import Settings
from .connectors import TargetConnector
from .models import DocumentJob, JobStatus, ReviewEvent, ReviewRequest
from .processing import RuleBasedProcessor, TextExtractor, WorkflowRules
from .store import JobStore


class DocumentPipeline:
    def __init__(self, settings: Settings, store: JobStore, connector: TargetConnector):
        self.settings = settings
        self.store = store
        self.connector = connector
        self.extractor = TextExtractor(settings.tesseract_lang)
        self.processor = RuleBasedProcessor()
        self.rules = WorkflowRules(settings.require_routing_reference)

    def ingest(self, source_path: Path, source: str, original_filename: str | None = None) -> DocumentJob:
        content_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        if existing := self.store.find_by_hash(content_hash):
            return existing
        filename = Path(original_filename or source_path.name).name
        job = DocumentJob(
            source=source,
            original_filename=filename,
            stored_path=self.settings.inbox_dir / f"{content_hash[:12]}-{filename}",
            sha256=content_hash,
        )
        shutil.copy2(source_path, job.stored_path)
        self.store.save(job)
        return self.process(job)

    def process(self, job: DocumentJob) -> DocumentJob:
        job.status = JobStatus.PROCESSING
        self.store.save(job)
        try:
            extraction = self.extractor.extract(job.stored_path)
            job.text_preview = extraction.text[:500]
            job.document_type, job.metadata = self.processor.process(extraction.text)
            job.metadata.update(extraction.metadata())
            job.errors = self.rules.validate(job.document_type, job.routing_reference is not None)
            if job.errors:
                job.status = JobStatus.QUARANTINED
                target = self.settings.quarantine_dir / f"{job.id}-{job.original_filename}"
                shutil.copy2(job.stored_path, target)
            else:
                job.metadata["destination_reference"] = self.connector.deliver(job)
                job.status = JobStatus.DELIVERED
        except Exception as exc:
            job.errors.append(str(exc))
            job.status = JobStatus.FAILED
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
        job.review_history.append(
            ReviewEvent(reviewer=request.reviewer, reason=request.reason, changes=changes)
        )
        self.store.save(job)
        return job

    def release(self, job: DocumentJob) -> DocumentJob:
        if job.status == JobStatus.DELIVERED:
            return job
        job.errors = self.rules.validate(job.document_type, job.routing_reference is not None)
        if job.errors:
            job.status = JobStatus.QUARANTINED
        else:
            job.metadata["destination_reference"] = self.connector.deliver(job)
            job.status = JobStatus.DELIVERED
        self.store.save(job)
        return job
