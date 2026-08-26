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

    # Postgres/RDS connection tuning. Ignored entirely when the URL is SQLite.
    # pool_size and max_overflow are PER WORKER PROCESS: the real ceiling on the
    # instance is workers x (pool_size + max_overflow), which must stay below the
    # RDS max_connections (~80 on a db.t4g.micro). Four workers at these defaults
    # is 60 — deliberately close, so raising either needs a matching instance.
    db_pool_size: int = Field(default=5)
    db_max_overflow: int = Field(default=10)
    # "require" encrypts without verifying the server certificate; "verify-full"
    # is correct once the RDS CA bundle is on the instance and PGSSLROOTCERT
    # points at it. Never lower this to "disable" on a hosted database.
    db_sslmode: str = Field(default="require")
    # Ceiling on any single statement. A report over a very large exam is the
    # only thing here that comes close; if one legitimately needs longer, raise
    # this rather than removing it, so a runaway query still cannot pin a
    # connection for the life of the process.
    db_statement_timeout_ms: int = Field(default=30000)
    # NOT IMPLEMENTED: nothing reads storage_backend / s3_bucket / s3_region.
    # There is no boto3 dependency and no S3 code path, so setting these has no
    # effect and the evidence vault stays on CAMVIEW_DATA_DIR. Kept as the shape
    # of the intended interface, not as a working switch.
    storage_backend: str = Field(default="local", description="local | s3 (s3 NOT implemented)")
    s3_bucket: str = Field(default="")
    s3_region: str = Field(default="ap-south-1")

    # Canonical modality registry (bounded CamView model set).
    modalities_path: Path = Field(default=PROJECT_ROOT / "config" / "modalities.json")

    # Branding assets surfaced to templates.
    assets_dir: Path = Field(default=PROJECT_ROOT / "assets")

    # Optional: Google Maps platform key. When unset, centre imagery falls back
    # to the exam's own evidence frames and no external request is ever made.
    google_maps_key: str = Field(default="", description="CAMVIEW_GOOGLE_MAPS_KEY")

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
