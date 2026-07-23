import json
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile


app = FastAPI(title="Document Core Mock Target")
output_dir = Path("/data/mock-target")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/documents", status_code=201)
async def receive_document(
    metadata: str = Form(...), file: UploadFile = File(...)
) -> dict[str, str]:
    try:
        payload = json.loads(metadata)
        job_id = str(payload["job_id"])
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        raise HTTPException(status_code=422, detail="Ungültige Metadaten") from exc
    destination = output_dir / job_id
    destination.mkdir(parents=True, exist_ok=True)
    document = destination / Path(file.filename or "document.bin").name
    with document.open("wb") as target:
        while chunk := await file.read(1024 * 1024):
            target.write(chunk)
    (destination / "delivery.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"reference": f"mock:{job_id}", "status": "accepted"}
