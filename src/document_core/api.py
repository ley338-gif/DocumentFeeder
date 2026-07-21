import asyncio
import fnmatch
import shutil
import tempfile
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, File, HTTPException, Query, Response, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from .config import Settings
from .connectors import FilesystemConnector
from .models import (
    DocumentJob,
    InputChannel,
    InputChannelCreate,
    InputChannelUpdate,
    JobListResponse,
    JobStatsResponse,
    JobStatus,
    ReviewRequest,
    TargetSystem,
    TargetSystemCreate,
    TargetSystemUpdate,
    TargetSystemView,
)
from .pipeline import DocumentPipeline
from .store import JobStore


settings = Settings()
settings.create_directories()
store = JobStore(settings.database_url, create_schema=settings.database_auto_create)
pipeline = DocumentPipeline(settings, store, FilesystemConnector(settings.output_dir))


async def watch_hotfolder() -> None:
    while True:
        for channel in store.list_channels(enabled_only=True):
            try:
                directory = resolve_channel_directory(channel.directory)
                directory.mkdir(parents=True, exist_ok=True)
                for path in directory.iterdir():
                    if (
                        path.is_file()
                        and not path.name.startswith(".")
                        and any(fnmatch.fnmatch(path.name, pattern) for pattern in channel.patterns)
                    ):
                        pipeline.ingest(path, f"hotfolder:{channel.name}"[:100])
                        path.unlink()
                        channel.last_ingested_at = datetime.now(UTC)
                        channel.last_error = None
                        store.save_channel(channel)
            except Exception as exc:
                channel.last_error = str(exc)
                store.save_channel(channel)
        await asyncio.sleep(settings.hotfolder_interval)


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.ensure_default_channel()
    store.ensure_default_target_system()
    watcher = asyncio.create_task(watch_hotfolder())
    yield
    watcher.cancel()
    with suppress(asyncio.CancelledError):
        await watcher


app = FastAPI(title="Document Core", version="0.1.0", lifespan=lifespan)
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/", include_in_schema=False)
def operator_console() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/health")
def health() -> dict[str, str]:
    database = "ok" if store.healthcheck() else "error"
    connector = "ok" if pipeline.connector.healthcheck() else "error"
    return {
        "status": "ok" if database == connector == "ok" else "error",
        "database": database,
        "connector": connector,
    }


def validate_channel_settings(directory: str, patterns: list[str]) -> tuple[str, list[str]]:
    if "\\" in directory or ":" in directory:
        raise HTTPException(status_code=422, detail="Hotfolder muss ein relativer POSIX-Pfad sein")
    relative = Path(directory.strip())
    if relative.is_absolute() or not relative.parts or ".." in relative.parts:
        raise HTTPException(status_code=422, detail="Hotfolder muss relativ zum Datenverzeichnis sein")
    normalized = relative.as_posix()
    resolve_channel_directory(normalized)
    cleaned_patterns = [pattern.strip() for pattern in patterns if pattern.strip()]
    if not cleaned_patterns or any("/" in pattern or "\\" in pattern for pattern in cleaned_patterns):
        raise HTTPException(status_code=422, detail="Dateimuster dürfen nur Dateinamen betreffen")
    return normalized, cleaned_patterns


def resolve_channel_directory(directory: str) -> Path:
    root = settings.data_dir.resolve()
    resolved = (root / directory).resolve()
    if resolved == root or root not in resolved.parents:
        raise HTTPException(status_code=422, detail="Hotfolder liegt außerhalb des Datenverzeichnisses")
    return resolved


@app.get("/v1/input-channels", response_model=list[InputChannel])
def list_input_channels() -> list[InputChannel]:
    return store.list_channels()


@app.post("/v1/input-channels", response_model=InputChannel, status_code=201)
def create_input_channel(request: InputChannelCreate) -> InputChannel:
    directory, patterns = validate_channel_settings(request.directory, request.patterns)
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Name darf nicht leer sein")
    channel = InputChannel(
        name=name,
        directory=directory,
        patterns=patterns,
        enabled=request.enabled,
    )
    try:
        store.save_channel(channel)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Name oder Hotfolder ist bereits vergeben") from exc
    resolve_channel_directory(directory).mkdir(parents=True, exist_ok=True)
    return channel


@app.patch("/v1/input-channels/{channel_id}", response_model=InputChannel)
def update_input_channel(channel_id: str, request: InputChannelUpdate) -> InputChannel:
    channel = store.get_channel(channel_id)
    if channel is None:
        raise HTTPException(status_code=404, detail="Eingangskanal nicht gefunden")
    directory = request.directory if request.directory is not None else channel.directory
    patterns = request.patterns if request.patterns is not None else channel.patterns
    channel.directory, channel.patterns = validate_channel_settings(directory, patterns)
    if request.name is not None:
        channel.name = request.name.strip()
        if not channel.name:
            raise HTTPException(status_code=422, detail="Name darf nicht leer sein")
    if request.enabled is not None:
        channel.enabled = request.enabled
    try:
        store.save_channel(channel)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Name oder Hotfolder ist bereits vergeben") from exc
    resolve_channel_directory(channel.directory).mkdir(parents=True, exist_ok=True)
    return channel


@app.delete("/v1/input-channels/{channel_id}", status_code=204)
def delete_input_channel(channel_id: str) -> Response:
    if not store.delete_channel(channel_id):
        raise HTTPException(status_code=404, detail="Eingangskanal nicht gefunden")
    return Response(status_code=204)


def target_view(target: TargetSystem) -> TargetSystemView:
    return TargetSystemView(
        **target.model_dump(exclude={"bearer_token"}),
        has_bearer_token=bool(target.bearer_token),
    )


