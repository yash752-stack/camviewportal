"""The Excel validation check.

Runs before (or without) an ingest and answers two questions about an alert
export: is the data fit to report on, and what will the portal make of it?

Findings come in three levels:
  error  the portal cannot read part of the file correctly (missing columns,
         rows it has to drop, times it cannot place)
  warn   the file reads, but a number built on it may mislead (an exam window
         the trunk data disagrees with, an alarm label that contradicts its
         channel, duplicate Alarm IDs)
  info   facts worth knowing (new alarm types, alerts outside the exam window)

The numbers section is exactly what the Alert Stats view would show for the
file, computed by exam_rules, so a reviewer can check the portal's reading
against the raw sheet line by line.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import openpyxl

from . import exam_rules as X
from .ingest.excel import HEADER_ALIASES, REQUIRED, SchemaError, _build_column_map, _norm, read_workbook
from .registry import get_registry

IST = timezone(timedelta(hours=5, minutes=30))
CLOCK_TOLERANCE_MIN = 2   # sheet time vs the time inside the Alarm ID

# Where each model's camera is expected to sit. An alert from elsewhere is not
# wrong, but it is unusual enough to show (often a camera mislabelled on site).
EXPECTED_ZONES = {
    "ZI": {"ENTRY EXIT"}, "CD": {"CONTROL ROOM", "ENTRY EXIT"}, "NP": {"CONTROL ROOM"},
    "TP": {"CONTROL ROOM", "STRONG ROOM"}, "TO": {"CONTROL ROOM", "STRONG ROOM"},
    "TT": {"CONTROL ROOM", "STRONG ROOM"},
    "INM": {"CLASS ROOM"}, "CHT": {"CLASS ROOM"}, "MPS": {"CLASS ROOM"}, "FOP": {"CLASS ROOM"},
}
_EX = 5


def _finding(level, check, text, count=0, examples=None):
    return {"level": level, "check": check, "text": text, "count": count, "examples": (examples or [])[:_EX]}


def _epoch_time(alarm_id: str) -> datetime | None:
    parts = alarm_id.split("-")
    if len(parts) >= 5 and parts[3].isdigit() and len(parts[3]) >= 12:
        return datetime.fromtimestamp(int(parts[3]) / 1000, IST).replace(tzinfo=None)
    return None


def _sheet_scan(path: Path) -> tuple[list[dict], int]:
    """Count data rows per sheet straight from the workbook, so rows the reader
    skips (no Alarm ID or no centre code) can be reported rather than vanish."""
    out, blank = [], 0
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        for ws in wb.worksheets:
            rows = ws.iter_rows(values_only=True)
            try:
                header = next(rows)
            except StopIteration:
                continue
            info = {"sheet": ws.title, "rows": 0, "skipped": 0, "error": "", "headers": [_norm(h) for h in header if _norm(h)]}
            try:
                cols = _build_column_map(header)
            except SchemaError as e:
                info["error"] = str(e)
                out.append(info)
                continue
            for row in rows:
                if not any(_norm(c) for c in row):
                    blank += 1
                    continue
                info["rows"] += 1
                aid = _norm(row[cols["alarm_id"]]) if cols["alarm_id"] < len(row) else ""
                cc = _norm(row[cols["centre_code"]]) if cols["centre_code"] < len(row) else ""
                if not aid or not cc:
                    info["skipped"] += 1
            out.append(info)
    finally:
        wb.close()
    return out, blank


def validate_workbook(paths, code: str | None = None) -> dict:
    if isinstance(paths, (str, Path)):
        paths = [paths]
    paths = [Path(p) for p in paths]
    reg = get_registry()
    F: list[dict] = []

    # ── 1 · can every sheet be read? ────────────────────────────────────────
    sheets = []
    for p in paths:
        try:
            sc, _ = _sheet_scan(p)
        except Exception as e:  # noqa: BLE001
            F.append(_finding("error", "file", f"{p.name}: the file could not be opened as an Excel workbook ({e})."))
            continue
        for s in sc:
            s["file"] = p.name
            sheets.append(s)
            if s["error"]:
                F.append(_finding("error", "columns",
                                  f"{p.name} / {s['sheet']}: {s['error']}. Every row of this sheet is ignored. "
                                  f"Accepted spellings: " + "; ".join(f"{k}: {', '.join(HEADER_ALIASES[k])}" for k in REQUIRED)))
            elif s["skipped"]:
                F.append(_finding("error", "dropped_rows",
                                  f"{p.name} / {s['sheet']}: {s['skipped']} row(s) have no Alarm ID or no centre code "
                                  f"and are left out of every count.", s["skipped"]))
    good = [p for p in paths if not any(s["error"] for s in sheets if s["file"] == p.name)]
    raw = []
    for p in good:
        try:
            raw.extend(read_workbook(p))
        except SchemaError:
            pass   # already reported per sheet
    if not raw:
        F.append(_finding("error", "empty", "No readable alert rows were found."))
        return {"ok": False, "files": [p.name for p in paths], "sheets": sheets, "rows": 0,
                "findings": F, "numbers": None}

    # ── 2 · row-level checks ────────────────────────────────────────────────
    seen: Counter = Counter(a.alarm_id for a in raw)
    dupes = {k: v for k, v in seen.items() if v > 1}
    if dupes:
        F.append(_finding("warn", "duplicates",
                          f"{sum(v - 1 for v in dupes.values())} repeated row(s) across {len(dupes)} Alarm ID(s). "
                          f"Each Alarm ID is counted once.", sum(v - 1 for v in dupes.values()),
                          [f"{k} × {v}" for k, v in list(dupes.items())]))
    uniq, done = [], set()
    for a in raw:
        if a.alarm_id in done:
            continue
        done.add(a.alarm_id)
        uniq.append(a)

    no_time = [a for a in uniq if a.timestamp is None]
    if no_time:
        recover = [a for a in no_time if _epoch_time(a.alarm_id)]
        F.append(_finding("error" if len(recover) < len(no_time) else "warn", "timestamps",
                          f"{len(no_time)} row(s) have a timestamp the portal cannot read "
                          f"({len(recover)} can be recovered from the time inside the Alarm ID). "
                          f"Accepted forms: 14/6/2026, 10:00:15 am or 3/6/2026, 16:29:59.",
                          len(no_time), [f"{a.alarm_id}: '{a.timestamp_raw}'" for a in no_time]))
    skew = []
    for a in uniq:
        e = _epoch_time(a.alarm_id)
        if a.timestamp and e and abs((a.timestamp - e).total_seconds()) > CLOCK_TOLERANCE_MIN * 60:
            skew.append(a)
    if skew:
        F.append(_finding("warn", "clock",
                          f"{len(skew)} row(s) show a sheet time more than {CLOCK_TOLERANCE_MIN} minutes away from "
                          f"the time stamped inside the Alarm ID. The sheet time is what the portal uses.",
                          len(skew), [f"{a.alarm_id}: sheet {a.timestamp:%H:%M:%S}, id {_epoch_time(a.alarm_id):%H:%M:%S}" for a in skew]))

    bad_id = [a for a in uniq if not a.channel]
    if bad_id:
        F.append(_finding("warn", "alarm_id",
                          f"{len(bad_id)} Alarm ID(s) are not in the C-centre-channel-time-seq form, so the model is "
                          f"read from the alarm-type text only.", len(bad_id), [a.alarm_id for a in bad_id]))

    clash, unknown = Counter(), Counter()
    for a in uniq:
        by_ch = reg.by_channel(a.channel) if a.channel else None
        by_lb = reg.by_label(a.alarm_type)
        if by_ch and by_lb and by_ch.code != by_lb.code:
            clash[(a.channel, a.alarm_type, by_ch.display_label)] += 1
        if not by_ch and not by_lb:
            unknown[(a.channel or "?", a.alarm_type)] += 1
    for (ch, lab, used), n in clash.items():
        F.append(_finding("warn", "label_vs_channel",
                          f"{n} alert(s) say '{lab}' but their Alarm ID carries channel {ch}, which is {used}. "
                          f"The channel wins.", n))
    for (ch, lab), n in unknown.items():
        F.append(_finding("info", "new_type",
                          f"'{lab}' (channel {ch}, {n} alert(s)) is not in the catalogue. It is adopted as a "
                          f"generic Medium-severity model, watched all day, until it gets a proper entry.", n))

    recs = X.from_raw(uniq, reg)
    off_zone = Counter()
    for r in recs:
        exp = EXPECTED_ZONES.get(r.code)
        if exp and r.zone and r.zone not in exp:
            off_zone[(r.label, X._pretty_zone(r.zone))] += 1
    for (lab, z), n in off_zone.items():
        F.append(_finding("info", "location", f"{n} {lab} alert(s) came from a {z} camera, where this model is "
                                               f"not usually placed. Worth checking the camera's sub-location tag.", n))

    for fld, name in (("camera", "camera name"), ("zone", "camera sub-location"), ("district", "district")):
        miss = [r for r in recs if not getattr(r, fld)]
        if miss:
            F.append(_finding("warn", f"missing_{fld}",
                              f"{len(miss)} alert(s) have no {name}. "
                              + ("Priority then groups them by sub-location instead of by camera."
                                 if fld == "camera" else "They are shown as 'Unknown'."),
                              len(miss), [r.alarm_id for r in miss]))
    names, dists = defaultdict(set), defaultdict(set)
    for a in uniq:
        if a.centre_name:
            names[a.centre_code].add(a.centre_name.strip().upper())
        if a.district:
            dists[a.centre_code].add(a.district.strip().upper())
    multi = {c: v for c, v in names.items() if len(v) > 1}
    if multi:
        F.append(_finding("warn", "centre_names", f"{len(multi)} centre code(s) carry more than one centre name. "
                                                 f"The first one seen is used.", len(multi),
                          [f"{c}: {' / '.join(sorted(v))}" for c, v in multi.items()]))
    multid = {c: v for c, v in dists.items() if len(v) > 1}
    if multid:
        F.append(_finding("warn", "centre_districts", f"{len(multid)} centre code(s) appear under more than one "
                                                     f"district, which splits them on the map.", len(multid),
                          [f"{c}: {' / '.join(sorted(v))}" for c, v in multid.items()]))

    # ── 3 · exam-day checks ─────────────────────────────────────────────────
    windows = X.windows_for(code, recs)
    for w in windows:
        if w.source == "density":
            F.append(_finding("warn", "no_inm",
                              f"{w.date:%d %b}: no Invigilator Not Moving alerts, so the exam window "
                              f"({w.label()}) was guessed from overall alert density. Set it by hand."))
    an = X.analyse(recs, windows)            # assigns shift and phase to every record
    for c in X.window_checks(recs, windows):
        F.append(_finding("warn", "window_vs_trunk", c["text"]))
    for b in an["analysis"]:
        off = sum(b["off_hours"])
        if b["stage"] == "during" and off:
            F.append(_finding("info", "off_hours", f"{off} {b['label']} alert(s) fell outside the exam window and "
                                                   f"are reported as off-hours, not counted with the exam.", off))
    timetable = None
    if code:
        from .compliance import get_shifts
        timetable = lambda d: get_shifts(code, d)  # noqa: E731
    trunk_rows = X.trunk_compliance(recs, windows, timetable)
    nos = Counter((t["shift"], k) for t in trunk_rows for k in ("arrival", "opening") if t[k]["status"] == "none")
    for (sh, k), n in sorted(nos.items()):
        F.append(_finding("info", "trunk_missing",
                          f"Shift {sh}: {n} centre(s) have no trunk {'placement' if k == 'arrival' else 'opening'} on camera."
                          , n))

    order = {"error": 0, "warn": 1, "info": 2}
    F.sort(key=lambda f: order[f["level"]])
    trunk_tally = Counter((k, t[k]["status"]) for t in trunk_rows for k in ("arrival", "opening"))
    numbers = {
        "rows": len(raw), "alerts": len(recs), "centres": an["centres"],
        "dates": sorted({r.day.isoformat() for r in recs}),
        "windows": an["windows"], "summary": an["summary"], "features": an["features"],
        "priority": an["priority"]["alerts"], "priority_rule": an["priority"]["rule"],
        "trunk": {f"{k}_{s}": n for (k, s), n in trunk_tally.items()},
        "unusual": [{"label": u["label"], "high": [x["name"] for x in u["rows"] if x["flag"] == "high"],
                     "low": [x["name"] for x in u["rows"] if x["flag"] == "low"]} for u in an["unusual"]],
        "by_model": [{"label": b["label"], "stage": b["stage"], "counted": b["counted"],
                      "off_hours": b["off_hours"]} for b in an["analysis"]],
    }
    return {"ok": not any(f["level"] == "error" for f in F), "files": [p.name for p in paths],
            "sheets": sheets, "rows": len(raw), "findings": F, "numbers": numbers,
            "counts": dict(Counter(f["level"] for f in F))}


def as_text(res: dict) -> str:
    """A plain-text rendering for the command line and for e-mail."""
    L = [f"Files: {', '.join(res['files'])}", f"Rows read: {res['rows']}", ""]
    tag = {"error": "ERROR", "warn": "WARN ", "info": "info "}
    L.append("FINDINGS")
    if not res["findings"]:
        L.append("  none — the file reads cleanly")
    for f in res["findings"]:
        L.append(f"  [{tag[f['level']]}] {f['text']}")
        for e in f["examples"]:
            L.append(f"           e.g. {e}")
    n = res.get("numbers")
    if n:
        L += ["", "HOW THE PORTAL READS IT", f"  {n['alerts']} alerts · {n['centres']} centres · {', '.join(n['dates'])}"]
        for w in n["windows"]:
            L.append(f"  {w['date']} {w['name']}: exam window {w['label']} ({w['source']})")
        for s in n["summary"]:
            L.append(f"  Shift {s['shift']}: {s['total']} alerts ({s['pre']} before the exam, {s['exam']} during, "
                     f"{s['post']} after) · {s['cameras']} cameras · busiest {s['peak_slot']} ({s['peak_n']})")
        L.append(f"  Priority ({n['priority_rule']}):")
        for sh, c in n["priority"].items():
            L.append(f"    Shift {sh}: " + ", ".join(f"{k} {c.get(k, 0)}" for k in X.PRIORITIES))
        L.append("  Exam-window alerts by type (Shift 1 → Shift 2, swing):")
        for f in n["features"]:
            sw = "new" if f["swing"] is None else f"{f['swing']:+d}%"
            L.append(f"    {f['label']:<30} {' → '.join(map(str, f['alerts']))}  {sw}")
        if n["trunk"]:
            L.append("  Trunk: " + ", ".join(f"{k} {v}" for k, v in sorted(n["trunk"].items())))
        for u in n["unusual"]:
            if u["high"] or u["low"]:
                L.append(f"  Unusual {u['label']}: high {', '.join(u['high']) or '—'}; low {', '.join(u['low']) or '—'}")
    return "\n".join(L)
