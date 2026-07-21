import json
from datetime import UTC, datetime
from pathlib import Path

from .models import DocumentJob


class JobStore:
    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)

    def save(self, job: DocumentJob) -> None:
        job.updated_at = datetime.now(UTC)
        target = self.directory / f"{job.id}.json"
        temporary = target.with_suffix(".tmp")
        temporary.write_text(job.model_dump_json(indent=2), encoding="utf-8")
        temporary.replace(target)

    def get(self, job_id: str) -> DocumentJob | None:
        path = self.directory / f"{job_id}.json"
        return DocumentJob.model_validate_json(path.read_text(encoding="utf-8")) if path.exists() else None

    def list(self) -> list[DocumentJob]:
        jobs = [DocumentJob.model_validate(json.loads(p.read_text(encoding="utf-8"))) for p in self.directory.glob("*.json")]
        return sorted(jobs, key=lambda item: item.created_at, reverse=True)

    def find_by_hash(self, sha256: str) -> DocumentJob | None:
        return next((job for job in self.list() if job.sha256 == sha256), None)
