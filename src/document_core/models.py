from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field


class JobStatus(StrEnum):
    RECEIVED = "received"
    PROCESSING = "processing"
    DELIVERING = "delivering"
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
    target_system_id: str | None = None


class DocumentJob(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    status: JobStatus = JobStatus.RECEIVED
    source: str
    original_filename: str
    stored_path: Path
    sha256: str
    document_type: str = "unknown"
    routing_reference: RoutingReference | None = None
    target_system_id: str | None = None
    delivery_path_template: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    review_history: list[ReviewEvent] = Field(default_factory=list)
    text_preview: str = ""
    errors: list[str] = Field(default_factory=list)
    attempt_count: int = 0
    next_attempt_at: datetime | None = None
    lease_expires_at: datetime | None = None
    worker_id: str | None = None
    last_error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class JobListResponse(BaseModel):
    items: list[DocumentJob]
    total: int
    limit: int
    offset: int


class JobStatsResponse(BaseModel):
    total: int
    by_status: dict[JobStatus, int]


class InputChannel(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1, max_length=100)
    kind: str = "hotfolder"
    directory: str = Field(min_length=1, max_length=300)
    patterns: list[str] = Field(default_factory=lambda: ["*"])
    enabled: bool = True
    last_ingested_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class InputChannelCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    directory: str = Field(min_length=1, max_length=300)
    patterns: list[str] = Field(default_factory=lambda: ["*"])
    enabled: bool = True


class InputChannelUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    directory: str | None = Field(default=None, min_length=1, max_length=300)
    patterns: list[str] | None = None
    enabled: bool | None = None


class TargetSystem(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(pattern="^(filesystem|http)$")
    endpoint_url: str | None = Field(default=None, max_length=1000)
    directory: str = Field(default="output", min_length=1, max_length=300)
    path_template: str = Field(
        default="{document_type}/{job_id}", min_length=1, max_length=500
    )
    bearer_token: str | None = Field(default=None, max_length=2000, repr=False)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    enabled: bool = True
    is_default: bool = False
    last_delivery_at: datetime | None = None
    last_error: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class TargetSystemView(BaseModel):
    id: str
    name: str
    kind: str
    endpoint_url: str | None
    directory: str
    path_template: str
    has_bearer_token: bool
    timeout_seconds: int
    enabled: bool
    is_default: bool
    last_delivery_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class TargetSystemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(pattern="^(filesystem|http)$")
    endpoint_url: str | None = Field(default=None, max_length=1000)
    directory: str = Field(default="output", min_length=1, max_length=300)
    path_template: str = Field(
        default="{document_type}/{job_id}", min_length=1, max_length=500
    )
    bearer_token: str | None = Field(default=None, max_length=2000)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    enabled: bool = True
    is_default: bool = False


class TargetSystemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    endpoint_url: str | None = Field(default=None, max_length=1000)
    directory: str | None = Field(default=None, min_length=1, max_length=300)
    path_template: str | None = Field(default=None, min_length=1, max_length=500)
    bearer_token: str | None = Field(default=None, max_length=2000)
    clear_bearer_token: bool = False
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    enabled: bool | None = None
    is_default: bool | None = None


class DeliveryRule(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str = Field(min_length=1, max_length=100)
    document_type: str = Field(min_length=1, max_length=100)
    target_system_id: str
    path_template: str | None = Field(default=None, max_length=500)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class DeliveryRuleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    document_type: str = Field(min_length=1, max_length=100)
    target_system_id: str
    path_template: str | None = Field(default=None, max_length=500)
    enabled: bool = True
    priority: int = Field(default=100, ge=0, le=10000)


class DeliveryRuleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    document_type: str | None = Field(default=None, min_length=1, max_length=100)
    target_system_id: str | None = None
    path_template: str | None = Field(default=None, max_length=500)
    enabled: bool | None = None
    priority: int | None = Field(default=None, ge=0, le=10000)
