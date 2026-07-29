"""Database engine and session factory.

SQLite on a workstation, Postgres on AWS. The only difference is the URL returned
by settings.resolved_database_url, so nothing downstream is engine-specific.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import get_settings

_settings = get_settings()
_url = _settings.resolved_database_url
_connect_args = {"check_same_thread": False} if _url.startswith("sqlite") else {}

engine = create_engine(_url, connect_args=_connect_args, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False, future=True)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    from . import models  # noqa: F401  (register mappers before create_all)
    Base.metadata.create_all(engine)
    # lightweight additive migrations for existing SQLite DBs (create_all does not
    # alter existing tables) — add columns when missing, ignore if already there.
    if engine.dialect.name == "sqlite":
        from sqlalchemy import text
        with engine.begin() as conn:
            cols = {r[1] for r in conn.execute(text("PRAGMA table_info(exams)"))}
            if "centre_total" not in cols:
                conn.execute(text("ALTER TABLE exams ADD COLUMN centre_total INTEGER DEFAULT 0"))
            # hard backstop against inflated statistics: an Alarm ID can appear at
            # most once per exam, guaranteed by the DB regardless of code path.
            # Safe to create only when no existing rows already violate it.
            has_dupes = conn.execute(text(
                "SELECT 1 FROM (SELECT exam_id, alarm_id FROM alerts "
                "GROUP BY exam_id, alarm_id HAVING COUNT(*) > 1) LIMIT 1")).first()
            if not has_dupes:
                conn.execute(text(
                    "CREATE UNIQUE INDEX IF NOT EXISTS ux_alerts_exam_alarm "
                    "ON alerts (exam_id, alarm_id)"))


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