def validate_target(target: TargetSystem) -> None:
    target.name = target.name.strip()
    if not target.name:
        raise HTTPException(status_code=422, detail="Name darf nicht leer sein")
    if target.kind == "http":
        parsed = urlparse(target.endpoint_url or "")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=422, detail="HTTP-Ziel benötigt eine gültige URL")
    elif target.endpoint_url:
        raise HTTPException(status_code=422, detail="Dateisystem-Ziele haben keine Endpoint-URL")
    if target.is_default and not target.enabled:
        raise HTTPException(status_code=422, detail="Das Standardziel muss aktiv sein")


@app.get("/v1/target-systems", response_model=list[TargetSystemView])
def list_target_systems() -> list[TargetSystemView]:
    return [target_view(target) for target in store.list_target_systems()]


@app.post("/v1/target-systems", response_model=TargetSystemView, status_code=201)
def create_target_system(request: TargetSystemCreate) -> TargetSystemView:
    target = TargetSystem(**request.model_dump())
    validate_target(target)
    try:
        store.save_target_system(target)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Zielsystemname ist bereits vergeben") from exc
    return target_view(target)


@app.patch("/v1/target-systems/{target_id}", response_model=TargetSystemView)
def update_target_system(target_id: str, request: TargetSystemUpdate) -> TargetSystemView:
    target = store.get_target_system(target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Zielsystem nicht gefunden")
    values = request.model_dump(exclude_unset=True, exclude={"clear_bearer_token"})
    for key, value in values.items():
        setattr(target, key, value)
    if request.clear_bearer_token:
        target.bearer_token = None
    validate_target(target)
    try:
        store.save_target_system(target)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Zielsystemname ist bereits vergeben") from exc
    return target_view(target)


@app.delete("/v1/target-systems/{target_id}", status_code=204)
def delete_target_system(target_id: str) -> Response:
    target = store.get_target_system(target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Zielsystem nicht gefunden")
    if target.is_default:
        raise HTTPException(status_code=409, detail="Standardziel kann nicht gelöscht werden")
    store.delete_target_system(target_id)
    return Response(status_code=204)


@app.post("/v1/documents", response_model=DocumentJob, status_code=202)
def upload_document(file: UploadFile = File(...)) -> DocumentJob:
    safe_name = Path(file.filename or "document.bin").name
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(safe_name).suffix) as temporary:
        shutil.copyfileobj(file.file, temporary)
        temporary_path = Path(temporary.name)
    try:
        return pipeline.ingest(temporary_path, "api", safe_name)
    finally:
        temporary_path.unlink(missing_ok=True)


@app.get("/v1/jobs", response_model=JobListResponse)
def list_jobs(
    status: list[JobStatus] = Query(default=[]),
    q: str | None = Query(default=None, max_length=200),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> JobListResponse:
    jobs = store.list()
    if status:
        jobs = [job for job in jobs if job.status in status]
    if q:
        needle = q.casefold()
        jobs = [
            job
            for job in jobs
            if needle in job.original_filename.casefold()
            or needle in job.id.casefold()
            or needle in job.document_type.casefold()
            or needle in str(job.routing_reference or "").casefold()
        ]
    return JobListResponse(
        items=jobs[offset : offset + limit],
        total=len(jobs),
        limit=limit,
        offset=offset,
    )


@app.get("/v1/jobs/stats", response_model=JobStatsResponse)
def job_stats() -> JobStatsResponse:
    jobs = store.list()
    counts = {status: 0 for status in JobStatus}
    for job in jobs:
        counts[job.status] += 1
    return JobStatsResponse(total=len(jobs), by_status=counts)


@app.get("/v1/jobs/{job_id}", response_model=DocumentJob)
def get_job(job_id: str) -> DocumentJob:
    if job := store.get(job_id):
        return job
    raise HTTPException(status_code=404, detail="Job nicht gefunden")


@app.get("/v1/jobs/{job_id}/content", response_class=FileResponse)
def get_job_content(job_id: str, download: bool = False) -> FileResponse:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    path = job.stored_path.resolve()
    inbox = settings.inbox_dir.resolve()
    if inbox not in path.parents or not path.is_file():
        raise HTTPException(status_code=404, detail="Dokumentinhalt nicht gefunden")
    disposition = "attachment" if download else "inline"
    return FileResponse(path, filename=job.original_filename, content_disposition_type=disposition)


@app.patch("/v1/jobs/{job_id}/review", response_model=DocumentJob)
def review_job(job_id: str, request: ReviewRequest) -> DocumentJob:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    if job.status != JobStatus.QUARANTINED:
        raise HTTPException(status_code=409, detail="Nur quarantänisierte Jobs können geprüft werden")
    if request.target_system_id is not None:
        target = store.get_target_system(request.target_system_id)
        if target is None or not target.enabled:
            raise HTTPException(status_code=422, detail="Zielsystem ist nicht vorhanden oder deaktiviert")
    return pipeline.review(job, request)


@app.post("/v1/jobs/{job_id}/release", response_model=DocumentJob)
def release_job(job_id: str) -> DocumentJob:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    if job.status not in {JobStatus.QUARANTINED, JobStatus.DELIVERING, JobStatus.DELIVERED}:
        raise HTTPException(status_code=409, detail="Job kann in diesem Status nicht freigegeben werden")
    return pipeline.release(job)


@app.post("/v1/jobs/{job_id}/retry", response_model=DocumentJob, status_code=202)
def retry_job(job_id: str) -> DocumentJob:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    if job.status != JobStatus.FAILED:
        raise HTTPException(status_code=409, detail="Nur fehlgeschlagene Jobs können neu gestartet werden")
    retried = store.retry_failed(job_id)
    if retried is None:
        raise HTTPException(status_code=409, detail="Jobstatus wurde zwischenzeitlich geändert")
    return retried
