import asyncio
import csv
import fnmatch
import io
import json
import tempfile
import hashlib
import hmac
from contextlib import asynccontextmanager, suppress
from datetime import UTC, datetime, timedelta
from pathlib import Path
from string import Formatter
from urllib.parse import urlparse

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, Response, UploadFile
from fastapi.responses import JSONResponse
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import IntegrityError

from .config import Settings
from .auth import hash_password, new_csrf_token, new_session_token, verify_password
from .connectors import FilesystemConnector
from .licensing import (
    EntitlementRequiredError,
    LicenseValidationError,
    LicenseVerifier,
)
from .file_validation import DocumentRejectedError, FileTooLargeError
from .models import (
    DocumentJob,
    AuditEvent,
    AuditCleanupResult,
    AuditIntegrityStatus,
    AuditListResponse,
    AuditRetentionSettings,
    DeliveryRule,
    DeliveryRuleCreate,
    DeliveryRuleUpdate,
    InputChannel,
    InputChannelCreate,
    InputChannelUpdate,
    JobEvent,
    JobListResponse,
    JobStatsResponse,
    JobStatus,
    LicenseActivationRequest,
    LicenseStatusView,
    ReviewRequest,
    TargetSystem,
    TargetSystemCreate,
    TargetSystemUpdate,
    TargetSystemView,
    LoginRequest,
    ProfileUpdate,
    UserAccount,
    UserCreate,
    UserRole,
    UserUpdate,
    UserView,
)
from .pipeline import DocumentPipeline
from .store import JobStore
from .secrets import SecretCipher


settings = Settings()
settings.create_directories()
store = JobStore(
    settings.database_url,
    create_schema=settings.database_auto_create,
    secret_cipher=SecretCipher.from_csv(settings.connector_secret_key_material),
)
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
                if channel.last_error is not None:
                    channel.last_error = None
                    store.save_channel(channel)
            except Exception as exc:
                channel.last_error = str(exc)
                store.save_channel(channel)
        await asyncio.sleep(settings.hotfolder_interval)


def audit_retention_days() -> int:
    try:
        return max(30, min(3650, int(
            store.get_system_setting("audit_retention_days", "365") or "365"
        )))
    except ValueError:
        return 365


async def enforce_audit_retention() -> None:
    while True:
        cutoff = datetime.now(UTC) - timedelta(days=audit_retention_days())
        deleted = store.delete_audit_events_before(cutoff)
        if deleted:
            store.save_audit_event(AuditEvent(
                actor_username="system",
                action="AUDIT_RETENTION",
                resource_type="audit",
                outcome="success",
                status_code=200,
                details={"deleted": deleted, "cutoff": cutoff.isoformat()},
            ))
        integrity = store.verify_audit_chain()
        store.set_system_setting(
            "audit_integrity_status",
            json.dumps(integrity, ensure_ascii=False, separators=(",", ":")),
        )
        await asyncio.sleep(24 * 60 * 60)


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.migrate_or_rotate_target_secrets()
    store.initialize_audit_chain()
    store.ensure_installation_id()
    if settings.auth_enabled and not store.list_users():
        if not settings.bootstrap_admin_password:
            raise RuntimeError("Bootstrap-Admin-Passwort muss für die erste Anmeldung gesetzt sein")
        store.save_user(UserAccount(
            username=settings.bootstrap_admin_username,
            display_name="Administrator",
            role=UserRole.ADMIN,
            password_hash=hash_password(settings.bootstrap_admin_password),
        ))
    store.ensure_default_channel()
    store.ensure_default_target_system()
    watcher = asyncio.create_task(watch_hotfolder())
    retention = asyncio.create_task(enforce_audit_retention())
    yield
    watcher.cancel()
    retention.cancel()
    with suppress(asyncio.CancelledError):
        await watcher
    with suppress(asyncio.CancelledError):
        await retention


app = FastAPI(title="Document Core", version="0.1.0", lifespan=lifespan)
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


def session_user(request: Request) -> UserAccount | None:
    token = request.cookies.get("document_core_session")
    return store.get_session_user(hashlib.sha256(token.encode()).hexdigest()) if token else None


