from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCUMENT_CORE_", env_file=".env")

    data_dir: Path = Path("data")
    input_root_dir: Path | None = None
    work_dir: Path | None = None
    destination_root_dir: Path | None = None
    delivered_file_policy: str = Field(default="retain", pattern="^(retain|archive|delete)$")
    database_url: str = "sqlite:///data/document-core.db"
    database_auto_create: bool = True
    hotfolder_interval: float = 2.0
    worker_poll_interval: float = 1.0
    worker_lease_seconds: int = 300
    worker_max_attempts: int = 3
    worker_retry_base_seconds: int = 5
    connector: str = "filesystem"
    connector_entitlements: str = ""
    license_public_key: str = ""
    connector_secret_keys: str = ""
    connector_secret_keys_file: Path | None = None
    require_routing_reference: bool = False
    tesseract_lang: str = "deu+eng"
    ingest_chunk_size_bytes: int = Field(default=1024 * 1024, ge=4096, le=16 * 1024 * 1024)
    max_file_size_bytes: int = Field(default=25 * 1024 * 1024, ge=1)
    max_pdf_pages: int = Field(default=100, ge=1)
    max_image_pixels: int = Field(default=40_000_000, ge=1)
    ocr_timeout_seconds: int = Field(default=60, ge=1)
    malware_scanner: str = "disabled"
    clamav_host: str = "clamav"
    clamav_port: int = Field(default=3310, ge=1, le=65535)
    malware_scan_timeout_seconds: float = Field(default=30, gt=0)
    bootstrap_admin_username: str = "admin"
    bootstrap_admin_password: str | None = None
    session_ttl_hours: int = Field(default=12, ge=1, le=168)
    session_cookie_secure: bool = False
    login_max_attempts: int = Field(default=5, ge=1, le=100)
    login_window_minutes: int = Field(default=15, ge=1, le=1440)
    auth_enabled: bool = True

    @property
    def inbox_dir(self) -> Path:
        return self.work_root_dir / "inbox"

    @property
    def work_root_dir(self) -> Path:
        return self.work_dir or self.data_dir

    @property
    def input_root(self) -> Path:
        return self.input_root_dir or self.data_dir

    @property
    def destination_root(self) -> Path:
        return self.destination_root_dir or self.data_dir

    @property
    def hotfolder_dir(self) -> Path:
        return self.input_root / "hotfolder"

    @property
    def output_dir(self) -> Path:
        return self.destination_root / "output"

    @property
    def quarantine_dir(self) -> Path:
        return self.work_root_dir / "quarantine"

    @property
    def completed_dir(self) -> Path:
        return self.work_root_dir / "completed"

    @property
    def connector_secret_key_material(self) -> str:
        if self.connector_secret_keys_file:
            return self.connector_secret_keys_file.read_text(encoding="utf-8").strip()
        return self.connector_secret_keys

    def create_directories(self) -> None:
        for path in (
            self.inbox_dir,
            self.hotfolder_dir,
            self.output_dir,
            self.quarantine_dir,
            self.completed_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
