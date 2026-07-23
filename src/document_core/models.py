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


class UserRole(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class UserAccount(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    username: str = Field(min_length=3, max_length=100)
    display_name: str = Field(min_length=1, max_length=200)
    role: UserRole = UserRole.VIEWER
    active: bool = True
    password_hash: str = Field(exclude=True, repr=False)
    last_login_at: datetime | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class UserView(BaseModel):
    id: str
    username: str
    display_name: str
    role: UserRole
    active: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=100, pattern=r"^[a-zA-Z0-9._-]+$")
    display_name: str = Field(min_length=1, max_length=200)
    role: UserRole
    password: str = Field(min_length=12, max_length=200)


class UserUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    role: UserRole | None = None
    active: bool | None = None
    password: str | None = Field(default=None, min_length=12, max_length=200)


class LoginRequest(BaseModel):
    username: str
    password: str


class ProfileUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=200)
    password: str | None = Field(default=None, min_length=12, max_length=200)


class AuditEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    actor_user_id: str | None = None
    actor_username: str
    action: str
    resource_type: str
    resource_id: str | None = None
    outcome: str
    status_code: int
    details: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class AuditListResponse(BaseModel):
    items: list[AuditEvent]
    total: int
    limit: int
    offset: int


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


class JobEvent(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    job_id: str
    event_type: str = Field(min_length=1, max_length=100)
    status: str = Field(min_length=1, max_length=32)
    message: str = Field(min_length=1, max_length=500)
    attempt: int | None = None
    target_system_id: str | None = None
    target_name: str | None = None
    delivery_rule: str | None = None
    external_reference: str | None = None
    error: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


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
    duplicate: bool = False


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
    kind: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,63}$")
    endpoint_url: str | None = Field(default=None, max_length=1000)
    healthcheck_url: str | None = Field(default=None, max_length=1000)
    directory: str = Field(default="output", min_length=1, max_length=300)
    path_template: str = Field(
        default="{document_type}/{job_id}", min_length=1, max_length=500
    )
    bearer_token: str | None = Field(default=None, max_length=2000, repr=False)
    graph_tenant_id: str | None = Field(default=None, max_length=200)
    graph_client_id: str | None = Field(default=None, max_length=200)
    graph_client_secret: str | None = Field(default=None, max_length=2000, repr=False)
    graph_drive_id: str | None = Field(default=None, max_length=300)
    graph_folder: str = Field(default="DocumentCore", max_length=500)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_response_bytes: int = Field(default=65536, ge=1024, le=1048576)
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
    connector_name: str
    capabilities: list[str]
    licensed: bool
    endpoint_url: str | None
    healthcheck_url: str | None
    directory: str
    path_template: str
    has_bearer_token: bool
    graph_tenant_id: str | None
    graph_client_id: str | None
    has_graph_client_secret: bool
    graph_drive_id: str | None
    graph_folder: str
    timeout_seconds: int
    max_response_bytes: int
    enabled: bool
    is_default: bool
    last_delivery_at: datetime | None
    last_error: str | None
    created_at: datetime
    updated_at: datetime


class TargetSystemCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    kind: str = Field(pattern=r"^[a-z][a-z0-9_.-]{1,63}$")
    endpoint_url: str | None = Field(default=None, max_length=1000)
    healthcheck_url: str | None = Field(default=None, max_length=1000)
    directory: str = Field(default="output", min_length=1, max_length=300)
    path_template: str = Field(
        default="{document_type}/{job_id}", min_length=1, max_length=500
    )
    bearer_token: str | None = Field(default=None, max_length=2000)
    graph_tenant_id: str | None = Field(default=None, max_length=200)
    graph_client_id: str | None = Field(default=None, max_length=200)
    graph_client_secret: str | None = Field(default=None, max_length=2000)
    graph_drive_id: str | None = Field(default=None, max_length=300)
    graph_folder: str = Field(default="DocumentCore", max_length=500)
    timeout_seconds: int = Field(default=30, ge=1, le=300)
    max_response_bytes: int = Field(default=65536, ge=1024, le=1048576)
    enabled: bool = True
    is_default: bool = False


class TargetSystemUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    endpoint_url: str | None = Field(default=None, max_length=1000)
    healthcheck_url: str | None = Field(default=None, max_length=1000)
    directory: str | None = Field(default=None, min_length=1, max_length=300)
    path_template: str | None = Field(default=None, min_length=1, max_length=500)
    bearer_token: str | None = Field(default=None, max_length=2000)
    clear_bearer_token: bool = False
    graph_tenant_id: str | None = Field(default=None, max_length=200)
    graph_client_id: str | None = Field(default=None, max_length=200)
    graph_client_secret: str | None = Field(default=None, max_length=2000)
    clear_graph_client_secret: bool = False
    graph_drive_id: str | None = Field(default=None, max_length=300)
    graph_folder: str | None = Field(default=None, max_length=500)
    timeout_seconds: int | None = Field(default=None, ge=1, le=300)
    max_response_bytes: int | None = Field(default=None, ge=1024, le=1048576)
    enabled: bool | None = None
    is_default: bool | None = None


class LicenseActivationRequest(BaseModel):
    license_key: str = Field(min_length=20, max_length=10000)


class LicenseStatusView(BaseModel):
    status: str
    configured: bool
    installation_id: str
    customer: str | None = None
    features: list[str] = Field(default_factory=list)
    expires_at: datetime | None = None
    detail: str | None = None


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