def record_audit(user: UserAccount | None, method: str, path: str, status_code: int) -> None:
    parts = [part for part in path.split("/") if part]
    resource_type = parts[1] if len(parts) > 1 else "system"
    resource_id = parts[2] if len(parts) > 2 else None
    store.save_audit_event(AuditEvent(
        actor_user_id=user.id if user else None,
        actor_username=user.username if user else "unknown",
        action=f"{method} {path}",
        resource_type=resource_type,
        resource_id=resource_id,
        outcome="success" if status_code < 400 else "failure",
        status_code=status_code,
        details={"method": method, "path": path},
    ))


@app.middleware("http")
async def authorize(request: Request, call_next):
    if not settings.auth_enabled:
        return await call_next(request)
    path = request.url.path
    public = path in {"/", "/health", "/v1/auth/login"} or path.startswith("/static/")
    if public:
        return await call_next(request)
    user = session_user(request)
    if user is None:
        return JSONResponse({"detail": "Anmeldung erforderlich"}, status_code=401)
    request.state.user = user
    safe_method = request.method in {"GET", "HEAD", "OPTIONS"}
    if not safe_method:
        csrf_cookie = request.cookies.get("document_core_csrf")
        csrf_header = request.headers.get("X-CSRF-Token")
        if not csrf_cookie or not csrf_header or not hmac.compare_digest(csrf_cookie, csrf_header):
            return JSONResponse({"detail": "Ungültiger CSRF-Schutz"}, status_code=403)
    if path.startswith(
        ("/v1/users", "/v1/audit-events", "/v1/system-status", "/v1/license")
    ) and user.role != UserRole.ADMIN:
        return JSONResponse({"detail": "Administratorrechte erforderlich"}, status_code=403)
    configuration = ("/v1/input-channels", "/v1/target-systems", "/v1/delivery-rules")
    if path.startswith(configuration) and not safe_method and user.role != UserRole.ADMIN:
        return JSONResponse({"detail": "Administratorrechte erforderlich"}, status_code=403)
    self_service = path in {"/v1/auth/me", "/v1/auth/logout"}
    if not safe_method and user.role == UserRole.VIEWER and not self_service:
        return JSONResponse({"detail": "Nur Lesezugriff erlaubt"}, status_code=403)
    response = await call_next(request)
    if not safe_method:
        record_audit(user, request.method, path, response.status_code)
    return response


def user_view(user: UserAccount) -> UserView:
    return UserView(**user.model_dump(exclude={"password_hash"}))


@app.post("/v1/auth/login", response_model=UserView)
def login(request: LoginRequest, response: Response) -> UserView:
    username = request.username.lower()
    since = datetime.now(UTC) - timedelta(minutes=settings.login_window_minutes)
    if store.recent_failed_logins(username, since) >= settings.login_max_attempts:
        store.save_audit_event(AuditEvent(
            actor_username=username, action="LOGIN", resource_type="session",
            outcome="failure", status_code=429, details={"reason": "rate_limited"},
        ))
        raise HTTPException(status_code=429, detail="Zu viele Anmeldeversuche. Bitte später erneut versuchen")
    user = store.get_user_by_username(request.username)
    if user is None or not user.active or not verify_password(request.password, user.password_hash):
        store.save_audit_event(AuditEvent(
            actor_username=username,
            action="LOGIN",
            resource_type="session",
            outcome="failure",
            status_code=401,
        ))
        raise HTTPException(status_code=401, detail="Benutzername oder Passwort ist falsch")
    token, token_hash = new_session_token()
    csrf_token = new_csrf_token()
    store.create_session(token_hash, user.id, datetime.now(UTC) + timedelta(hours=settings.session_ttl_hours))
    user.last_login_at = datetime.now(UTC)
    store.save_user(user)
    store.save_audit_event(AuditEvent(
        actor_user_id=user.id,
        actor_username=user.username,
        action="LOGIN",
        resource_type="session",
        outcome="success",
        status_code=200,
    ))
    response.set_cookie("document_core_session", token, httponly=True, samesite="strict", secure=settings.session_cookie_secure, max_age=settings.session_ttl_hours * 3600)
    response.set_cookie("document_core_csrf", csrf_token, httponly=False, samesite="strict", secure=settings.session_cookie_secure, max_age=settings.session_ttl_hours * 3600)
    return user_view(user)


