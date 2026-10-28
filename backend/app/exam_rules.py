"""How the portal reads an exam day — the operations-review rules.

Every number on the Alert Stats / Alert Analysis view and every finding of the
Excel validation check comes from this module, so the rules live in one place
and can be read, tested and changed together. The rules were set by operations
review (the manager's Exam Monitoring Report); each is a named constant below.

THE EXAM DAY
  A day has one or more SHIFTS. Each shift has an EXAM WINDOW: the time the
  paper is actually being written. The window is found from Invigilator Not
  Moving (INM), because invigilators only stand still once candidates are
  writing: the first sustained INM cluster opens the window, its last alert
  closes it, both rounded out to the half hour. The operator confirms or edits
  the suggestion in the New Examination wizard; a confirmed window always wins.

  Shift boundaries follow the windows: Shift 1 runs from the first alert of the
  day to the end of its exam window, Shift 2 from there to the end of its own
  window, and so on. Anything before a shift's window is PRE-EXAM (setup); any
  alert after the last window is POST-EXAM.

STAGES  (config/modalities.json `stage`)
  pre     box handling and room setup: Trunk Placed, Trunk Opened, Trunk
          Tampering, Furniture Out of Place. Counted across the whole shift.
  during  only meaningful while candidates write: Cheating, Multiple Persons
          Standing, Invigilator Not Moving. Counted inside the exam window;
          the same alert outside it is reported as OFF-HOURS, not dropped.
  whole   watched all day: Crowd, Zone Intrusion, Camera Tampering, No Person,
          Mobile. Counted across the whole shift.

  Shift-to-shift comparisons (swings, the exam clock, the heat map) use exam-
  window alerts only, so a long setup in one shift does not distort them.

PRIORITY  (a second axis beside severity, never replacing it)
  Severity says what KIND of alert it is (a phone is Critical whatever the
  camera). Priority says how PERSISTENT the camera is: the number of times that
  camera raised that alert type in that shift.
      High   >= PRIORITY_HIGH (10)
      Medium >= PRIORITY_MEDIUM (5)
      Low    otherwise
  So a Zone Intrusion from a camera that raised it 10 times is High priority,
  and one from a camera that raised it twice is Low.

TRUNK WINDOWS  (used when an exam has no configured timetable)
  arrival  90 to 45 minutes before the exam window opens
  opening  the last 15 minutes before the exam window opens

UNUSUAL CENTRES
  For each alert type, a centre outside mean +/- 1 standard deviation of the
  per-centre counts (every centre in the exam counted, zeros included) is
  flagged high or low.

LISTS
  "Top" and "bottom" lists show the top 10 or the top 5%, whichever is larger.

SWING
  (Shift 2 - Shift 1) / Shift 1. A count that was zero in Shift 1 is "new".

RISK OVERLAPS
  Named pairs from RISK_RULES: the subject alert counts as overlapping when the
  other alert fires at the same centre (or in the same room, i.e. the same
  camera) within the stated minutes.
"""
from __future__ import annotations

import json
import math
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Iterable

from .registry import get_registry

# ── the rules, as numbers ───────────────────────────────────────────────────
PRIORITY_HIGH = 10
PRIORITY_MEDIUM = 5
WINDOW_ANCHOR = "INM"        # the model whose activity marks the exam window
WINDOW_ROUND = 30            # exam windows are rounded out to the half hour
WINDOW_CLUSTER_GAP = 30      # INM alerts further apart than this start a new cluster
WINDOW_SPLIT_GAP = 90        # clusters further apart than this are different shifts
WINDOW_NOISE_SHARE = 0.02    # a cluster under 2% of the day's INM (min 3) is noise
DENSITY_SPLIT_GAP = 90       # fallback when there is no INM: gap in all alerts
TRUNK_ARRIVAL_BEFORE = (90, 45)   # minutes before exam start
TRUNK_OPENING_BEFORE = (15, 0)
TRUNK_OPEN_TOLERANCE = 5     # an open stamped up to 5 min before the arrival is channel noise
OUTLIER_SD = 1.0
TOP_MIN, TOP_SHARE = 10, 0.05
SLOT_MIN = 30                # the exam clock's slot width
LIST_CAP = 100               # most rows any one list sends to the page (the rule's k is still reported)

PRIORITIES = ("High", "Medium", "Low")


@dataclass(frozen=True)
class RiskRule:
    other: str               # modality code of the related alert
    scope: str               # "centre" or "room" (same camera)
    minutes: int | None      # window either side; None = any time in the shift
    text: str                # what the overlap means, for the report
    other_zone: str = ""     # restrict the other alert to a camera location
    after_only: bool = False # the other alert must FOLLOW the subject


