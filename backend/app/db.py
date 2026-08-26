"""Database engine and session factory.

SQLite on a workstation, Postgres on AWS. The only difference is the URL returned
by settings.resolved_database_url, so nothing downstream is engine-specific.
"""
from __future__ import annotations

import logging

from collections.abc import Iterator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import get_settings

_settings = get_settings()
_url = _settings.resolved_database_url
_is_sqlite = _url.startswith("sqlite")


def _postgres_connect_args() -> dict:
    """Connection options a managed Postgres needs and a local file does not.

    Each of these is a failure mode that only appears once the database is on
    the other side of a network:

    sslmode        RDS accepts unencrypted connections unless the parameter
                   group forbids it. Exam data should not cross a VPC in
                   clear text because nobody remembered to set this.
    connect_timeout  Without it, a failover or a wrong security group leaves
                   the worker blocked on connect() until the OS gives up,
                   which is minutes. Ten seconds then a clean error is better.
    keepalives     NAT gateways and load balancers silently drop idle TCP
                   sessions. pool_pre_ping recovers from that, but only after
                   paying a failed round trip; keepalives stop it happening.
    statement_timeout  One pathological report query can otherwise hold a
                   connection open indefinitely and starve the pool.
    application_name  So `pg_stat_activity` names this app rather than
                   showing an anonymous psycopg connection during an incident.
    """
    return {
        "sslmode": _settings.db_sslmode,
        "connect_timeout": 10,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
        "application_name": "camview-portal",
        "options": f"-c statement_timeout={_settings.db_statement_timeout_ms}",
    }


engine = create_engine(
    _url,
    future=True,
    pool_pre_ping=True,
    connect_args=({"check_same_thread": False} if _is_sqlite else _postgres_connect_args()),
    # SQLite ignores pooling; on Postgres this keeps a small warm pool rather
    # than reconnecting per request. pool_size is PER WORKER PROCESS, so the
    # ceiling on RDS is (workers x (pool_size + max_overflow)) — keep that under
    # the instance max_connections, which is max(LEAST(DBInstanceClassMemory/
    # 9531392, 5000), 5) and is only about 80 on a db.t4g.micro.
    **({} if _is_sqlite else {
        "pool_size": _settings.db_pool_size,
        "max_overflow": _settings.db_max_overflow,
        # Below RDS's idle_session_timeout and any NLB idle timeout, so the pool
        # retires a connection before the network does it for us.
        "pool_recycle": 900,
        "pool_timeout": 30,
    }),
)


@event.listens_for(engine, "connect")
def _sqlite_pragmas(dbapi_conn, _record):
    """WAL + relaxed sync. Default SQLite journalling blocks every reader for
    the duration of a write, which on a single shared core turns one ingest
    into a stalled portal. WAL lets readers run straight through a write, and
    NORMAL sync trades an fsync per commit for throughput -- acceptable here
    because the durable record is the uploaded workbook, not the database."""
    if not _is_sqlite:
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
    _apply_additive_migrations()


def _apply_additive_migrations() -> None:
    """Bring an existing database up to the current schema.

    create_all() creates missing tables but never alters existing ones, so a
    database written by an older build needs its new columns and indexes added
    by hand. This whole step used to be wrapped in `if dialect == "sqlite"`,
    which meant the uniqueness index below — the only thing standing between a
    repeated ingest and double-counted statistics — silently did not exist on
    Postgres. The checks are expressed through the Inspector and portable DDL
    so both engines end up with the same schema.
    """
    from sqlalchemy import Index, inspect, text

    from .models import Alert

    insp = inspect(engine)

    # ALTER TABLE ... ADD COLUMN with a constant default is understood by both
    # engines and rewrites nothing.
    existing = {c["name"] for c in insp.get_columns("exams")}
    additions = (("centre_total", "INTEGER DEFAULT 0"),
                 ("body", "VARCHAR(128) DEFAULT ''"))
    with engine.begin() as conn:
        for name, ddl in additions:
            if name not in existing:
                conn.execute(text(f"ALTER TABLE exams ADD COLUMN {name} {ddl}"))

    # Indexes declared on a model reach an EXISTING table through nobody:
    # create_all() creates missing tables and their indexes, but adds nothing to a
    # table that is already there. So a new index is silently absent on every
    # database that predates it — including, on the first deploy after a restore,
    # production. Create whatever the models declare and the database lacks.
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        present = {i["name"] for i in insp.get_indexes(table.name)}
        for index in table.indexes:
            if index.name not in present:
                with engine.begin() as conn:
                    index.create(conn)
                logging.getLogger("camview.db").info("created index %s", index.name)

    # Drop indexes the models no longer declare but only when a declared index
    # contains them as a leading prefix, i.e. the planner has a strictly better
    # one available. Anything else is left alone: an unexplained index is more
    # likely to be someone else's deliberate work than dead weight.
    for table in Base.metadata.sorted_tables:
        if not insp.has_table(table.name):
            continue
        declared = {tuple(c.name for c in i.columns): i.name for i in table.indexes}
        for existing in insp.get_indexes(table.name):
            name, cols = existing["name"], tuple(existing["column_names"])
            if name in declared.values() or existing.get("unique") or not name.startswith("ix_"):
                continue
            covered = any(dc[:len(cols)] == cols and dc != cols for dc in declared)
            if covered:
                with engine.begin() as conn:
                    conn.execute(text(f"DROP INDEX IF EXISTS {name}"))
                logging.getLogger("camview.db").info(
                    "dropped index %s, superseded by a wider one", name)

    # Hard backstop against inflated statistics: an Alarm ID may appear at most
    # once per exam, enforced by the database whatever the code path does. It can
    # only be added when no existing row already violates it, which on a fresh
    # RDS instance is trivially true.
    if "ux_alerts_exam_alarm" in {i["name"] for i in insp.get_indexes("alerts")}:
        return
    with engine.begin() as conn:
        # The derived table needs an alias: SQLite tolerates it missing,
        # Postgres rejects the statement outright.
        dupes = conn.execute(text(
            "SELECT 1 FROM (SELECT exam_id, alarm_id FROM alerts "
            "GROUP BY exam_id, alarm_id HAVING COUNT(*) > 1) d LIMIT 1")).first()
        if dupes:
            logging.getLogger("camview.db").warning(
                "alerts already contains duplicate (exam_id, alarm_id) rows, so the "
                "uniqueness index was not created. Statistics may be inflated until "
                "the duplicates are removed.")
            return
        Index("ux_alerts_exam_alarm", Alert.__table__.c.exam_id,
              Alert.__table__.c.alarm_id, unique=True).create(conn)


def get_session() -> Iterator[Session]:
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