@app.get("/v1/auth/me", response_model=UserView)
def current_user(request: Request, response: Response) -> UserView:
    if not request.cookies.get("document_core_csrf"):
        response.set_cookie(
            "document_core_csrf",
            new_csrf_token(),
            httponly=False,
            samesite="strict",
            secure=settings.session_cookie_secure,
            max_age=settings.session_ttl_hours * 3600,
        )
    return user_view(request.state.user)


@app.patch("/v1/auth/me", response_model=UserView)
def update_profile(request: Request, profile: ProfileUpdate) -> UserView:
    user = request.state.user
    if profile.display_name is not None:
        user.display_name = profile.display_name.strip()
    if profile.password is not None:
        user.password_hash = hash_password(profile.password)
    saved = store.save_user(user)
    if profile.password is not None:
        store.delete_user_sessions(user.id)
    return user_view(saved)


@app.post("/v1/auth/logout", status_code=204)
def logout(request: Request, response: Response) -> Response:
    token = request.cookies.get("document_core_session")
    if token:
        store.delete_session(hashlib.sha256(token.encode()).hexdigest())
    response.delete_cookie("document_core_session")
    response.delete_cookie("document_core_csrf")
    response.status_code = 204
    return response


@app.get("/v1/users", response_model=list[UserView])
def list_users() -> list[UserView]:
    return [user_view(user) for user in store.list_users()]


@app.post("/v1/users", response_model=UserView, status_code=201)
def create_user(request: UserCreate) -> UserView:
    if store.get_user_by_username(request.username):
        raise HTTPException(status_code=409, detail="Benutzername ist bereits vergeben")
    user = UserAccount(**request.model_dump(exclude={"password"}), password_hash=hash_password(request.password))
    return user_view(store.save_user(user))


@app.patch("/v1/users/{user_id}", response_model=UserView)
def update_user(user_id: str, request: UserUpdate, http_request: Request) -> UserView:
    user = store.get_user(user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="Benutzer nicht gefunden")
    values = request.model_dump(exclude_unset=True)
    password = values.pop("password", None)
    for key, value in values.items():
        setattr(user, key, value)
    if password:
        user.password_hash = hash_password(password)
    if user.id == http_request.state.user.id and not user.active:
        raise HTTPException(status_code=409, detail="Das eigene Konto kann nicht deaktiviert werden")
    active_admins = [item for item in store.list_users() if item.active and item.role == UserRole.ADMIN]
    if user.id in {item.id for item in active_admins} and (
        not user.active or user.role != UserRole.ADMIN
    ) and len(active_admins) == 1:
        raise HTTPException(status_code=409, detail="Der letzte aktive Admin muss erhalten bleiben")
    saved = store.save_user(user)
    if password or not user.active:
        store.delete_user_sessions(user.id)
    return user_view(saved)


