"""Database engine and session factory.

SQLite on a workstation, Postgres on AWS. The only difference is the URL returned
by settings.resolved_database_url, so nothing downstream is engine-specific.
"""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import get_settings

_settings = get_settings()
_url = _settings.resolved_database_url
_connect_args = {"check_same_thread": False} if _url.startswith("sqlite") else {}

engine = create_engine(
    _url, connect_args=_connect_args, future=True,
    pool_pre_ping=True,
    # SQLite ignores pool_size; on Postgres this keeps a small warm pool rather
    # than reconnecting per request on a latency-sensitive free instance.
    **({} if _url.startswith("sqlite") else {"pool_size": 5, "max_overflow": 10, "pool_recycle": 900}),
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    """WAL + relaxed sync. Default SQLite journalling blocks every reader for
    the duration of a write, which on a single shared core turns one ingest
    into a stalled portal. WAL lets readers run straight through a write, and
    NORMAL sync trades an fsync per commit for throughput -- acceptable here
    because the durable record is the uploaded workbook, not the database."""
    if not _url.startswith("sqlite"):
        return
    cur = dbapi_conn.cursor()
    cur.execute("PRAGMA journal_mode=WAL")
    cur.execute("PRAGMA synchronous=NORMAL")
    cur.execute("PRAGMA temp_store=MEMORY")
    cur.execute("PRAGMA mmap_size=134217728")     # 128MB, well under the 512MB cap
    cur.execute("PRAGMA cache_size=-32000")       # 32MB page cache
    cur.execute("PRAGMA busy_timeout=8000")
    cur.close()
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
            if "body" not in cols:
                conn.execute(text("ALTER TABLE exams ADD COLUMN body VARCHAR(128) DEFAULT ''"))
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
