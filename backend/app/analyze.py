"""Auto-analysis of an uploaded alert Excel for the exam-creation wizard.

Reads the workbook (never persists) and infers the exam STRUCTURE the data can
prove: dates, the exam window of each shift (from when Invigilator Not Moving
starts, see exam_rules) and how many shifts ran each day. Suggested trunk windows
are set RELATIVE to the exam start (arrival 90 to 45 minutes before, opening the
last 15 minutes before), never from where the box events themselves clustered:
a window drawn from the data would make compliance circular. A shift whose trunk
openings say the INM start is late carries a `check` the wizard shows. The
operator confirms or edits everything.
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from .ingest.excel import read_workbook
from .registry import get_registry


def _hm(m: int) -> str:
    return f"{m // 60:02d}:{m % 60:02d}"


def _guess_name(filename: str) -> tuple[str, str]:
    """Best-effort exam name + code from the filename (always editable by the user)."""
    stem = filename.rsplit(".", 1)[0] if filename else ""
    head = re.split(r"CCTV|Alert\s*Report|Report", stem, flags=re.I)[0]
    year = ""
    ym = re.search(r"(20\d{2})", head)
    if ym:
        year = ym.group(1)
    alpha = re.split(r"[^A-Za-z]", head)[0] if head else ""
    name = (f"{alpha} {year}".strip()) or (stem[:40].strip(" -_")) or "New Examination"
    code = re.sub(r"[^A-Za-z0-9]+", "-", name).upper().strip("-") or "EXAM"
    return name, code


def _rows_again(paths):
    """Every row of every file once more, deduplicated by Alarm ID across files."""
    seen: set[str] = set()
    for p in paths:
        for a in read_workbook(p):
            if a.alarm_id and a.alarm_id in seen:
                continue
            if a.alarm_id:
                seen.add(a.alarm_id)
            yield a


def analyze_workbook(paths, filename: str = "") -> dict:
    """Analyse one or more alert workbooks together (multi-file exam). `paths` may
    be a single Path or a list. Alarm IDs are deduplicated across files so overlapping
    exports don't double-count."""
    if isinstance(paths, (str, Path)):
        paths = [paths]
    reg = get_registry()
    per_day: dict = defaultdict(lambda: {"all": [], "tp": [], "to": []})
    centres: set[str] = set()
    mod_counts: dict[str, int] = defaultdict(int)
    new_types: dict[str, dict] = {}   # channel -> {channel,label,count}: alarm types not in the catalogue yet
    seen: set[str] = set()
    n = 0
    for p in paths:
        for a in read_workbook(p):
            if a.alarm_id and a.alarm_id in seen:
                continue
            if a.alarm_id:
                seen.add(a.alarm_id)
            n += 1
            if a.centre_code:
                centres.add(a.centre_code)
            mod = reg.resolve(a.channel, a.alarm_type, a.zone, a.centre_code)
            if mod is None:
                # an alarm type the software has not seen before — surface it so the
                # operator decides at creation whether it needs bespoke handling.
                key = a.channel or "?"
                nt = new_types.setdefault(key, {"channel": key, "label": a.alarm_type or "", "count": 0})
                nt["count"] += 1
                if not nt["label"] and a.alarm_type:
                    nt["label"] = a.alarm_type
            if not a.timestamp:
                continue
            d = a.timestamp.date()
            t = a.timestamp.hour * 60 + a.timestamp.minute
            per_day[d]["all"].append(t)
            if mod:
                mod_counts[mod.code] += 1
                if mod.code == "TP":
                    per_day[d]["tp"].append(t)
                elif mod.code == "TO":
                    per_day[d]["to"].append(t)

    # Exam windows and the shifts they imply come from the operations-review
    # rules (exam_rules): the exam window opens with the first sustained
    # Invigilator Not Moving cluster, and the suggested trunk windows are set
    # relative to that start (arrival 90->45 min before, opening the last 15
    # min before). Everything here is a SUGGESTION the operator confirms.
    from . import exam_rules as X
    recs = X.from_raw(_rows_again(paths), reg)
    windows = X.infer_windows(recs)
    X.assign(recs, windows)
    checks = {(c["date"], c["shift"]): c for c in X.window_checks(recs, windows)}
    days = []
    for d in sorted(per_day):
        pd = per_day[d]
        shifts = []
        for w in [w for w in windows if w.date == d]:
            rs = [r for r in recs if r.day == d and r.shift == w.shift]
            tw = X.trunk_windows(w)
            chk = checks.get((d.isoformat(), w.shift))
            shifts.append({
                "name": w.name,
                "count": len(rs),
                "observed": f"{_hm(min(r.minute for r in rs))}–{_hm(max(r.minute for r in rs))}" if rs else "",
                "exam": [_hm(w.start), _hm(w.end)],          # suggested exam window
                "exam_source": w.source,                     # inm | density
                "arrival": tw["arrival"] if pd["tp"] else None,
                "opening": tw["opening"] if pd["to"] else None,
                "check": chk["text"] if chk else "",
                "suggested_start": chk["suggested_start"] if chk else "",
            })
        days.append({"date": d.isoformat(), "shifts": shifts})

    name, code = _guess_name(filename)
    return {
        "name": name, "code": code,
        "centres": len(centres), "alarms": n,
        "modalities": dict(sorted(mod_counts.items(), key=lambda kv: -kv[1])),
        "newAlarmTypes": sorted(new_types.values(), key=lambda x: -x["count"]),
        "days": days,
        "date_min": min(per_day).isoformat() if per_day else None,
        "date_max": max(per_day).isoformat() if per_day else None,
    }
