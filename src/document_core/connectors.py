import json
import shutil
from abc import ABC, abstractmethod
from pathlib import Path

from .models import DocumentJob


class TargetConnector(ABC):
    """Stable destination-system boundary (Medical Office adapters implement this)."""

    @abstractmethod
    def deliver(self, job: DocumentJob) -> str:
        """Deliver a document and return the destination reference."""

    @abstractmethod
    def healthcheck(self) -> bool:
        """Return whether the destination is reachable."""


class FilesystemConnector(TargetConnector):
    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

    def deliver(self, job: DocumentJob) -> str:
        destination = self.output_dir / job.document_type / job.id
        destination.mkdir(parents=True, exist_ok=True)
        document = destination / job.original_filename
        shutil.copy2(job.stored_path, document)
        (destination / "metadata.json").write_text(
            json.dumps(job.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return str(document)

    def healthcheck(self) -> bool:
        return self.output_dir.is_dir()

