import base64
import hashlib
import json
import re
import shutil
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from datetime import datetime
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
            normalized = re.sub(r'[\\/:*?"<>|\s]+', "_", value.strip())
            normalized = re.sub(r"_+", "_", normalized).strip("._")
            return normalized[:120] or "Unbekannt"

        document_date = parse_document_date(str(job.metadata.get("document_date") or ""))
        effective_date = document_date or job.created_at
        values = {
            "document_type": safe(job.document_type),
            "year": f"{effective_date.year:04d}",
            "month": f"{effective_date.month:02d}",
            "job_id": job.id,
            "reference": safe(
                job.routing_reference.value if job.routing_reference else "ohne-referenz"
            ),
            "supplier_name": safe(
                str(job.metadata.get("supplier_name") or "Unbekannter_Lieferant")
            ),
            "invoice_number": re.sub(
                r"[^A-Za-z0-9]+", "", str(job.metadata.get("invoice_number") or job.id)
            ),
            "extension": job.stored_path.suffix.lower(),
        }
        rendered = (job.delivery_path_template or self.path_template).format_map(values)
        relative = Path(rendered)
        rendered_path = (self.output_dir / relative).resolve()
        root = self.output_dir.resolve()
        if relative.is_absolute() or root not in rendered_path.parents:
            raise ValueError("Zielpfad liegt außerhalb des konfigurierten Ablageordners")
        is_file_template = bool(relative.suffix)
        destination = rendered_path.parent if is_file_template else rendered_path
        destination.mkdir(parents=True, exist_ok=True)
        document = rendered_path if is_file_template else destination / job.original_filename
        if document.exists():
            existing_hash = hashlib.sha256(document.read_bytes()).hexdigest()
            if existing_hash != job.sha256:
                document = document.with_name(
                    f"{document.stem}_{job.id[:8]}{document.suffix}"
                )
        shutil.copy2(job.stored_path, document)
        metadata_name = f"{document.stem}.metadata.json" if is_file_template else "metadata.json"
        (destination / metadata_name).write_text(
            json.dumps(job.model_dump(mode="json"), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return str(document)

    def healthcheck(self) -> bool:
        return self.output_dir.is_dir()


def parse_document_date(value: str) -> datetime | None:
    cleaned = value.strip()
    for date_format in ("%d.%m.%Y", "%d.%m.%y"):
        try:
            return datetime.strptime(cleaned, date_format)
        except ValueError:
            pass
    months = {
        "januar": 1,
        "februar": 2,
        "märz": 3,
        "maerz": 3,
        "april": 4,
        "mai": 5,
        "juni": 6,
        "juli": 7,
        "august": 8,
        "september": 9,
        "oktober": 10,
        "november": 11,
        "dezember": 12,
    }
    match = re.fullmatch(r"(?i)(?:(\d{1,2})\.\s*)?([a-zä]+)\s+(\d{4})", cleaned)
    if match and match.group(2).casefold() in months:
        return datetime(
            int(match.group(3)),
            months[match.group(2).casefold()],
            int(match.group(1) or 1),
        )
    return None


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
