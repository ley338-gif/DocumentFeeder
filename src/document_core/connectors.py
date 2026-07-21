import base64
import json
import shutil
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from pathlib import Path

from .models import DocumentJob, TargetSystem


class TargetConnector(ABC):
    """Stable, domain-neutral destination-system boundary."""

    @abstractmethod
    def deliver(self, job: DocumentJob) -> str:
        """Deliver a document and return the destination reference."""

    @abstractmethod
    def healthcheck(self) -> bool:
        """Return whether the destination is reachable."""


class FilesystemConnector(TargetConnector):
    def __init__(
        self,
        output_dir: Path,
        path_template: str = "{document_type}/{job_id}",
    ):
        self.output_dir = output_dir
        self.path_template = path_template
        output_dir.mkdir(parents=True, exist_ok=True)

    def deliver(self, job: DocumentJob) -> str:
        def safe(value: str) -> str:
            return value.replace("/", "_").replace("\\", "_").replace("..", "_")

        values = {
            "document_type": safe(job.document_type),
            "year": f"{job.created_at.year:04d}",
            "month": f"{job.created_at.month:02d}",
            "job_id": job.id,
            "reference": safe(
                job.routing_reference.value if job.routing_reference else "ohne-referenz"
            ),
        }
        rendered = (job.delivery_path_template or self.path_template).format_map(values)
        relative = Path(rendered)
        destination = (self.output_dir / relative).resolve()
        root = self.output_dir.resolve()
        if relative.is_absolute() or root not in destination.parents:
            raise ValueError("Zielpfad liegt außerhalb des konfigurierten Ablageordners")
        destination.mkdir(parents=True, exist_ok=True)
        document = destination / job.original_filename
        shutil.copy2(job.stored_path, document)
        (destination / "metadata.json").write_text(
            json.dumps(job.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return str(document)

    def healthcheck(self) -> bool:
        return self.output_dir.is_dir()


class HttpConnector(TargetConnector):
    def __init__(self, target: TargetSystem):
        if not target.endpoint_url:
            raise ValueError("HTTP-Ziel benötigt eine Endpoint-URL")
        self.target = target

    def deliver(self, job: DocumentJob) -> str:
        payload = {
            "job_id": job.id,
            "filename": job.original_filename,
            "content_type": "application/octet-stream",
            "content_base64": base64.b64encode(job.stored_path.read_bytes()).decode("ascii"),
            "document_type": job.document_type,
            "routing_reference": (
                job.routing_reference.model_dump(mode="json") if job.routing_reference else None
            ),
            "metadata": job.metadata,
        }
        headers = {
            "Content-Type": "application/json",
            "Idempotency-Key": job.id,
            "User-Agent": "Document-Core/0.1",
        }
        if self.target.bearer_token:
            headers["Authorization"] = f"Bearer {self.target.bearer_token}"
        request = urllib.request.Request(
            self.target.endpoint_url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.target.timeout_seconds) as response:
                body = response.read().decode("utf-8")
                data = json.loads(body) if body else {}
                return str(
                    data.get("reference")
                    or data.get("id")
                    or response.headers.get("Location")
                    or f"http:{response.status}:{job.id}"
                )
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"HTTP-Ziel antwortete mit {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"HTTP-Ziel nicht erreichbar: {exc.reason}") from exc

    def healthcheck(self) -> bool:
        return bool(self.target.endpoint_url)
