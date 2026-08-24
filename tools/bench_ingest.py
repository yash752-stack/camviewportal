"""Time an ingest end to end, stage by stage, against a throwaway database.

    python tools/bench_ingest.py --alerts 50000 --frames 20000

Reports wall time and peak memory for each stage, so an optimisation can be
shown to have worked rather than asserted. Always runs against a fresh SQLite
file in tools/_bench so it never touches real data.
"""
from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
import tracemalloc
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BENCH = ROOT / "tools" / "_bench"
LOAD = ROOT / "tools" / "_load"

# point the app at a scratch data dir BEFORE anything imports settings
BENCH.mkdir(parents=True, exist_ok=True)
os.environ["CAMVIEW_DATA_DIR"] = str(BENCH)
sys.path.insert(0, str(ROOT / "backend"))


class Stage:
    """Times a block.

    Memory is measured only when --mem is passed, and never in the same run as a
    timing: tracemalloc traces every allocation and inflates wall time roughly
    fivefold, which silently corrupts any before/after comparison.
    """
    rows: list[tuple[str, float, float]] = []
    MEM = False

    def __init__(self, label: str):
        self.label = label

    def __enter__(self):
        if Stage.MEM:
            tracemalloc.start()
        self.t = time.perf_counter()
        return self

    def __exit__(self, *exc):
        dt = time.perf_counter() - self.t
        peak = 0.0
        if Stage.MEM:
            _, p = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            peak = p / 1048576
        Stage.rows.append((self.label, dt, peak))
        tail = f"   peak {peak:7.1f} MB" if Stage.MEM else ""
        print(f"  {self.label:<34} {dt:8.2f}s{tail}")
        return False


def best(label: str, fn, repeat: int):
    """Run fn `repeat` times and keep the fastest.

    This machine is noisy — the same parse measured 6.5s, 10.9s and 14.8s on
    consecutive runs with background work competing for it. The minimum is the
    robust estimator here: interference can only ever make a run slower, never
    faster, so the fastest observation is the closest to the true cost.
    """
    times, out = [], None
    for _ in range(repeat):
        if Stage.MEM:
            tracemalloc.start()
        t = time.perf_counter()
        out = fn()
        times.append(time.perf_counter() - t)
        if Stage.MEM:
            _, pk = tracemalloc.get_traced_memory()
            tracemalloc.stop()
            Stage.rows.append((label, min(times), pk / 1048576))
    lo, hi = min(times), max(times)
    spread = f"  (worst {hi:.2f}s)" if hi > lo * 1.15 else ""
    mem = ""
    if Stage.MEM:
        mem = f"   peak {Stage.rows[-1][2]:7.1f} MB"
    print(f"  {label:<34} {lo:8.2f}s{mem}{spread}")
    if not Stage.MEM:
        Stage.rows.append((label, lo, 0.0))
    return out


def main(alerts: int, frames: int, repeat: int) -> None:
    db = BENCH / "camview.db"

    xl = LOAD / f"alerts_{alerts}.xlsx"
    ev = LOAD / f"evidence_{frames}"
    if not xl.exists():
        sys.exit(f"missing {xl} — run tools/make_load.py first")

    from app.db import SessionLocal, init_db, engine
    from app.ingest.evidence import EvidenceIndex
    from app.ingest.excel import read_workbook
    from app.ingest.pipeline import ingest_exam

    print()
    print(f"  {alerts:,} alerts · {frames:,} frames · {engine.dialect.name} · best of {repeat}")
    print()

    def fresh():
        # the engine keeps the SQLite file open; dispose before unlinking or
        # Windows refuses the delete
        engine.dispose()
        for p in (db, BENCH / "camview.db-wal", BENCH / "camview.db-shm"):
            try:
                p.unlink(missing_ok=True)
            except PermissionError:
                pass
        init_db()

    best("init_db", fresh, repeat)
    n = best("read_workbook (parse only)", lambda: sum(1 for _ in read_workbook(xl)), repeat)
    print(f"  {'':<34} {n:,} rows parsed")

    idx = best("EvidenceIndex scan", lambda: EvidenceIndex(ev), repeat)
    print(f"  {'':<34} {idx.image_count:,} frames indexed")

    def one_ingest():
        fresh()
        se = SessionLocal()
        try:
            return ingest_exam(se, code="BENCH", name="Benchmark", session_label="S1",
                               exam_date=None, excel_path=xl, evidence_root=ev)
        finally:
            se.close()

    res = best("ingest_exam (full)", one_ingest, repeat)
    print(f"  {'':<34} {res.alert_count:,} alerts, {res.evidence_linked:,} linked")

    ing = [r[1] for r in Stage.rows if r[0].startswith("ingest_exam")][0]
    size = db.stat().st_size / 1048576 if db.exists() else 0
    print()
    print(f"  {'ingest wall time':<34} {ing:8.2f}s")
    print(f"  {'database on disk':<34} {size:8.1f} MB")
    print(f"  {'throughput':<34} {res.alert_count / max(ing, 1e-9):8.0f} alerts/s")
    print()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--alerts", type=int, default=50_000)
    ap.add_argument("--frames", type=int, default=20_000)
    ap.add_argument("--repeat", type=int, default=3)
    ap.add_argument("--mem", action="store_true",
                    help="measure peak allocation; inflates wall time ~5x, never mix with timings")
    a = ap.parse_args()
    ap_repeat = a.repeat
    Stage.MEM = a.mem
    main(a.alerts, a.frames, ap_repeat)
