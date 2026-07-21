import asyncio
import shutil
import tempfile
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile

from .config import Settings
from .connectors import FilesystemConnector
from .models import DocumentJob
from .pipeline import DocumentPipeline
from .store import JobStore


settings = Settings()
settings.create_directories()
store = JobStore(settings.jobs_dir)
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
    return {"status": "ok", "connector": "ok" if pipeline.connector.healthcheck() else "error"}


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
def list_jobs() -> list[DocumentJob]:
    return store.list()


@app.get("/v1/jobs/{job_id}", response_model=DocumentJob)
def get_job(job_id: str) -> DocumentJob:
    if job := store.get(job_id):
        return job
    raise HTTPException(status_code=404, detail="Job nicht gefunden")

