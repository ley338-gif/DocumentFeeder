import hashlib
import shutil
from pathlib import Path

from .config import Settings
from .connectors import TargetConnector
from .models import DocumentJob, JobStatus
from .processing import RuleBasedProcessor, TextExtractor, WorkflowRules
from .store import JobStore


class DocumentPipeline:
    def __init__(self, settings: Settings, store: JobStore, connector: TargetConnector):
        self.settings = settings
        self.store = store
        self.connector = connector
        self.extractor = TextExtractor(settings.tesseract_lang)
        self.processor = RuleBasedProcessor()
        self.rules = WorkflowRules(settings.require_patient)

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
            text = self.extractor.extract(job.stored_path)
            job.text_preview = text[:500]
            job.document_type, job.metadata = self.processor.process(text)
            job.errors = self.rules.validate(job.document_type, job.metadata)
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
