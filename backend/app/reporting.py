"""Event-report builder.

Produces the standardised CamView event report (light/print) for any event
modality, from measurable facts only. Centre ranking uses the modality's severity
basis: SUSTAINED detections for state conditions, raw COUNT for discrete violations,
and both sustained and count together for zone intrusion. Severity is always
expressed as a number, never a label.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import engine
from .models import Alert, Exam

# Per-modality severity basis. Belongs in the registry; kept here until the
# registry schema carries it.
SEVERITY_MODE = {
    "INM": "sustained", "CD": "sustained", "NP": "sustained",
    "ZI": "sustained_count", "MD": "count", "CT": "count",
    "TP": "compliance", "TO": "compliance",
}

COLLAPSE_SECONDS = 120     # same-camera fires within this gap are one detection
BURST_WINDOW = timedelta(minutes=15)   # window for the composite burst term

_MON = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
        "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass
class CentreStat:
    centre_code: str
    centre_name: str
    district: str
    alerts: int
    detections: int        # collapsed checkpoints
    longest_run_min: int   # longest consecutive sustained stretch
    peak_burst: int        # most alerts in any 15-min window
    score: float


def _hm(d: datetime | None) -> str:
    return f"{d.hour:02d}:{d.minute:02d}" if d else "--"


def _ts(d: datetime | None) -> str:
    return f"{d.day:02d} {_MON[d.month]} {d.hour:02d}:{d.minute:02d}:{d.second:02d}" if d else "--"


def _collapse(times: list[datetime]) -> list[list[datetime]]:
    """Group a single camera's sorted fire times into detections (incidents)."""
    if not times:
        return []
    groups = [[times[0]]]
    for t in times[1:]:
        if (t - groups[-1][-1]).total_seconds() <= COLLAPSE_SECONDS:
            groups[-1].append(t)
        else:
            groups.append([t])
    return groups


def _peak_burst(times: list[datetime]) -> int:
    if not times:
        return 0
    times = sorted(times)
    best = 1
    j = 0
    for i in range(len(times)):
        while times[i] - times[j] > BURST_WINDOW:
            j += 1
        best = max(best, i - j + 1)
    return best


def days_cond(days):
    """SQLAlchemy conditions restricting to specific exam dates (a list of
    'YYYY-MM-DD' strings). Empty / None means all days — the whole exam."""
    if not days:
        return ()
    return (func.date(Alert.occurred_at).in_(list(days)),)


def centre_stats(session: Session, exam_id: int, code: str, days=None) -> list[CentreStat]:
    rows = session.execute(
        select(Alert.centre_code, Alert.centre_name, Alert.district,
               Alert.camera_name, Alert.occurred_at)
        .where(Alert.exam_id == exam_id, Alert.modality_code == code, *days_cond(days))
        .order_by(Alert.centre_code, Alert.camera_name, Alert.occurred_at)
    ).all()

    centres: dict[str, dict] = {}
    for cc, cn, dist, cam, ts in rows:
        c = centres.setdefault(cc, {"name": cn, "district": dist, "cams": {}, "times": []})
        c["cams"].setdefault(cam, []).append(ts)
        if ts:
            c["times"].append(ts)

    mode = SEVERITY_MODE.get(code, "count")
    out: list[CentreStat] = []
    for cc, c in centres.items():
        alerts = sum(len(v) for v in c["cams"].values())
        detections = 0
        longest_sec = 0
        for cam_times in c["cams"].values():
            ct = sorted(t for t in cam_times if t)
            groups = _collapse(ct)
            detections += len(groups)
            # Longest unbroken sustained run = real elapsed wall-clock across
            # consecutive ~15-min checkpoints on one camera. A run continues
            # while the next checkpoint lands within one interval + slack; if it
            # doesn't, the condition cleared and a new run starts. We measure the
            # actual first->last span (no assumed cadence), so a camera firing
            # faster than 15 min can never inflate the duration.
            start = ct[0] if ct else None
            for a, b in zip(ct, ct[1:]):
                if (b - a).total_seconds() <= BURST_WINDOW.total_seconds() + 120:
                    longest_sec = max(longest_sec, (b - start).total_seconds())
                else:
                    start = b
        peak = _peak_burst([t for t in c["times"]])
        run_min = round(longest_sec / 60)
        if mode == "sustained":
            score = detections * 1000 + run_min
        elif mode == "sustained_count":   # zone intrusion: sustained and count together
            score = detections * 1000 + peak
        else:  # count / presence
            score = alerts
        out.append(CentreStat(cc, c["name"], c["district"], alerts, detections,
                              run_min, peak, score))
    out.sort(key=lambda s: -s.score)
    return out