@app.get("/v1/audit-events", response_model=AuditListResponse)
def list_audit_events(
    q: str | None = Query(default=None, max_length=200),
    outcome: str | None = Query(default=None, pattern="^(success|failure)$"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> AuditListResponse:
    events, total = store.search_audit_events(q, outcome, limit, offset)
    return AuditListResponse(
        items=events, total=total, limit=limit, offset=offset
    )


@app.get("/v1/audit-events/export")
def export_audit_events(
    request: Request,
    q: str | None = Query(default=None, max_length=200),
    outcome: str | None = Query(default=None, pattern="^(success|failure)$"),
) -> StreamingResponse:
    user = getattr(request.state, "user", None)
    store.save_audit_event(AuditEvent(
        actor_user_id=user.id if user else None,
        actor_username=user.username if user else "system",
        action="EXPORT_AUDIT",
        resource_type="audit",
        outcome="success",
        status_code=200,
        details={"q": q, "outcome": outcome, "format": "csv"},
    ))

    def rows():
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow((
            "created_at", "actor_username", "action", "resource_type", "resource_id",
            "outcome", "status_code", "details",
        ))
        yield buffer.getvalue().encode("utf-8-sig")
        for event in store.iter_audit_events(q, outcome):
            buffer.seek(0)
            buffer.truncate(0)
            writer.writerow((
                event.created_at.isoformat(),
                event.actor_username,
                event.action,
                event.resource_type,
                event.resource_id or "",
                event.outcome,
                event.status_code,
                json.dumps(event.details, ensure_ascii=False, separators=(",", ":")),
            ))
            yield buffer.getvalue().encode("utf-8")

    filename = f"document-core-audit-{datetime.now(UTC):%Y-%m-%d}.csv"
    return StreamingResponse(
        rows(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/v1/audit-events/retention", response_model=AuditRetentionSettings)
def get_audit_retention() -> AuditRetentionSettings:
    return AuditRetentionSettings(retention_days=audit_retention_days())


@app.put("/v1/audit-events/retention", response_model=AuditRetentionSettings)
def set_audit_retention(
    settings_request: AuditRetentionSettings,
) -> AuditRetentionSettings:
    store.set_system_setting(
        "audit_retention_days", str(settings_request.retention_days)
    )
    return settings_request


@app.post("/v1/audit-events/cleanup", response_model=AuditCleanupResult)
def cleanup_audit_events() -> AuditCleanupResult:
    cutoff = datetime.now(UTC) - timedelta(days=audit_retention_days())
    deleted = store.delete_audit_events_before(cutoff)
    return AuditCleanupResult(deleted=deleted, cutoff=cutoff)


@app.get("/v1/audit-events/integrity", response_model=AuditIntegrityStatus)
def verify_audit_integrity() -> AuditIntegrityStatus:
    result = store.verify_audit_chain()
    store.set_system_setting(
        "audit_integrity_status",
        json.dumps(result, ensure_ascii=False, separators=(",", ":")),
    )
    return AuditIntegrityStatus(**result)


@app.get("/v1/system-status")
def system_status() -> dict:
    now = datetime.now(UTC)
    jobs = store.list()
    channels = store.list_channels()
    targets = store.list_target_systems()
    stale_after = max(10.0, settings.worker_poll_interval * 3 + 5)

    def aware(value: datetime) -> datetime:
        return value if value.tzinfo else value.replace(tzinfo=UTC)

    workers = []
    for item in store.list_worker_heartbeats():
        age = (now - aware(item["last_seen_at"])).total_seconds()
        workers.append({**item, "status": "ok" if age <= stale_after else "stale"})
    active_workers = [item for item in workers if item["status"] == "ok"]
    waiting = [job for job in jobs if job.status == JobStatus.RECEIVED]
    delivered = [job for job in jobs if job.status == JobStatus.DELIVERED]
    scanner_configured = settings.malware_scanner != "disabled"
    scanning_enabled = scanner_configured and (
        store.get_system_setting("malware_scanning_enabled", "true") == "true"
    )
    malware = pipeline.malware_scanner.healthcheck() if scanning_enabled else {
        "status": "paused", "engine": settings.malware_scanner
    }
    malware.update({"enabled": scanning_enabled, "controllable": scanner_configured})
    database_ok = store.healthcheck()
    try:
        audit_integrity = json.loads(
            store.get_system_setting("audit_integrity_status", "{}") or "{}"
        )
    except json.JSONDecodeError:
        audit_integrity = {}
    audit_integrity.setdefault("status", "unknown")
    target_errors = [target for target in targets if target.last_error]
    channel_errors = [channel for channel in channels if channel.last_error]
    status = "ok"
    if (
        not database_ok
        or not active_workers
        or malware["status"] == "error"
        or audit_integrity["status"] == "invalid"
    ):
        status = "error"
    elif (
        target_errors or channel_errors or (scanner_configured and not scanning_enabled)
        or any(job.status == JobStatus.FAILED for job in jobs)
    ):
        status = "warning"
    return {
        "status": status,
        "generated_at": now,
        "version": app.version,
        "schema_version": store.schema_version(),
        "services": {
            "api": {"status": "ok"},
            "database": {"status": "ok" if database_ok else "error"},
            "malware_scanner": malware,
            "audit_trail": audit_integrity,
        },
        "queue": {
            "waiting": len(waiting),
            "processing": sum(job.status == JobStatus.PROCESSING for job in jobs),
            "scheduled_retries": sum(job.next_attempt_at is not None for job in jobs),
            "failed": sum(job.status == JobStatus.FAILED for job in jobs),
            "quarantined": sum(job.status == JobStatus.QUARANTINED for job in jobs),
            "oldest_waiting_at": min((job.created_at for job in waiting), default=None),
            "last_delivered_at": max((job.updated_at for job in delivered), default=None),
        },
        "workers": workers,
        "channels": {
            "total": len(channels), "enabled": sum(channel.enabled for channel in channels),
            "errors": len(channel_errors),
        },
        "targets": {
            "total": len(targets), "enabled": sum(target.enabled for target in targets),
            "errors": len(target_errors),
        },
        "storage": {
            "input_root": str(settings.input_root),
            "work_root": str(settings.work_root_dir),
            "destination_root": str(settings.destination_root),
            "delivered_file_policy": settings.delivered_file_policy,
        },
    }


@app.post("/v1/system-status/malware-scanner")
def control_malware_scanner(enabled: bool = Body(embed=True)) -> dict:
    if settings.malware_scanner == "disabled" and enabled:
        raise HTTPException(status_code=409, detail="Kein Malware-Scanner konfiguriert")
    store.set_system_setting("malware_scanning_enabled", "true" if enabled else "false")
    return {"enabled": enabled, "status": "enabled" if enabled else "paused"}


def license_status_view() -> LicenseStatusView:
    installation_id = store.ensure_installation_id()
    verifier = LicenseVerifier(settings.license_public_key)
    license_key = store.get_system_setting("license_key")
    if not verifier.configured:
        return LicenseStatusView(
            status="not_configured",
            configured=False,
            installation_id=installation_id,
            detail="Öffentlicher Lizenzschlüssel ist nicht konfiguriert",
        )
    if not license_key:
        return LicenseStatusView(
            status="missing",
            configured=True,
            installation_id=installation_id,
            detail="Keine Lizenz aktiviert",
        )
    try:
        verified = verifier.verify(license_key, installation_id)
    except LicenseValidationError as exc:
        return LicenseStatusView(
            status="invalid",
            configured=True,
            installation_id=installation_id,
            detail=str(exc),
        )
    return LicenseStatusView(
        status="active",
        configured=True,
        installation_id=installation_id,
        customer=verified.customer,
        features=sorted(verified.features),
        expires_at=verified.expires_at,
    )


@app.get("/v1/license", response_model=LicenseStatusView)
def get_license_status() -> LicenseStatusView:
    return license_status_view()


@app.post("/v1/license", response_model=LicenseStatusView)
def activate_license(request: LicenseActivationRequest) -> LicenseStatusView:
    installation_id = store.ensure_installation_id()
    try:
        LicenseVerifier(settings.license_public_key).verify(
            request.license_key, installation_id
        )
    except LicenseValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    store.set_system_setting("license_key", request.license_key.strip())
    return license_status_view()


@app.delete("/v1/license", status_code=204)
def remove_license() -> Response:
    store.set_system_setting("license_key", "")
    return Response(status_code=204)


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
    root = settings.input_root.resolve()
    resolved = (root / directory).resolve()
    if resolved == root or root not in resolved.parents:
        raise HTTPException(status_code=422, detail="Hotfolder liegt außerhalb des Datenverzeichnisses")
    return resolved


def resolve_target_directory(directory: str) -> Path:
    root = settings.destination_root.resolve()
    resolved = (root / directory).resolve()
    if resolved == root or root not in resolved.parents:
        raise HTTPException(status_code=422, detail="Zielordner liegt außerhalb des Zielbereichs")
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
    connector_registry = pipeline.connector_registry
    module = connector_registry.get(target.kind)
    return TargetSystemView(
        **target.model_dump(exclude={"bearer_token", "graph_client_secret"}),
        has_bearer_token=bool(target.bearer_token),
        has_graph_client_secret=bool(target.graph_client_secret),
        connector_name=module.name if module else target.kind,
        capabilities=list(module.capabilities) if module else [],
        licensed=bool(module and connector_registry.entitlements.allows(module.license_feature)),
    )


def validate_target(target: TargetSystem) -> None:
    connector_registry = pipeline.connector_registry
    target.name = target.name.strip()
    if not target.name:
        raise HTTPException(status_code=422, detail="Name darf nicht leer sein")
    if (target.bearer_token or target.graph_client_secret) and not store.secret_cipher.available:
        raise HTTPException(
            status_code=503,
            detail="Connector-Secrets sind nicht konfiguriert",
        )
    try:
        connector_registry.require_available(target.kind)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except EntitlementRequiredError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    if target.kind == "http":
        parsed = urlparse(target.endpoint_url or "")
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise HTTPException(status_code=422, detail="HTTP-Ziel benötigt eine gültige URL")
        if target.healthcheck_url:
            health = urlparse(target.healthcheck_url)
            if health.scheme not in {"http", "https"} or not health.netloc:
                raise HTTPException(
                    status_code=422, detail="Healthcheck benötigt eine gültige HTTP-URL"
                )
    elif target.kind == "microsoft_graph":
        required = {
            "Mandant-ID": target.graph_tenant_id,
            "Client-ID": target.graph_client_id,
            "Client-Secret": target.graph_client_secret,
            "Drive-ID": target.graph_drive_id,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise HTTPException(
                status_code=422,
                detail=f"Microsoft Graph benötigt: {', '.join(missing)}",
            )
        target.graph_folder = target.graph_folder.strip().strip("/")
        if not target.graph_folder or any(
            part in {"", ".", ".."} for part in target.graph_folder.split("/")
        ):
            raise HTTPException(status_code=422, detail="Ungültiger Microsoft-Graph-Zielordner")
    elif target.endpoint_url:
        raise HTTPException(status_code=422, detail="Dieses Ziel verwendet keine Endpoint-URL")
    if target.kind == "filesystem":
        if "\\" in target.directory or ":" in target.directory:
            raise HTTPException(status_code=422, detail="Zielordner muss ein relativer POSIX-Pfad sein")
        relative = Path(target.directory.strip())
        if relative.is_absolute() or not relative.parts or ".." in relative.parts:
            raise HTTPException(status_code=422, detail="Zielordner muss relativ zum Zielbereich sein")
        target.directory = relative.as_posix()
        resolve_target_directory(target.directory)
        validate_path_template(target.path_template)
    if target.is_default and not target.enabled:
        raise HTTPException(status_code=422, detail="Das Standardziel muss aktiv sein")


def validate_path_template(template: str) -> str:
    allowed = {
        "document_type",
        "year",
        "month",
        "job_id",
        "reference",
        "supplier_name",
        "invoice_number",
        "extension",
    }
    try:
        fields = {field for _, field, _, _ in Formatter().parse(template) if field}
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Ungültige Pfadvorlage") from exc
    if not fields.issubset(allowed) or "\\" in template or Path(template).is_absolute():
        raise HTTPException(status_code=422, detail="Pfadvorlage enthält ungültige Platzhalter")
    if ".." in Path(template).parts:
        raise HTTPException(status_code=422, detail="Pfadvorlage darf data/ nicht verlassen")
    return template


@app.get("/v1/target-systems", response_model=list[TargetSystemView])
def list_target_systems() -> list[TargetSystemView]:
    return [target_view(target) for target in store.list_target_systems()]


@app.get("/v1/connector-modules")
def list_connector_modules() -> list[dict]:
    return pipeline.connector_registry.describe()


@app.get("/v1/target-systems/{target_id}/health")
def target_system_health(target_id: str) -> dict:
    target = store.get_target_system(target_id)
    if target is None:
        raise HTTPException(status_code=404, detail="Zielsystem nicht gefunden")
    try:
        healthy = pipeline.connector_registry.create(target).healthcheck()
    except Exception as exc:
        return {"status": "error", "detail": store.redact(str(exc))}
    return {
        "status": "ok" if healthy else "error",
        "detail": None if healthy else "Zielsystem nicht erreichbar oder Healthcheck fehlt",
    }


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
    values = request.model_dump(
        exclude_unset=True,
        exclude={"clear_bearer_token", "clear_graph_client_secret"},
    )
    for key, value in values.items():
        setattr(target, key, value)
    if request.clear_bearer_token:
        target.bearer_token = None
    if request.clear_graph_client_secret:
        target.graph_client_secret = None
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


@app.get("/v1/delivery-rules", response_model=list[DeliveryRule])
def list_delivery_rules() -> list[DeliveryRule]:
    return store.list_delivery_rules()


@app.post("/v1/delivery-rules", response_model=DeliveryRule, status_code=201)
def create_delivery_rule(request: DeliveryRuleCreate) -> DeliveryRule:
    target = store.get_target_system(request.target_system_id)
    if target is None:
        raise HTTPException(status_code=422, detail="Zielsystem nicht gefunden")
    values = request.model_dump()
    if request.path_template:
        values["path_template"] = validate_path_template(request.path_template)
    rule = DeliveryRule(**values)
    try:
        return store.save_delivery_rule(rule)
    except IntegrityError as exc:
        raise HTTPException(status_code=409, detail="Regelname ist bereits vergeben") from exc


@app.patch("/v1/delivery-rules/{rule_id}", response_model=DeliveryRule)
def update_delivery_rule(rule_id: str, request: DeliveryRuleUpdate) -> DeliveryRule:
    rule = store.get_delivery_rule(rule_id)
    if rule is None:
        raise HTTPException(status_code=404, detail="Automatisierungsregel nicht gefunden")
    values = request.model_dump(exclude_unset=True)
    if "target_system_id" in values and store.get_target_system(values["target_system_id"]) is None:
        raise HTTPException(status_code=422, detail="Zielsystem nicht gefunden")
    if values.get("path_template"):
        values["path_template"] = validate_path_template(values["path_template"])
    for key, value in values.items():
        setattr(rule, key, value)
    return store.save_delivery_rule(rule)


@app.delete("/v1/delivery-rules/{rule_id}", status_code=204)
def delete_delivery_rule(rule_id: str) -> Response:
    if not store.delete_delivery_rule(rule_id):
        raise HTTPException(status_code=404, detail="Automatisierungsregel nicht gefunden")
    return Response(status_code=204)


@app.post("/v1/documents", response_model=DocumentJob, status_code=202)
def upload_document(file: UploadFile = File(...)) -> DocumentJob:
    safe_name = Path(file.filename or "document.bin").name
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=Path(safe_name).suffix) as temporary:
            temporary_path = Path(temporary.name)
            size = 0
            while chunk := file.file.read(settings.ingest_chunk_size_bytes):
                size += len(chunk)
                if size > settings.max_file_size_bytes:
                    raise FileTooLargeError(
                        f"Datei überschreitet das Limit von {settings.max_file_size_bytes} Bytes"
                    )
                temporary.write(chunk)
        return pipeline.ingest(temporary_path, "api", safe_name)
    except DocumentRejectedError as exc:
        raise HTTPException(status_code=exc.status_code, detail=str(exc)) from exc
    finally:
        if temporary_path is not None:
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


@app.get("/v1/jobs/{job_id}/events", response_model=list[JobEvent])
def get_job_events(job_id: str) -> list[JobEvent]:
    if store.get(job_id) is None:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    return store.list_events(job_id)


@app.get("/v1/jobs/{job_id}/content", response_class=FileResponse)
def get_job_content(job_id: str, download: bool = False) -> FileResponse:
    job = store.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    path = job.stored_path.resolve()
    work_root = settings.work_root_dir.resolve()
    if work_root not in path.parents or not path.is_file():
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
    store.save_event(
        JobEvent(
            job_id=retried.id,
            event_type="manual_retry",
            status=JobStatus.RECEIVED.value,
            message="Manueller Retry wurde eingeplant",
        )
    )
    return retried


@app.delete("/v1/jobs/{job_id}", status_code=204)
def delete_job(job_id: str) -> Response:
    existing = store.get(job_id)
    if existing is None:
        raise HTTPException(status_code=404, detail="Job nicht gefunden")
    deleted = store.delete_stalled_job(job_id)
    if deleted is None:
        raise HTTPException(
            status_code=409,
            detail="Nur Jobs in Verarbeitung, manueller Prüfung oder mit Fehler können gelöscht werden",
        )
    stored_path = deleted.stored_path.resolve()
    work_root = settings.work_root_dir.resolve()
    if work_root in stored_path.parents:
        stored_path.unlink(missing_ok=True)
    quarantine_path = settings.quarantine_dir / f"{deleted.id}-{deleted.original_filename}"
    quarantine_path.unlink(missing_ok=True)
    return Response(status_code=204)