RISK_RULES: dict[str, list[RiskRule]] = {
    "ZI": [RiskRule("CT", "centre", 30, "a camera at the same centre was tampered with within 30 minutes"),
           RiskRule("CD", "centre", 30, "a crowd was detected in the control room of the same centre within 30 minutes",
                    other_zone="CONTROL ROOM")],
    "CD": [RiskRule("ZI", "centre", 30, "someone also entered a restricted zone at the same centre within 30 minutes"),
           RiskRule("CT", "centre", 30, "a camera at the same centre was tampered with within 30 minutes")],
    "CHT": [RiskRule("INM", "room", 15, "the invigilator in that room was stationary at the time"),
            RiskRule("MD", "room", 30, "a mobile was detected in the same room within 30 minutes")],
    "NP": [RiskRule("TP", "centre", 60, "a trunk was placed at that centre within 1 hour"),
           RiskRule("CD", "centre", 60, "there was a crowd at the entry gate of that centre within 1 hour",
                    other_zone="ENTRY EXIT"),
           RiskRule("TO", "centre", 60, "a trunk was opened at that centre within 1 hour")],
    "CT": [RiskRule("CHT", "centre", 60, "a cheating alert fired at that centre within 1 hour"),
           RiskRule("INM", "centre", 60, "an invigilator-not-moving alert fired at that centre within 1 hour"),
           RiskRule("MD", "centre", 60, "a mobile was detected at that centre within 1 hour")],
    "MPS": [RiskRule("CHT", "room", 60, "a cheating alert followed in the same room within 1 hour", after_only=True),
            RiskRule("MD", "room", 60, "a mobile was detected in the same room within 1 hour")],
    "FOP": [RiskRule("CT", "room", None, "a camera in the same room was also tampered with"),
            RiskRule("CHT", "room", None, "cheating was detected in the same room"),
            RiskRule("NP", "centre", 60, "the control room was empty within 1 hour")],
}


# ── records ─────────────────────────────────────────────────────────────────
@dataclass
class Rec:
    """One alert, normalised from either an Excel row or a stored Alert."""
    alarm_id: str
    code: str
    label: str
    stage: str
    severity: str
    centre_code: str
    centre_name: str
    district: str
    zone: str
    camera: str
    ts: datetime
    # filled by assign()
    shift: int = 0           # 1-based within the day
    phase: str = ""          # pre | exam | post
    priority: str = ""
    priority_count: int = 0
    row_id: int = 0          # Alert.id when read from the database

    @property
    def minute(self) -> int:
        return self.ts.hour * 60 + self.ts.minute

    @property
    def day(self) -> date:
        return self.ts.date()

    @property
    def cam_key(self) -> str:
        return f"{self.centre_code}|{self.camera or self.zone or '?'}"

    @property
    def in_scope(self) -> bool:
        """Does this alert count for its model? `during` models count only
        inside the exam window; the rest count across the whole shift."""
        return self.phase == "exam" if self.stage == "during" else True


def _zone(z: str) -> str:
    return " ".join((z or "").upper().replace("/", " ").split())


def _pretty_zone(z: str) -> str:
    z = _zone(z)
    return {"CLASS ROOM": "Class Room", "CONTROL ROOM": "Control Room",
            "ENTRY EXIT": "Entry / Exit", "STRONG ROOM": "Strong Room"}.get(z, z.title() or "Unknown")


def from_raw(rows: Iterable, registry=None) -> list[Rec]:
    """Records from ingest.excel.RawAlert rows, deduplicated by Alarm ID.
    Rows with no usable time are left out (the validation check reports them)."""
    reg = registry or get_registry()
    out, seen = [], set()
    for a in rows:
        if not a.alarm_id or a.alarm_id in seen or a.timestamp is None:
            continue
        seen.add(a.alarm_id)
        m = reg.resolve(a.channel, a.alarm_type)
        code = m.code if m else (f"X{a.channel}" if a.channel else "X?")
        out.append(Rec(
            alarm_id=a.alarm_id, code=code,
            label=m.display_label if m else (a.alarm_type or code),
            stage=m.stage if m else "whole",
            severity=m.severity_for(a.zone) if m else "Medium",
            centre_code=a.centre_code, centre_name=(a.centre_name or "").title(),
            district=(a.district or "").title(), zone=_zone(a.zone),
            camera=a.camera_name, ts=a.timestamp))
    return out


def from_alerts(alerts: Iterable, registry=None) -> list[Rec]:
    """Records from stored Alert rows. The model is re-resolved by channel so an
    exam ingested before a model joined the catalogue reads correctly."""
    reg = registry or get_registry()
    out = []
    for a in alerts:
        if a.occurred_at is None:
            continue
        m = reg.resolve(a.channel, a.alarm_type_raw) or reg.by_code(a.modality_code)
        out.append(Rec(
            alarm_id=a.alarm_id, code=m.code if m else a.modality_code,
            label=m.display_label if m else (a.display_label or a.modality_code),
            stage=m.stage if m else "whole", severity=a.severity,
            centre_code=a.centre_code, centre_name=a.centre_name, district=a.district,
            zone=_zone(a.zone), camera=a.camera_name, ts=a.occurred_at, row_id=a.id))
    return out


# ── exam windows ────────────────────────────────────────────────────────────
@dataclass
class Window:
    date: date
    shift: int
    start: int               # minute of day
    end: int
    source: str              # configured | inm | density

    @property
    def name(self) -> str:
        return f"Shift {self.shift}"

    def label(self) -> str:
        return f"{hm12(self.start)} to {hm12(self.end)}"

    def as_dict(self) -> dict:
        return {"date": self.date.isoformat(), "shift": self.shift, "name": self.name,
                "start": hm(self.start), "end": hm(self.end), "source": self.source,
                "label": self.label()}


def hm(m: int) -> str:
    m = int(m)
    return f"{m // 60:02d}:{m % 60:02d}"


def hm12(m: int) -> str:
    m = int(m) % (24 * 60)
    h, mm = divmod(m, 60)
    ap = "AM" if h < 12 else "PM"
    h12 = h % 12 or 12
    return f"{h12}:{mm:02d} {ap}" if mm else f"{h12} {ap}"


