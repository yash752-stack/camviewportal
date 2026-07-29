"""Auto-analysis of an uploaded alert Excel for the exam-creation wizard.

Reads the workbook once (never persists) and infers the exam STRUCTURE the data
can prove — dates, and how many shifts ran on each day — plus a suggested set of
trunk windows drawn from where the box events actually clustered. The operator
then confirms/edits everything; the authorised windows in particular are only
*suggestions* (a suggested window derived from the data would make compliance
circular — "late" must be judged against the official timetable, not the data).
"""
from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path

from .ingest.excel import read_workbook
from .registry import get_registry

GAP_TRUNK = 120   # min gap in Trunk-Placed times that separates one shift from the next
GAP_ALERT = 90    # fallback: gap in general alert density (exams with no trunk data)


def _split(times: list[int], gap: int) -> list[list[int]]:
    """Split a sorted minute-of-day list into clusters separated by > gap minutes."""
    if not times:
        return []
    times = sorted(times)
    out: list[list[int]] = [[times[0]]]
    for t in times[1:]:
        if t - out[-1][-1] > gap:
            out.append([t])
        else:
            out[-1].append(t)
    return out


def _r5(m: int, up: bool = False) -> int:
    return ((m + 4) // 5 * 5) if up else (m // 5 * 5)


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
            mod = reg.resolve(a.channel, a.alarm_type)
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

    days = []
    for d in sorted(per_day):
        pd = per_day[d]
        # Trunk-Placed events mark shift starts cleanly; fall back to alert density.
        clusters = _split(pd["tp"], GAP_TRUNK) if pd["tp"] else _split(pd["all"], GAP_ALERT)
        shifts = []
        for i, cl in enumerate(clusters):
            lo, hi = min(cl), max(cl)
            nxt = min(clusters[i + 1]) if i + 1 < len(clusters) else 24 * 60
            tp_in = [t for t in pd["tp"] if lo - 30 <= t <= hi + 30]
            # opening suggestion: only Trunk-Open events AFTER the arrivals finish —
            # opens during the arrival/handling phase are box-handling noise
            to_in = [t for t in pd["to"] if hi <= t < nxt]
            arr = [_hm(_r5(min(tp_in))), _hm(_r5(max(tp_in), up=True))] if tp_in else None
            opn = [_hm(_r5(min(to_in))), _hm(_r5(max(to_in), up=True))] if to_in else None
            shifts.append({
                "name": f"Shift {i + 1}",
                "count": sum(1 for t in pd["all"] if lo <= t < nxt),
                "observed": f"{_hm(lo)}–{_hm(hi)}",
                "arrival": arr,      # suggested trunk arrival window (from Trunk-Placed spread)
                "opening": opn,      # suggested trunk opening window (from Trunk-Open spread)
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
