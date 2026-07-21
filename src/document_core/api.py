import asyncio
import shutil
import tempfile
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile

from .config import Settings
from .connectors import FilesystemConnector
from .models import DocumentJob, JobStatus, ReviewRequest
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


@app.get("/health")
def health() -> dict[str, str]:
    database = "ok" if store.healthcheck() else "error"
    connector = "ok" if pipeline.connector.healthcheck() else "error"
    return {
        "status": "ok" if database == connector == "ok" else "error",
        "database": database,
        "connector": connector,
    }


@app.post("/v1/documents", response_model=DocumentJob, status_code=201)
def upload_document(file: UploadFile = File(...)) -> DocumentJob:
    safe_name = Path(file.filename or "document.bin").name
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(safe_name).suffix) as temporary:
        shutil.copyfileobj(file.file, temporary)
        temporary_path = Path(temporary.name)
    try:
        return pipeline.ingest(temporary_path, "api", safe_name)
    finally:
        temporary_path.unlink(missing_ok=True)


@app.get("/v1/jobs", response_model=list[DocumentJob])
def list_jobs(status: JobStatus | None = None) -> list[DocumentJob]:
    jobs = store.list()
    return [job for job in jobs if job.status == status] if status else jobs


@app.get("/v1/jobs/{job_id}", response_model=DocumentJob)
def get_job(job_id: str) -> DocumentJob:
    if job := store.get(job_id):
        return job
    raise HTTPException(status_code=404, detail="Job nicht gefunden")


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