def _m(t: str) -> int:
    h, mm = str(t).strip().split(":")
    return int(h) * 60 + int(mm)


def _clusters(times: list[int], gap: int) -> list[list[int]]:
    times = sorted(times)
    if not times:
        return []
    out = [[times[0]]]
    for t in times[1:]:
        (out[-1].append(t) if t - out[-1][-1] <= gap else out.append([t]))
    return out


def infer_windows(recs: list[Rec]) -> list[Window]:
    """Exam windows per day from INM activity (fallback: overall alert density)."""
    by_day: dict[date, list[Rec]] = defaultdict(list)
    for r in recs:
        by_day[r.day].append(r)
    out: list[Window] = []
    for d in sorted(by_day):
        inm = [r.minute for r in by_day[d] if r.code == WINDOW_ANCHOR]
        source = "inm"
        if inm:
            floor = max(3, math.ceil(WINDOW_NOISE_SHARE * len(inm)))
            kept = [c for c in _clusters(inm, WINDOW_CLUSTER_GAP) if len(c) >= floor]
            if not kept:
                kept = _clusters(inm, WINDOW_CLUSTER_GAP)
            spans = _clusters([t for c in kept for t in c], WINDOW_SPLIT_GAP)
        else:
            source = "density"
            body = [r.minute for r in by_day[d] if r.stage != "pre"] or [r.minute for r in by_day[d]]
            spans = _clusters(body, DENSITY_SPLIT_GAP)
        for i, sp in enumerate(spans):
            s = min(sp) // WINDOW_ROUND * WINDOW_ROUND
            e = -(-(max(sp) + 1) // WINDOW_ROUND) * WINDOW_ROUND
            out.append(Window(d, i + 1, s, e, source))
    return out


def _store() -> Path:
    from .settings import get_settings
    return get_settings().data_dir / "exam_windows.json"


def load_windows(code: str) -> dict:
    """{date: {"source": ..., "windows": [[start,end],...]}} as stored for an exam."""
    p = _store()
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text()).get(code, {})
    except (OSError, ValueError):
        return {}


def save_windows(code: str, windows: list[Window] | list[dict], source: str | None = None,
                 overwrite_confirmed: bool = False) -> dict:
    """Store an exam's windows. Inferred windows never overwrite ones an operator
    confirmed unless `overwrite_confirmed` is set."""
    p = _store()
    try:
        cfg = json.loads(p.read_text()) if p.exists() else {}
    except (OSError, ValueError):
        cfg = {}
    entry = cfg.get(code, {})
    per_day: dict[str, list] = defaultdict(list)
    src_of: dict[str, str] = {}
    for w in windows:
        if isinstance(w, Window):
            k, sp, src = w.date.isoformat(), [hm(w.start), hm(w.end)], w.source
        else:
            k, sp, src = str(w["date"])[:10], [w["start"], w["end"]], w.get("source", "configured")
        per_day[k].append(sp)
        src_of[k] = source or src
    for k, spans in per_day.items():
        if entry.get(k, {}).get("source") == "configured" and src_of[k] != "configured" and not overwrite_confirmed:
            continue
        entry[k] = {"source": src_of[k], "windows": sorted(spans, key=lambda s: _m(s[0]))}
    cfg[code] = entry
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, indent=2))
    return entry


def windows_for(code: str | None, recs: list[Rec]) -> list[Window]:
    """Stored windows (confirmed or inferred at ingest) where a day has them,
    inference from the alerts for any day that does not."""
    stored = load_windows(code) if code else {}
    inferred = infer_windows(recs)
    days = sorted({r.day for r in recs} | {date.fromisoformat(k) for k in stored})
    out: list[Window] = []
    for d in days:
        st = stored.get(d.isoformat())
        if st and st.get("windows"):
            for i, (s, e) in enumerate(sorted(st["windows"], key=lambda x: _m(x[0]))):
                out.append(Window(d, i + 1, _m(s), _m(e), st.get("source", "configured")))
        else:
            out.extend(w for w in inferred if w.date == d)
    return out


def trunk_windows(window: Window) -> dict:
    """The authorised trunk windows a shift implies when no timetable is set."""
    a0, a1 = TRUNK_ARRIVAL_BEFORE
    o0, o1 = TRUNK_OPENING_BEFORE
    return {"name": window.name,
            "arrival": [hm(window.start - a0), hm(window.start - a1)],
            "opening": [hm(window.start - o0), hm(window.start - o1)]}


# ── assignment and priority ─────────────────────────────────────────────────
def assign(recs: list[Rec], windows: list[Window]) -> list[Rec]:
    """Give every record its shift and phase, then its camera-frequency priority."""
    by_day: dict[date, list[Window]] = defaultdict(list)
    for w in windows:
        by_day[w.date].append(w)
    for ws in by_day.values():
        ws.sort(key=lambda w: w.start)
    for r in recs:
        ws = by_day.get(r.day)
        if not ws:
            r.shift, r.phase = 1, "exam"
            continue
        t = r.minute
        for i, w in enumerate(ws):
            if t < w.end or i == len(ws) - 1:
                r.shift = w.shift
                r.phase = "pre" if t < w.start else ("exam" if t < w.end else "post")
                break
    counts = Counter((r.day, r.shift, r.cam_key, r.code) for r in recs)
    for r in recs:
        n = counts[(r.day, r.shift, r.cam_key, r.code)]
        r.priority_count = n
        r.priority = priority_of(n)
    return recs


