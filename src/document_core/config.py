from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="DOCUMENT_CORE_", env_file=".env")

    data_dir: Path = Path("data")
    hotfolder_interval: float = 2.0
    connector: str = "filesystem"
    require_routing_reference: bool = False
    tesseract_lang: str = "deu+eng"

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

    @property
    def jobs_dir(self) -> Path:
        return self.data_dir / "jobs"

    def create_directories(self) -> None:
        for path in (
            self.inbox_dir,
            self.hotfolder_dir,
            self.output_dir,
            self.quarantine_dir,
            self.jobs_dir,
        ):
            path.mkdir(parents=True, exist_ok=True)
