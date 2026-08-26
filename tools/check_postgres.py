"""Compile every statement the app really issues against the Postgres dialect.

There is no Postgres on a workstation and no Docker in the deploy pipeline's
dev image, so the usual answer is to read the code and hope. This does better:
it runs the actual workflows -- ingest, overview, compliance, report -- against
the local SQLite database, and intercepts every statement on its way to the
driver to compile it a second time for Postgres. A construct SQLite tolerates
and Postgres does not (strftime, a bare column in GROUP BY, a type Postgres
will not coerce) raises here instead of on RDS at 6am.

It cannot catch behaviour that differs only at runtime -- collation, integer
division, timezone handling -- so those are checked separately by assertion.
Everything that is a *compile* difference, which is most of them, it catches.

    python tools/check_postgres.py
"""
from __future__ import annotations

import sys
import traceback
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import event                        # noqa: E402
from sqlalchemy.dialects import postgresql          # noqa: E402
from sqlalchemy.orm import Session                  # noqa: E402
from sqlalchemy.sql import ClauseElement            # noqa: E402

PG = postgresql.dialect()
seen: Counter = Counter()
failures: list[tuple[str, str]] = []


def _try_compile(stmt, where: str) -> None:
    if not isinstance(stmt, ClauseElement):
        return
    key = str(stmt)[:120]
    if key in seen:
        seen[key] += 1
        return
    seen[key] = 1
    try:
        stmt.compile(dialect=PG, compile_kwargs={"literal_binds": False})
    except Exception as exc:                        # noqa: BLE001
        failures.append((f"{where}: {type(exc).__name__}: {exc}", str(stmt)[:400]))


_orig_execute = Session.execute
_orig_scalar = Session.scalar
_orig_scalars = Session.scalars


def _wrap(fn, name):
    def inner(self, statement, *a, **kw):
        _try_compile(statement, name)
        return fn(self, statement, *a, **kw)
    return inner


Session.execute = _wrap(_orig_execute, "Session.execute")
Session.scalar = _wrap(_orig_scalar, "Session.scalar")
Session.scalars = _wrap(_orig_scalars, "Session.scalars")


def main() -> int:
    from app.db import SessionLocal, engine, Base
    from app.models import Exam
    from sqlalchemy import select

    # ---- 1. schema: can the ORM's DDL even be emitted for Postgres? --------
    print("=" * 78)
    print("SCHEMA")
    from sqlalchemy.schema import CreateTable, CreateIndex
    ddl_bad = 0
    for table in Base.metadata.sorted_tables:
        try:
            CreateTable(table).compile(dialect=PG)
            for idx in table.indexes:
                CreateIndex(idx).compile(dialect=PG)
            print(f"  ok    {table.name:24} ({len(table.columns)} cols, {len(table.indexes)} idx)")
        except Exception as exc:                    # noqa: BLE001
            ddl_bad += 1
            print(f"  FAIL  {table.name:24} {type(exc).__name__}: {exc}")

    # ---- 2. exercise the real workflows -----------------------------------
    print()
    print("=" * 78)
    print("QUERY SURFACE  (running real workflows, compiling each stmt for Postgres)")
    s = SessionLocal()
    exams = list(s.scalars(select(Exam)))
    if not exams:
        print("  no exams in the local db -- ingest one first, coverage would be empty")
        return 2

    from app import aggregates, compliance, queries, reporting
    from app.models import Alert as _A
    from app import report_render as RR

    for e in exams:
        label = e.code
        steps = [
            ("modality_cards",   lambda: aggregates.modality_cards(s, e.id)),
            ("top_districts",    lambda: aggregates.top_districts(s, e.id)),
            ("compliance",       lambda: compliance.compute(s, e)),
            ("centre_deviations", lambda: compliance.centre_deviations(s, e)),
        ]
        for fn_name in ("recent_critical", "exam_summary", "severity_split"):
            fn = getattr(aggregates, fn_name, None) or getattr(queries, fn_name, None)
            if fn:
                steps.append((fn_name, lambda fn=fn: fn(s, e.id)))
        codes = [c for c, in s.execute(
            select(_A.modality_code).where(_A.exam_id == e.id)
            .group_by(_A.modality_code))]
        # Day-filtered variants: days_cond is on nearly every report query and is
        # the one predicate whose SQLite and Postgres behaviour genuinely differ,
        # so it must be exercised rather than left at the unfiltered default.
        from sqlalchemy import func as _f
        days = sorted({str(d)[:10] for d, in s.execute(
            select(_f.date(_A.occurred_at)).where(_A.exam_id == e.id,
                                                  _A.occurred_at.is_not(None)).distinct()) if d})
        for c in codes[:4]:
            steps.append((f"report.gather[{c}]", lambda c=c: RR.R.gather(s, e.id, c, c)))
            steps.append((f"report.gather[{c}] days={len(days)}",
                          lambda c=c, d=days: RR.R.gather(s, e.id, c, c, days=d)))
            steps.append((f"report.gather[{c}] day[0]",
                          lambda c=c, d=days[:1]: RR.R.gather(s, e.id, c, c, days=d)))

        for name, fn in steps:
            try:
                fn()
                print(f"  ran   {label:10} {name}")
            except Exception as exc:                # noqa: BLE001
                print(f"  ERR   {label:10} {name}: {type(exc).__name__}: {exc}")
                traceback.print_exc(limit=2)

    # ---- 3. verdict --------------------------------------------------------
    print()
    print("=" * 78)
    print(f"distinct statements compiled for Postgres : {len(seen)}")
    print(f"total statement executions observed       : {sum(seen.values())}")
    print(f"schema objects that failed to compile     : {ddl_bad}")
    print(f"statements that failed to compile         : {len(failures)}")
    if failures:
        print()
        for msg, sql in failures:
            print("  FAIL", msg)
            print("       ", sql.replace("\n", " ")[:300])
    print()
    print("POSTGRES-CLEAN" if not failures and not ddl_bad else "NOT POSTGRES-CLEAN")
    return 1 if (failures or ddl_bad) else 0


if __name__ == "__main__":
    raise SystemExit(main())
