import base64
import json
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class DeliveryPayload(BaseModel):
    job_id: str = Field(min_length=1, max_length=100)
    filename: str = Field(min_length=1, max_length=500)
    content_type: str
    content_base64: str
    document_type: str
    routing_reference: dict | None = None
    metadata: dict


app = FastAPI(title="Document Core Mock Target")
output_dir = Path("/data/mock-target")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/documents", status_code=201)
def receive_document(payload: DeliveryPayload) -> dict[str, str]:
    try:
        content = base64.b64decode(payload.content_base64, validate=True)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Ungültiger Base64-Inhalt") from exc
    destination = output_dir / payload.job_id
    destination.mkdir(parents=True, exist_ok=True)
    document = destination / Path(payload.filename).name
    document.write_bytes(content)
    (destination / "delivery.json").write_text(
        json.dumps(payload.model_dump(exclude={"content_base64"}), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"reference": f"mock:{payload.job_id}"}
