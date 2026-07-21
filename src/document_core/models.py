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


class RoutingReference(BaseModel):
    namespace: str = Field(min_length=1, max_length=100)
    type: str = Field(min_length=1, max_length=100)
    value: str = Field(min_length=1, max_length=500)


class ReviewEvent(BaseModel):
    reviewer: str
    reason: str
    changes: dict[str, Any]
    reviewed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ReviewRequest(BaseModel):
    reviewer: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=1000)
    document_type: str | None = Field(default=None, min_length=1, max_length=100)
    routing_reference: RoutingReference | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class DocumentJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: JobStatus = JobStatus.RECEIVED
    source: str
    original_filename: str
    stored_path: Path
    sha256: str
    document_type: str = "unknown"
    routing_reference: RoutingReference | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    review_history: list[ReviewEvent] = Field(default_factory=list)
    text_preview: str = ""
    errors: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