@dataclass
class ReportData:
    exam: Exam
    code: str
    label: str
    mode: str
    total: int
    centres: int
    districts: int
    cameras: int
    tmin: datetime | None
    tmax: datetime | None
    hourly: list[int]
    minute_series: dict[int, int]   # minute-of-day -> count, for fine-grained timeline
    peak_hour: int
    peak_n: int
    districts_ranked: list[tuple[str, int]]
    dist_label: str
    centre_stats: list[CentreStat]
    evidence: list[Alert]


def gather(session: Session, exam_id: int, code: str, label: str,
           photos: list[str] | None = None, days=None) -> ReportData:
    exam = session.get(Exam, exam_id)
    base = (Alert.exam_id == exam_id, Alert.modality_code == code, *days_cond(days))
    total = session.scalar(select(func.count(Alert.id)).where(*base))
    centres = session.scalar(select(func.count(func.distinct(Alert.centre_code))).where(*base))
    districts = session.scalar(
        select(func.count(func.distinct(Alert.district))).where(*base, Alert.district != ""))
    cameras = session.scalar(select(func.count(func.distinct(Alert.camera_name))).where(*base))
    tmin = session.scalar(select(func.min(Alert.occurred_at)).where(*base))
    tmax = session.scalar(select(func.max(Alert.occurred_at)).where(*base))

    hour = func.strftime("%H", Alert.occurred_at) if engine.dialect.name == "sqlite" \
        else func.extract("hour", Alert.occurred_at)
    hourly = [0] * 24
    for h, n in session.execute(
        select(hour, func.count(Alert.id)).where(*base, Alert.occurred_at.is_not(None)).group_by(hour)
    ).all():
        try:
            hourly[int(h)] = n
        except (TypeError, ValueError):
            pass
    peak_hour = hourly.index(max(hourly)) if any(hourly) else 0

    hm = func.strftime("%H:%M", Alert.occurred_at) if engine.dialect.name == "sqlite" \
        else func.to_char(Alert.occurred_at, "HH24:MI")
    minute_series: dict[int, int] = {}
    for s_hm, n in session.execute(
        select(hm, func.count(Alert.id)).where(*base, Alert.occurred_at.is_not(None)).group_by(hm)
    ).all():
        try:
            h, m = str(s_hm).split(":")
            minute_series[int(h) * 60 + int(m)] = n
        except (ValueError, AttributeError):
            pass

    stats = centre_stats(session, exam_id, code, days)
    mode = SEVERITY_MODE.get(code, "count")
    sustained = mode in ("sustained", "sustained_count")

    # districts arranged by the modality's severity measure (worst first)
    dist_agg: dict[str, int] = {}
    for s in stats:
        if s.district:
            dist_agg[s.district] = dist_agg.get(s.district, 0) + (s.detections if sustained else s.alerts)
    districts_ranked = sorted(dist_agg.items(), key=lambda x: -x[1])[:22]
    dist_label = "sustained detections" if sustained else "alerts"

    # evidence: an operator-curated set of frames (in chosen order) when supplied,
    # otherwise drawn automatically from the highest-severity centres, worst first
    evidence: list[Alert] = []
    if photos:
        found = {a.alarm_id: a for a in session.scalars(
            select(Alert).where(*base, Alert.alarm_id.in_(photos))).all()}
        evidence = [found[p] for p in photos if p in found]
    else:
        for cs in stats:
            a = session.scalar(
                select(Alert).where(*base, Alert.centre_code == cs.centre_code,
                                    Alert.evidence_image != "").order_by(Alert.occurred_at)
            )
            if a:
                evidence.append(a)
            if len(evidence) >= 12:
                break

    return ReportData(
        exam=exam, code=code, label=label, mode=SEVERITY_MODE.get(code, "count"),
        total=total, centres=centres, districts=districts, cameras=cameras,
        tmin=tmin, tmax=tmax, hourly=hourly, minute_series=minute_series, peak_hour=peak_hour,
        peak_n=max(hourly) if hourly else 0, districts_ranked=districts_ranked,
        dist_label=dist_label, centre_stats=stats, evidence=evidence,
    )
