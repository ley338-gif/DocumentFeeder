from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCUMENT_CORE_", env_file=".env")

    data_dir: Path = Path("data")
    database_url: str = "sqlite:///data/document-core.db"
    database_auto_create: bool = True
    hotfolder_interval: float = 2.0
    worker_poll_interval: float = 1.0
    worker_lease_seconds: int = 300
    worker_max_attempts: int = 3
    worker_retry_base_seconds: int = 5
    connector: str = "filesystem"
    require_routing_reference: bool = False
    tesseract_lang: str = "deu+eng"
    ingest_chunk_size_bytes: int = Field(default=1024 * 1024, ge=4096, le=16 * 1024 * 1024)

    @property
    def inbox_dir(self) -> Path:
        return self.data_dir / "inbox"

    @property
    def hotfolder_dir(self) -> Path:
        return self.data_dir / "hotfolder"

    @property
    def output_dir(self) -> Path:
        return self.data_dir / "output"

    @property
    def quarantine_dir(self) -> Path:
        return self.data_dir / "quarantine"

    def create_directories(self) -> None:
        for path in (
            self.inbox_dir,
            self.hotfolder_dir,
            self.output_dir,
            self.quarantine_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
