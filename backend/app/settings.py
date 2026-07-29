"""Runtime configuration. Local-first, AWS-ready: every storage and database
location is injected here so a deployment switches backend by environment alone,
never by code change."""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parent.parent
PROJECT_ROOT = BACKEND_ROOT.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CAMVIEW_", env_file=".env", extra="ignore")

    app_name: str = "CamView Examination Security Intelligence"
    environment: str = Field(default="local", description="local | staging | production")

    # Storage. local_data_dir holds the SQLite db, uploaded workbooks and the
    # evidence vault while running on a workstation. On AWS these are replaced by
    # an RDS url and an S3 bucket without touching call sites.
    data_dir: Path = Field(default=BACKEND_ROOT / "data")
    database_url: str = Field(default="")
    storage_backend: str = Field(default="local", description="local | s3")
    s3_bucket: str = Field(default="")
    s3_region: str = Field(default="ap-south-1")

    # Canonical modality registry (bounded CamView model set).
    modalities_path: Path = Field(default=PROJECT_ROOT / "config" / "modalities.json")

    # Branding assets surfaced to templates.
    assets_dir: Path = Field(default=PROJECT_ROOT / "assets")

    # Confidence is not present in current CamView Excel exports; when absent the
    # ingest derives a deterministic stand-in and flags it as synthetic so the UI
    # never presents a fabricated score as a measured one.
    allow_synthetic_confidence: bool = Field(default=True)

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @property
    def evidence_dir(self) -> Path:
        return self.data_dir / "evidence"

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return f"sqlite:///{self.data_dir / 'camview.db'}"

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.uploads_dir, self.evidence_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    settings.ensure_dirs()
    return settings
