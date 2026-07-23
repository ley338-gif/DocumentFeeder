import hashlib
import json
import mimetypes
import re
import shutil
import urllib.error
import urllib.request
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from uuid import uuid4

from .models import DocumentJob, TargetSystem


@dataclass(frozen=True)
class DeliveryReceipt:
    reference: str
    connector: str
    status_code: int | None = None
    content_type: str | None = None
    details: dict = field(default_factory=dict)

    def metadata(self) -> dict:
        return {
            "reference": self.reference,
            "connector": self.connector,
            "status_code": self.status_code,
            "content_type": self.content_type,
            "details": self.details,
        }


class ConnectorDeliveryError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class TemporaryConnectorError(ConnectorDeliveryError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        retry_after_seconds: int | None = None,
    ):
        super().__init__(message, status_code=status_code)
        self.retry_after_seconds = retry_after_seconds


class PermanentConnectorError(ConnectorDeliveryError):
    pass


class TargetConnector(ABC):
    """Stable, domain-neutral destination-system boundary."""

    @abstractmethod
    def deliver(self, job: DocumentJob) -> DeliveryReceipt:
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

    def deliver(self, job: DocumentJob) -> DeliveryReceipt:
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
        return DeliveryReceipt(reference=str(document), connector="filesystem")

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


class MultipartBody:
    def __init__(self, job: DocumentJob, chunk_size: int = 1024 * 1024):
        self.job = job
        self.chunk_size = chunk_size
        self.boundary = f"document-core-{uuid4().hex}"
        filename = re.sub(r'[\r\n"]+', "_", Path(job.original_filename).name)
        content_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        metadata = json.dumps(
            {
                "job_id": job.id,
                "filename": job.original_filename,
                "document_type": job.document_type,
                "routing_reference": (
                    job.routing_reference.model_dump(mode="json")
                    if job.routing_reference
                    else None
                ),
                "metadata": job.metadata,
            },
            ensure_ascii=False,
        ).encode("utf-8")
        self.metadata_part = (
            f"--{self.boundary}\r\n"
            'Content-Disposition: form-data; name="metadata"\r\n'
            "Content-Type: application/json; charset=utf-8\r\n\r\n"
        ).encode("ascii") + metadata + b"\r\n"
        self.file_header = (
            f"--{self.boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode("utf-8")
        self.closing = f"\r\n--{self.boundary}--\r\n".encode("ascii")
        self.content_length = (
            len(self.metadata_part)
            + len(self.file_header)
            + job.stored_path.stat().st_size
            + len(self.closing)
        )

    def __iter__(self):
        yield self.metadata_part
        yield self.file_header
        with self.job.stored_path.open("rb") as source:
            while chunk := source.read(self.chunk_size):
                yield chunk
        yield self.closing


def parse_retry_after(value: str | None, now: datetime | None = None) -> int | None:
    if not value:
        return None
    if value.strip().isdigit():
        return min(int(value.strip()), 86400)
    try:
        retry_at = parsedate_to_datetime(value)
        if retry_at.tzinfo is None:
            retry_at = retry_at.replace(tzinfo=UTC)
        seconds = int((retry_at - (now or datetime.now(UTC))).total_seconds())
        return min(max(0, seconds), 86400)
    except (TypeError, ValueError, OverflowError):
        return None


class HttpConnector(TargetConnector):
    temporary_statuses = {408, 425, 429, 500, 502, 503, 504}

    def __init__(self, target: TargetSystem):
        if not target.endpoint_url:
            raise ValueError("HTTP-Ziel benötigt eine Endpoint-URL")
        self.target = target

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": "Document-Core/0.1"}
        if self.target.bearer_token:
            headers["Authorization"] = f"Bearer {self.target.bearer_token}"
        return headers

    def _read_limited(self, response) -> bytes:
        body = response.read(self.target.max_response_bytes + 1)
        if len(body) > self.target.max_response_bytes:
            raise PermanentConnectorError("HTTP-Zielantwort überschreitet das Größenlimit")
        return body

    def deliver(self, job: DocumentJob) -> DeliveryReceipt:
        body = MultipartBody(job)
        headers = self._headers() | {
            "Content-Type": f"multipart/form-data; boundary={body.boundary}",
            "Content-Length": str(body.content_length),
            "Idempotency-Key": job.id,
            "Accept": "application/json",
        }
        request = urllib.request.Request(
            self.target.endpoint_url, data=body, headers=headers, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.target.timeout_seconds) as response:
                response_body = self._read_limited(response)
                content_type = response.headers.get("Content-Type", "").partition(";")[0].lower()
                if response_body and content_type != "application/json":
                    raise PermanentConnectorError(
                        f"Unerwarteter Content-Type der Zielantwort: {content_type or 'unbekannt'}",
                        status_code=response.status,
                    )
                try:
                    data = json.loads(response_body) if response_body else {}
                except json.JSONDecodeError as exc:
                    raise PermanentConnectorError(
                        "HTTP-Ziel lieferte ungültiges JSON", status_code=response.status
                    ) from exc
                if not isinstance(data, dict):
                    raise PermanentConnectorError(
                        "HTTP-Zielquittung muss ein JSON-Objekt sein", status_code=response.status
                    )
                reference = str(
                    data.get("reference")
                    or data.get("id")
                    or response.headers.get("Location")
                    or f"http:{response.status}:{job.id}"
                )
                return DeliveryReceipt(
                    reference=reference,
                    connector="http",
                    status_code=response.status,
                    content_type=content_type or None,
                    details={
                        "location": response.headers.get("Location"),
                        "acknowledgement": {
                            key: data[key] for key in ("reference", "id", "status") if key in data
                        },
                    },
                )
        except urllib.error.HTTPError as exc:
            detail = exc.read(min(self.target.max_response_bytes, 500)).decode(
                "utf-8", errors="replace"
            )
            message = f"HTTP-Ziel antwortete mit {exc.code}: {detail}"
            if exc.code in self.temporary_statuses:
                raise TemporaryConnectorError(
                    message,
                    status_code=exc.code,
                    retry_after_seconds=parse_retry_after(exc.headers.get("Retry-After")),
                ) from exc
            raise PermanentConnectorError(message, status_code=exc.code) from exc
        except urllib.error.URLError as exc:
            raise TemporaryConnectorError(f"HTTP-Ziel nicht erreichbar: {exc.reason}") from exc
        except TimeoutError as exc:
            raise TemporaryConnectorError("Zeitüberschreitung beim HTTP-Ziel") from exc

    def healthcheck(self) -> bool:
        if not self.target.healthcheck_url:
            return False
        request = urllib.request.Request(
            self.target.healthcheck_url,
            headers=self._headers() | {"Accept": "application/json"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.target.timeout_seconds) as response:
                self._read_limited(response)
                return 200 <= response.status < 400
        except (
            ConnectorDeliveryError,
            urllib.error.HTTPError,
            urllib.error.URLError,
            TimeoutError,
        ):
            return False