def priority_of(n: int) -> str:
    return "High" if n >= PRIORITY_HIGH else "Medium" if n >= PRIORITY_MEDIUM else "Low"


# ── small helpers the report uses ───────────────────────────────────────────
def top_k(n: int) -> int:
    return min(n, max(TOP_MIN, math.ceil(TOP_SHARE * n)))


def swing(a: int, b: int) -> int | None:
    """Percent change Shift 1 -> Shift 2. None means new (Shift 1 was zero)."""
    if a == 0:
        return None if b else 0
    return round((b - a) / a * 100)


def outliers(per_centre: dict[str, int]) -> dict:
    vals = list(per_centre.values())
    if not vals:
        return {"mean": 0, "sd": 0, "high": [], "low": []}
    mean = statistics.fmean(vals)
    sd = statistics.pstdev(vals) if len(vals) > 1 else 0.0
    hi = mean + OUTLIER_SD * sd
    lo = mean - OUTLIER_SD * sd
    return {"mean": round(mean, 1), "sd": round(sd, 1),
            "high": sorted([c for c, v in per_centre.items() if sd and v > hi], key=lambda c: -per_centre[c]),
            "low": sorted([c for c, v in per_centre.items() if sd and v < lo], key=lambda c: per_centre[c])}


# ── trunk compliance on the relative rule ───────────────────────────────────
def trunk_compliance(recs: list[Rec], windows: list[Window], timetable=None) -> list[dict]:
    """Per shift and centre: first Trunk Placed against the arrival window, first
    Trunk Opened at or after that arrival against the opening window.

    `timetable(date)` returns the exam's authorised windows for a day (the same
    ones the compliance report uses, see compliance.get_shifts); shift N takes
    the Nth. Without a timetable, or for a shift it does not cover, the windows
    follow from the exam start by the relative rule."""
    wmap = {(w.date, w.shift): w for w in windows}
    first_tp: dict[tuple, Rec] = {}
    for r in recs:
        if r.code == "TP":
            k = (r.day, r.shift, r.centre_code)
            if k not in first_tp or r.ts < first_tp[k].ts:
                first_tp[k] = r
    first_to: dict[tuple, Rec] = {}
    for r in recs:
        if r.code != "TO":
            continue
        k = (r.day, r.shift, r.centre_code)
        arr = first_tp.get(k)
        if arr is not None and r.minute < arr.minute - TRUNK_OPEN_TOLERANCE:
            continue
        if k not in first_to or r.ts < first_to[k].ts:
            first_to[k] = r
    out = []
    for k in sorted(set(first_tp) | set(first_to), key=lambda x: (x[0], x[1], x[2])):
        w = wmap.get((k[0], k[1]))
        if not w:
            continue
        tw = trunk_windows(w)
        if timetable is not None:
            tt = timetable(k[0]) or []
            if len(tt) >= k[1]:
                tw = tt[k[1] - 1]
        row = {"date": k[0].isoformat(), "shift": k[1], "centre": k[2], "exam_start": hm(w.start)}
        for kind, rec, win in (("arrival", first_tp.get(k), tw["arrival"]),
                               ("opening", first_to.get(k), tw["opening"])):
            if rec is None:
                row[kind] = {"status": "none", "window": win}
                continue
            s, e = _m(win[0]), _m(win[1])
            t = rec.minute
            st = "early" if t < s else "late" if t > e else "ok"
            row[kind] = {"status": st, "at": rec.ts.strftime("%H:%M:%S"), "window": win,
                         "gap": (s - t) if st == "early" else (t - e) if st == "late" else 0,
                         "centre_name": rec.centre_name}
        out.append(row)
    return out


