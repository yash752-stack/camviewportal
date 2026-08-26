"""Copy the local SQLite database into Postgres (RDS).

Run once, when the portal moves from a workstation file to a managed database.
It refuses to touch a target that already holds rows unless --replace is given.

    python tools/migrate_to_postgres.py --target postgresql+psycopg://camview:PW@host:5432/camview
    python tools/migrate_to_postgres.py --target ... --dry-run
    python tools/migrate_to_postgres.py --target ... --replace

The source is whatever CAMVIEW_DATA_DIR points at, i.e. the same database the
portal itself uses, so there is no way to migrate the wrong file by accident.

Three things here are the reason this is a script and not a pg_dump one-liner:

  * pg_dump cannot read SQLite, and `.dump | psql` emits SQL Postgres rejects
    (AUTOINCREMENT, type affinity, quoting). Going through the ORM means the
    target schema is the one the models declare, which is the schema the
    application actually expects to find.

  * Rows are copied with their existing primary keys so foreign keys survive.
    That leaves every Postgres identity sequence sitting at 1, and the app's
    next INSERT then fails on a duplicate key. Resetting the sequences is
    mandatory, and skipping it is the single most common way this migration
    looks like it worked and then breaks on the first write.

  * SQLite hands back a str for a DateTime column whenever the value was written
    by something other than SQLAlchemy. Postgres will not accept that, so
    timestamps are coerced on the way through.
"""
from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import create_engine, func, inspect, select, text  # noqa: E402

BATCH = 5000


