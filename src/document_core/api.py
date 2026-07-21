import asyncio
import shutil
import tempfile
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .config import Settings
from .connectors import FilesystemConnector
from .models import (
    DocumentJob,
    JobListResponse,
    JobStatsResponse,
    JobStatus,
    ReviewRequest,
)
from .pipeline import DocumentPipeline
from .store import JobStore


settings = Settings()
settings.create_directories()
store = JobStore(settings.database_url, create_schema=settings.database_auto_create)
pipeline = DocumentPipeline(settings, store, FilesystemConnector(settings.output_dir))


async def watch_hotfolder() -> None:
    while True:
        for path in settings.hotfolder_dir.iterdir():
            if path.is_file() and not path.name.startswith("."):
                pipeline.ingest(path, "hotfolder")
                path.unlink()
        await asyncio.sleep(settings.hotfolder_interval)


@asynccontextmanager
async def lifespan(_: FastAPI):
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