def window_checks(recs: list[Rec], windows: list[Window]) -> list[dict]:
    """Cross-check each exam window against the trunk openings of its shift.

    INM only starts once an invigilator has been stationary for a while, so on
    some exams it lags the real start. If most boxes were opened well before the
    INM-based start, the window is probably late: say so, and suggest the start
    the openings imply (median opening rounded up to the half hour), so the
    operator can confirm one or the other."""
    if any(r.shift == 0 for r in recs):
        assign(recs, windows)
    out = []
    for w in windows:
        first: dict[str, int] = {}
        for r in recs:
            if r.code == "TO" and r.day == w.date and r.shift == w.shift:
                first[r.centre_code] = min(first.get(r.centre_code, 10 ** 6), r.minute)
        if len(first) < 3:
            continue
        o0 = w.start - TRUNK_OPENING_BEFORE[0]
        early = sum(1 for t in first.values() if t < o0)
        share = early / len(first)
        med = int(statistics.median(first.values()))
        alt = -(-(med + 1) // WINDOW_ROUND) * WINDOW_ROUND
        if share >= 0.6 and alt < w.start:
            out.append({"date": w.date.isoformat(), "shift": w.shift, "level": "warn",
                        "window_start": hm(w.start), "suggested_start": hm(alt),
                        "share_early": round(100 * share),
                        "text": (f"{w.name}: {round(100 * share)}% of trunks were opened before "
                                 f"{hm12(o0)}, the earliest the opening window allows if the exam "
                                 f"started at {hm12(w.start)} (median opening {hm12(med)}). "
                                 f"The exam probably started nearer {hm12(alt)}: Invigilator Not "
                                 f"Moving can lag the real start. Confirm the start before reading "
                                 f"trunk compliance.")})
    return out


def trunk_summary(rows: list[dict]) -> dict:
    """Status counts per checkpoint and the worst exceptions, for the page."""
    out = {}
    for kind in ("arrival", "opening"):
        cnt = Counter(r[kind]["status"] for r in rows)
        bad = sorted((r for r in rows if r[kind]["status"] in ("early", "late")), key=lambda r: -r[kind]["gap"])
        out[kind] = {"counts": {k: cnt.get(k, 0) for k in ("ok", "early", "late", "none")},
                     "exceptions": [{"centre": r["centre"], "shift": r["shift"], "date": r["date"], **r[kind]}
                                    for r in bad[:min(top_k(len(bad)), LIST_CAP)]],
                     "exception_count": len(bad)}
    out["boxes"] = len(rows)
    return out


# ── risk overlaps ───────────────────────────────────────────────────────────
def risk_overlaps(recs: list[Rec], subject: str) -> dict:
    rules = RISK_RULES.get(subject)
    if not rules:
        return {}
    subj = [r for r in recs if r.code == subject]
    index: dict[tuple, list[Rec]] = defaultdict(list)
    for r in recs:
        index[(r.code, r.day, r.shift, r.centre_code)].append(r)
    result = {"subject": subject, "rules": [], "by_shift": {}}
    flags: dict[str, list[bool]] = {}
    for rule in rules:
        hits = []
        for s in subj:
            hit = False
            for o in index.get((rule.other, s.day, s.shift, s.centre_code), ()):
                if rule.scope == "room" and o.cam_key != s.cam_key:
                    continue
                if rule.other_zone and o.zone != rule.other_zone:
                    continue
                dt = (o.ts - s.ts).total_seconds() / 60
                if rule.after_only and dt < 0:
                    continue
                if rule.minutes is None or abs(dt) <= rule.minutes:
                    hit = True
                    break
            hits.append(hit)
        flags[rule.other + rule.other_zone] = hits
        result["rules"].append({"other": rule.other, "text": rule.text, "hits": sum(hits),
                                "examples": [_ex(s) for s, h in zip(subj, hits) if h][:5]})
    # combinations, per shift
    names = list(flags)
    for i, s in enumerate(subj):
        combo = tuple(n for n in names if flags[n][i])
        sh = result["by_shift"].setdefault(s.shift, Counter())
        sh[combo] += 1
    result["by_shift"] = {sh: [{"with": list(k), "n": v} for k, v in c.most_common()]
                          for sh, c in result["by_shift"].items()}
    result["total"] = len(subj)
    return result


def _ex(r: Rec) -> str:
    return f"{r.centre_name or r.centre_code} · {r.camera or _pretty_zone(r.zone)} · {r.ts.strftime('%H:%M')}"


def rules_summary() -> dict:
    """The reading rules in plain words, for the 'How alerts are read' tab."""
    reg = get_registry()
    models = [{"code": m.code, "label": m.display_label, "stage": m.stage, "severity": m.default_severity,
               "escalation": (f"{m.escalation_to} at {', '.join(_pretty_zone(z) for z in m.escalation_zones)}"
                              if m.escalation_to else ""),
               "adopted": m.synthetic,
               "risk": [r.text for r in RISK_RULES.get(m.code, [])]} for m in reg.modalities]
    return {
        "priority": {"high": PRIORITY_HIGH, "medium": PRIORITY_MEDIUM},
        "window": {"anchor": WINDOW_ANCHOR, "round": WINDOW_ROUND, "cluster_gap": WINDOW_CLUSTER_GAP,
                   "split_gap": WINDOW_SPLIT_GAP},
        "trunk": {"arrival": list(TRUNK_ARRIVAL_BEFORE), "opening": list(TRUNK_OPENING_BEFORE),
                  "tolerance": TRUNK_OPEN_TOLERANCE},
        "outlier_sd": OUTLIER_SD, "top": {"min": TOP_MIN, "share": TOP_SHARE}, "slot": SLOT_MIN,
        "models": models,
    }


# ── the whole picture ───────────────────────────────────────────────────────
def analyse(recs: list[Rec], windows: list[Window], timetable=None) -> dict:
    """Everything the Alert Stats and Alert Analysis views show, as plain data."""
    reg = get_registry()
    assign(recs, windows)
    shifts = sorted({r.shift for r in recs}) or [1]
    centres = {r.centre_code: r.centre_name for r in recs}
    exam = [r for r in recs if r.phase == "exam"]

    def per(sel, key):
        c: dict[int, Counter] = {s: Counter() for s in shifts}
        for r in sel:
            c[r.shift][key(r)] += 1
        return c

    # headline per shift
    head = []
    for s in shifts:
        rs = [r for r in recs if r.shift == s]
        ex = [r for r in rs if r.phase == "exam"]
        ws = [w for w in windows if w.shift == s]
        slots = Counter((r.minute // SLOT_MIN) * SLOT_MIN for r in ex)
        pk = max(slots.items(), key=lambda kv: kv[1]) if slots else (None, 0)
        head.append({
            "shift": s, "total": len(rs), "exam": len(ex),
            "pre": sum(1 for r in rs if r.phase == "pre"),
            "post": sum(1 for r in rs if r.phase == "post"),
            "cameras": len({r.cam_key for r in rs}),
            "centres": len({r.centre_code for r in rs}),
            "window": ws[0].label() if ws else "",
            "window_source": ws[0].source if ws else "",
            "shift_span": f"{hm12(min(r.minute for r in rs))} to {hm12(max(r.minute for r in rs) + 1)}" if rs else "",
            "peak_slot": f"{hm12(pk[0])} to {hm12(pk[0] + SLOT_MIN)}" if pk[0] is not None else "",
            "peak_n": pk[1],
            "pre_by_type": dict(Counter(r.label for r in rs if r.phase == "pre").most_common()),
        })

    types = sorted({r.code for r in recs}, key=lambda c: -sum(1 for r in recs if r.code == c))
    label = {r.code: r.label for r in recs}
    stage = {r.code: r.stage for r in recs}

    def a2(c: dict, k) -> list[int]:
        return [c[s].get(k, 0) for s in shifts]

    by_type_exam = per(exam, lambda r: r.code)
    by_type_cams = {s: defaultdict(set) for s in shifts}
    for r in exam:
        by_type_cams[r.shift][r.code].add(r.cam_key)
    features = []
    for t in types:
        if stage[t] == "pre":
            continue          # box handling and setup: shown per model in the analysis, not compared on the exam clock
        v = a2(by_type_exam, t)
        cams = [len(by_type_cams[s][t]) for s in shifts]
        features.append({"code": t, "label": label[t], "stage": stage[t], "alerts": v, "cameras": cams,
                         "per_camera": [round(a / c, 1) if c else 0 for a, c in zip(v, cams)],
                         "swing": swing(v[0], v[-1]) if len(v) > 1 else None})

    by_centre_exam = per(exam, lambda r: r.centre_code)
    centre_rows = sorted(
        ({"code": c, "name": centres[c], "alerts": a2(by_centre_exam, c),
          "swing": swing(*a2(by_centre_exam, c)[:2]) if len(shifts) > 1 else None}
         for c in centres), key=lambda x: -sum(x["alerts"]))

    by_cam_exam = per(exam, lambda r: r.cam_key)
    cam_info = {r.cam_key: (r.camera, r.centre_name or r.centre_code, _pretty_zone(r.zone)) for r in recs}
    cam_rows = [{"camera": cam_info[k][0], "centre": cam_info[k][1], "zone": cam_info[k][2],
                 "alerts": a2(by_cam_exam, k)} for k in cam_info]
    both = [c for c in cam_rows if len(shifts) > 1 and c["alerts"][0] and c["alerts"][1]]
    for c in cam_rows:
        c["swing"] = swing(c["alerts"][0], c["alerts"][1]) if len(shifts) > 1 else None
    cam_swing = sorted(both, key=lambda c: -abs(c["alerts"][1] - c["alerts"][0]))[:min(top_k(len(both)), LIST_CAP)]

    # exam clock: 30-min slots inside the windows, split by type
    clock = []
    for w in sorted(windows, key=lambda w: (w.date, w.start)):
        for m in range(w.start, w.end, SLOT_MIN):
            sel = [r for r in exam if r.day == w.date and r.shift == w.shift and m <= r.minute < m + SLOT_MIN]
            clock.append({"date": w.date.isoformat(), "shift": w.shift, "slot": hm12(m), "start": hm(m),
                          "total": len(sel), "by_type": dict(Counter(r.code for r in sel)),
                          "by_zone": dict(Counter(_pretty_zone(r.zone) for r in sel))})

    # centre x (location, type) heat map per shift, exam window
    cols = sorted({(_pretty_zone(r.zone), r.code) for r in exam})
    heat = {}
    for s in shifts:
        cnt = Counter((r.centre_code, _pretty_zone(r.zone), r.code) for r in exam if r.shift == s)
        rows = []
        for c in {cc for cc, _, _ in cnt}:
            vals = [cnt.get((c, z, t), 0) for z, t in cols]
            rows.append({"code": c, "name": centres[c], "vals": vals, "total": sum(vals)})
        rows.sort(key=lambda x: -x["total"])
        heat[s] = rows[:top_k(len(rows))]
    heat_cols = [{"zone": z, "code": t, "label": label[t]} for z, t in cols]

    # unusual centres per type, in the type's own scope
    unusual = []
    scoped = Counter((r.code, r.shift, r.centre_code) for r in recs if r.in_scope)
    for t in types:
        cnt = {s: Counter({c: scoped.get((t, s, c), 0) for c in centres}) for s in shifts}
        tot = {c: sum(cnt[s].get(c, 0) for s in shifts) for c in centres}
        o = outliers(tot)
        ordered = sorted(centres, key=lambda c: tot[c])
        far = sorted(set(o["high"]) | set(o["low"]), key=lambda c: -abs(tot[c] - o["mean"]))[:LIST_CAP]
        keep = set(far) | set(ordered[:TOP_MIN]) | set(ordered[-TOP_MIN:])
        unusual.append({"code": t, "label": label[t], "mean": o["mean"], "sd": o["sd"], "centres": len(centres),
                        "flagged": {"high": len(o["high"]), "low": len(o["low"])},
                        "rows": sorted(({"code": c, "name": centres[c],
                                         "by_shift": [cnt[s].get(c, 0) for s in shifts], "total": tot[c],
                                         "flag": "high" if c in o["high"] else "low" if c in o["low"] else ""}
                                        for c in keep), key=lambda x: x["total"])})

    # priority mix: alert type x High/Medium/Low, counted as camera-type pairs
    pairs = {}
    for r in recs:
        pairs[(r.shift, r.cam_key, r.code)] = r.priority
    prio = []
    for t in types:
        row = {"code": t, "label": label[t], "by_shift": []}
        for s in shifts:
            c = Counter(p for (sh, _, tt), p in pairs.items() if sh == s and tt == t)
            row["by_shift"].append([c.get(p, 0) for p in PRIORITIES])
        prio.append(row)
    pc = Counter((sh, ck.split("|")[0], p) for (sh, ck, _), p in pairs.items())
    prio_centre = [{"code": c, "name": centres[c],
                    "by_shift": [[pc.get((s, c, p), 0) for p in PRIORITIES] for s in shifts]} for c in centres]
    prio_centre.sort(key=lambda x: tuple(-sum(b[i] for b in x["by_shift"]) for i in range(3)))
    prio_centre = prio_centre[:top_k(len(prio_centre))]
    alert_prio = {s: Counter(r.priority for r in recs if r.shift == s) for s in shifts}

    # top / bottom cameras and sub-locations, per shift (all alerts in the shift)
    def rank(key, info):
        res = {}
        for s in shifts:
            c = Counter(key(r) for r in recs if r.shift == s)
            allk = [k for k in info]
            ordered = sorted(allk, key=lambda k: -c.get(k, 0))
            k = top_k(len(ordered))
            top = set(ordered[:k])
            bt: dict = defaultdict(Counter)
            for r in recs:
                if r.shift == s:
                    kk = key(r)
                    if kk in top:
                        bt[kk][r.label] += 1
            res[s] = {"n": len(ordered), "k": k, "listed": min(k, LIST_CAP),
                      "high": [{**info[x], "alerts": c.get(x, 0), "by_type": dict(bt[x])}
                               for x in ordered[:min(k, LIST_CAP)]],
                      "low": [{**info[x], "alerts": c.get(x, 0)} for x in list(reversed(ordered))[:min(k, LIST_CAP)]],
                      "typical": round(statistics.fmean([c.get(x, 0) for x in allk]), 1) if allk else 0}
        return res
    cam_meta = {k: {"camera": v[0], "centre": v[1], "zone": v[2]} for k, v in cam_info.items()}
    sub_meta = {(r.centre_code, _pretty_zone(r.zone)): {"centre": r.centre_name or r.centre_code, "code": r.centre_code,
                                                         "zone": _pretty_zone(r.zone)} for r in recs}
    top_cams = rank(lambda r: r.cam_key, cam_meta)
    top_subs = rank(lambda r: (r.centre_code, _pretty_zone(r.zone)), sub_meta)

    # volume vs variety, concentration, location scorecard
    quad, conc = {}, {}
    for s in shifts:
        ex = [r for r in exam if r.shift == s]
        vol = Counter(r.centre_code for r in ex)
        kinds: dict[str, set] = defaultdict(set)
        for r in ex:
            kinds[r.centre_code].add(r.code)
        var = {c: len(kinds[c]) for c in vol}
        if vol:
            mv, mt = statistics.median(vol.values()), statistics.median(var.values())
            q = defaultdict(list)
            for c in vol:
                key = ("busy" if vol[c] >= mv else "quiet") + "_" + ("varied" if var[c] >= mt else "narrow")
                q[key].append({"code": c, "name": centres[c], "alerts": vol[c], "types": var[c]})
            quad[s] = {"median_alerts": mv, "median_types": mt,
                       **{k2: sorted(v, key=lambda x: -x["alerts"])[:8] for k2, v in q.items()},
                       "counts": {k2: len(v) for k2, v in q.items()}}
        tot = sum(vol.values()) or 1
        ranked = vol.most_common()
        ct = Counter((r.centre_code, r.code) for r in ex)
        conc[s] = {"top1": round(100 * sum(v for _, v in ranked[:1]) / tot, 1),
                   "top3": round(100 * sum(v for _, v in ranked[:3]) / tot, 1),
                   "ranked": [{"code": c, "name": centres[c], "alerts": v,
                               "by_type": {t: n for (cc, t), n in ct.items() if cc == c}}
                              for c, v in ranked[:top_k(len(ranked))]]}
    zones = sorted({_pretty_zone(r.zone) for r in exam})
    scorecard = []
    for z in zones:
        sel = [r for r in exam if _pretty_zone(r.zone) == z]
        dom = Counter(r.label for r in sel).most_common(1)
        scorecard.append({"zone": z, "alerts": [sum(1 for r in sel if r.shift == s) for s in shifts],
                          "reach": [len({r.centre_code for r in sel if r.shift == s}) for s in shifts],
                          "centres": len(centres),
                          "dominant": dom[0][0] if dom else "",
                          "dominant_share": round(100 * dom[0][1] / len(sel)) if dom else 0})

    # alert analysis: one block per model, grouped by stage
    analysis = []
    for t in types:
        sel = [r for r in recs if r.code == t]
        inside = [r for r in sel if r.in_scope]
        off = [r for r in sel if r.phase != "exam"]
        hot = Counter((r.centre_code, r.cam_key) for r in inside)
        per_cs = Counter((r.centre_code, r.shift) for r in inside)
        blk = {"code": t, "label": label[t], "stage": stage[t],
               "severity": (reg.by_code(t).default_severity if reg.by_code(t) else ""),
               "counted": [sum(1 for r in inside if r.shift == s) for s in shifts],
               "off_hours": [sum(1 for r in off if r.shift == s) for s in shifts],
               "pre": [sum(1 for r in sel if r.shift == s and r.phase == "pre") for s in shifts],
               "slots": {s: dict(sorted(Counter((r.minute // SLOT_MIN) * SLOT_MIN for r in inside if r.shift == s).items()))
                         for s in shifts},
               "centres": sorted(({"code": c, "name": centres[c],
                                   "by_shift": [per_cs.get((c, s), 0) for s in shifts]}
                                  for c in {r.centre_code for r in inside}), key=lambda x: -sum(x["by_shift"]))[:top_k(len({r.centre_code for r in inside}))],
               "centre_count": len({r.centre_code for r in inside}),
               "hot": [{"camera": cam_info[k][0], "centre": cam_info[k][1], "zone": cam_info[k][2], "alerts": n}
                       for (_, k), n in hot.most_common(5)],
               "risk": risk_overlaps(recs, t)}
        analysis.append(blk)

    return {
        "shifts": shifts,
        "windows": [w.as_dict() for w in windows],
        "summary": head,
        "centres": len(centres),
        "features": features,
        "centre_swing": centre_rows[:top_k(len(centre_rows))],
        "centre_count": len(centre_rows),
        "camera_swing": cam_swing,
        "camera_both": len(both),
        "clock": clock,
        "heat": {"cols": heat_cols, "rows": heat},
        "unusual": unusual,
        "priority": {"by_type": prio, "by_centre": prio_centre,
                     "alerts": {s: dict(alert_prio[s]) for s in shifts},
                     "rule": f"High >= {PRIORITY_HIGH}, Medium {PRIORITY_MEDIUM} to {PRIORITY_HIGH - 1}, Low < {PRIORITY_MEDIUM}"},
        "top_cameras": top_cams,
        "top_sublocations": top_subs,
        "quadrant": quad,
        "concentration": conc,
        "scorecard": scorecard,
        "trunk": trunk_summary(trunk_compliance(recs, windows, timetable)),
        "window_checks": window_checks(recs, windows),
        "analysis": analysis,
        "rules": rules_summary(),
    }


# ── stored exams ────────────────────────────────────────────────────────────
def exam_records(session, exam, days=None) -> list[Rec]:
    from sqlalchemy import select
    from .models import Alert
    from .reporting import days_cond
    rows = session.scalars(select(Alert).where(Alert.exam_id == exam.id, *days_cond(days))).all()
    return from_alerts(rows)


def refresh_exam(session, exam) -> list[Window]:
    """Stamp every stored alert of an exam with its shift, phase and priority.

    Runs after an ingest, an append, and whenever the operator confirms the
    exam windows. Windows inferred here are saved (as inferred) so the trunk
    rule and the reports use the same windows the operator was shown; a window
    the operator confirmed is never overwritten."""
    from .models import Alert
    recs = exam_records(session, exam)
    windows = windows_for(exam.code, recs)
    stored = load_windows(exam.code)
    fresh = [w for w in windows if w.source != "configured" and w.date.isoformat() not in stored]
    if fresh:
        save_windows(exam.code, fresh)
    assign(recs, windows)
    session.bulk_update_mappings(Alert, [
        {"id": r.row_id, "priority": r.priority, "priority_count": r.priority_count,
         "shift_no": r.shift, "phase": r.phase} for r in recs if r.row_id])
    # an alert with no time cannot be placed in a shift; mark it so the boot-time
    # backfill does not keep treating the exam as never stamped
    from sqlalchemy import update
    session.execute(update(Alert).where(Alert.exam_id == exam.id, Alert.occurred_at.is_(None))
                    .values(priority="-", phase=""))
    session.commit()
    return windows


def exam_analysis(session, exam, days=None) -> dict:
    recs = exam_records(session, exam, days)
    windows = windows_for(exam.code, recs)
    if days:
        keep = {str(d)[:10] for d in days}
        windows = [w for w in windows if w.date.isoformat() in keep]
    from .compliance import get_shifts
    out = analyse(recs, windows, timetable=lambda d: get_shifts(exam.code, d))
    out["exam"] = {"code": exam.code, "name": exam.name, "body": exam.body,
                   "date": exam.exam_date.isoformat() if exam.exam_date else ""}
    return out


def reconcile_codes(session) -> int:
    """Re-label stored alerts whose model has since joined the catalogue.

    Before Cheating, Multiple Persons Standing and Trunk Tampering had catalogue
    entries, an ingest adopted them as generic X15/X17/X18 at Medium severity.
    This moves those rows onto the real model (code, labels, severity) so old
    exams read the same as new ones. Idempotent; returns rows changed."""
    from sqlalchemy import select, update
    from .models import Alert
    from .registry import SEVERITY_RANK
    reg = get_registry()
    changed = 0
    pairs = session.execute(
        select(Alert.modality_code, Alert.channel, Alert.alarm_type_raw, Alert.zone).distinct()).all()
    for code, ch, raw, zone in pairs:
        m = reg.resolve(ch, raw)
        if m is None or m.synthetic or m.code == code:
            continue
        cur = reg.by_code(code)
        if cur is not None and not cur.synthetic:
            continue          # a real catalogue code: leave it alone
        sev = m.severity_for(zone)
        res = session.execute(
            update(Alert).where(Alert.modality_code == code, Alert.channel == ch,
                                Alert.alarm_type_raw == raw, Alert.zone == zone)
            .values(modality_code=m.code, modality_label=m.label, display_label=m.display_label,
                    severity=sev, severity_rank=SEVERITY_RANK[sev]))
        changed += res.rowcount or 0
    session.commit()
    return changed
