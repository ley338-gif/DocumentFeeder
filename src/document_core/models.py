from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    DELIVERED = "delivered"
    QUARANTINED = "quarantined"
    FAILED = "failed"


class DocumentJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: JobStatus = JobStatus.RECEIVED
    source: str
    original_filename: str
    stored_path: Path
    sha256: str
    document_type: str = "unknown"
    metadata: dict[str, Any] = Field(default_factory=dict)
    text_preview: str = ""
    errors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