def _coerce(value, column):
    """SQLite type affinity is advisory. Postgres's is not."""
    import sqlalchemy as sa

    if value is None:
        return None
    t = column.type
    if isinstance(t, sa.DateTime) and isinstance(value, str):
        v = value.strip()
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
            try:
                return dt.datetime.strptime(v, fmt)
            except ValueError:
                continue
        return None
    if isinstance(t, sa.Boolean) and isinstance(value, int):
        return bool(value)
    if isinstance(t, sa.Integer) and isinstance(value, bool):
        return int(value)
    return value


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--target", required=True,
                    help="postgresql+psycopg://user:pw@host:5432/db")
    ap.add_argument("--dry-run", action="store_true",
                    help="report what would move, write nothing")
    ap.add_argument("--replace", action="store_true",
                    help="DELETE existing target rows first")
    a = ap.parse_args()

    if not a.target.startswith("postgresql"):
        print("--target must be a postgresql:// URL")
        return 2

    from app.db import Base, engine as src_engine
    from app import models  # noqa: F401  (register mappers before create_all)

    if src_engine.dialect.name != "sqlite":
        print(f"source is {src_engine.dialect.name}, not sqlite -- unset "
              f"CAMVIEW_DATABASE_URL so the source resolves to the local file")
        return 2

    print(f"source : {src_engine.url}")
    print(f"target : {a.target.split('@')[-1]}")

    tgt_engine = create_engine(a.target, future=True, pool_pre_ping=True)
    try:
        with tgt_engine.connect() as c:
            ver = c.execute(text("SHOW server_version")).scalar()
        print(f"connected to Postgres {ver}")
    except Exception as exc:                                    # noqa: BLE001
        print(f"cannot reach target: {type(exc).__name__}: {exc}")
        return 1

    tables = Base.metadata.sorted_tables                        # FK-safe order
    src_insp = inspect(src_engine)
    Base.metadata.create_all(tgt_engine)

    # ---- survey -----------------------------------------------------------
    print()
    print(f"  {'table':20} {'source':>10} {'target':>10}")
    counts = {}
    with src_engine.connect() as sc, tgt_engine.connect() as tc:
        for t in tables:
            n_src = (sc.execute(select(func.count()).select_from(t)).scalar()
                     if src_insp.has_table(t.name) else 0)
            n_tgt = tc.execute(select(func.count()).select_from(t)).scalar()
            counts[t.name] = (n_src, n_tgt)
            print(f"  {t.name:20} {n_src:>10,} {n_tgt:>10,}")

    occupied = [n for n, (_, tg) in counts.items() if tg]
    if occupied and not a.replace:
        print()
        print(f"target already holds rows in: {', '.join(occupied)}")
        print("re-run with --replace to overwrite, or point at an empty database")
        return 1

    if a.dry_run:
        print()
        print(f"dry run: would copy {sum(s for s, _ in counts.values()):,} rows")
        return 0

    # ---- copy -------------------------------------------------------------
    print()
    if a.replace:
        with tgt_engine.begin() as tc:
            for t in reversed(tables):                          # children first
                tc.execute(t.delete())
        print("  cleared target")

    moved = 0
    with src_engine.connect() as sc:
        for t in tables:
            if not src_insp.has_table(t.name):
                continue
            cols = list(t.columns)
            batch, n = [], 0
            with tgt_engine.begin() as tc:
                for row in sc.execute(select(t)).mappings():
                    batch.append({c.name: _coerce(row.get(c.name), c) for c in cols})
                    if len(batch) >= BATCH:
                        tc.execute(t.insert(), batch)
                        n += len(batch)
                        batch = []
                if batch:
                    tc.execute(t.insert(), batch)
                    n += len(batch)
            moved += n
            print(f"  copied {t.name:20} {n:>10,}")

    # ---- sequences --------------------------------------------------------
    # Rows kept their original ids, so every identity sequence is still at 1 and
    # the app's next INSERT would collide. This is the step that makes the
    # migration usable rather than merely complete.
    print()
    with tgt_engine.begin() as tc:
        for t in tables:
            for c in t.primary_key.columns:
                if c.autoincrement is False:
                    continue
                seq = tc.execute(
                    text("SELECT pg_get_serial_sequence(:t, :c)"),
                    {"t": t.name, "c": c.name}).scalar()
                if not seq:
                    continue
                nxt = tc.execute(
                    text(f"SELECT setval(:s, COALESCE((SELECT MAX({c.name}) "
                         f"FROM {t.name}), 1))"),
                    {"s": seq}).scalar()
                print(f"  sequence {seq.split('.')[-1]:32} -> {nxt:,}")

    # ---- verify -----------------------------------------------------------
    print()
    ok = True
    with src_engine.connect() as sc, tgt_engine.connect() as tc:
        for t in tables:
            if not src_insp.has_table(t.name):
                continue
            n_src = sc.execute(select(func.count()).select_from(t)).scalar()
            n_tgt = tc.execute(select(func.count()).select_from(t)).scalar()
            if n_src != n_tgt:
                ok = False
            print(f"  {'ok  ' if n_src == n_tgt else 'FAIL'} "
                  f"{t.name:20} {n_src:>10,} -> {n_tgt:>10,}")

        # A row count can match while values are mangled, so compare something
        # the application actually reads back: per-exam, per-modality totals.
        A = models.Alert.__table__
        q = (select(A.c.exam_id, A.c.modality_code, func.count())
             .group_by(A.c.exam_id, A.c.modality_code))
        s_agg = {(e, m): n for e, m, n in sc.execute(q)}
        t_agg = {(e, m): n for e, m, n in tc.execute(q)}
        if s_agg == t_agg:
            print(f"  ok   per-exam/modality totals identical ({len(s_agg)} groups)")
        else:
            ok = False
            print("  FAIL per-exam/modality totals differ")
            for k in sorted(set(s_agg) | set(t_agg)):
                if s_agg.get(k) != t_agg.get(k):
                    print(f"       {k}: source={s_agg.get(k)} target={t_agg.get(k)}")

    print()
    print(f"{moved:,} rows migrated")
    if ok:
        print()
        print("VERIFIED. Now set on the app host:")
        print(f"  CAMVIEW_DATABASE_URL={a.target}")
        print("and restart. Keep the SQLite file until the portal has served a")
        print("full report from Postgres.")
    else:
        print("VERIFICATION FAILED -- do not switch the app over")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
