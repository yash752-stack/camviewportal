"""Read-side query helpers. Filtering and sorting run in the database against the
composite indexes on the alerts table, so an operator paging through a 25k-row
exam pays for one indexed scan, not a full table load into the app."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .models import Alert, Exam
from .registry import SEVERITY_RANK

_SORTABLE = {
    "sev": Alert.severity_rank,
    "ts": Alert.occurred_at,
    "conf": Alert.confidence,
    "district": Alert.district,
    "type": Alert.display_label,
    "status": Alert.status,
}


@dataclass
class AlertFilter:
    severity: str | None = None
    modality: str | None = None
    district: str | None = None
    status: str | None = None
    centre_code: str | None = None
    query: str | None = None
    sort: str = "sev"
    direction: int = 1
    limit: int = 300
    offset: int = 0


def _apply(stmt, exam_id: int, f: AlertFilter):
    stmt = stmt.where(Alert.exam_id == exam_id)
    if f.severity and f.severity != "all":
        stmt = stmt.where(Alert.severity == f.severity)
    if f.modality and f.modality != "all":
        mods = [m for m in f.modality.split(",") if m]
        stmt = stmt.where(Alert.modality_code.in_(mods) if len(mods) > 1
                          else Alert.modality_code == mods[0])
    if f.district:
        stmt = stmt.where(Alert.district == f.district)
    if f.status:
        stmt = stmt.where(Alert.status == f.status)
    if f.centre_code:
        stmt = stmt.where(Alert.centre_code == f.centre_code)
    if f.query:
        like = f"%{f.query.strip()}%"
        stmt = stmt.where(
            Alert.centre_name.ilike(like)
            | Alert.district.ilike(like)
            | Alert.camera_name.ilike(like)
            | Alert.centre_code.ilike(like)
            | Alert.alarm_id.ilike(like)
            | Alert.evidence_id.ilike(like)
        )
    return stmt


def get_exam(session: Session, code: str) -> Exam | None:
    return session.scalar(select(Exam).where(Exam.code == code))


def first_exam(session: Session) -> Exam | None:
    return session.scalar(select(Exam).order_by(Exam.created_at.desc()))


def list_alerts(session: Session, exam_id: int, f: AlertFilter) -> tuple[list[Alert], int]:
    base = _apply(select(Alert), exam_id, f)
    total = session.scalar(_apply(select(func.count(Alert.id)), exam_id, f))
    col = _SORTABLE.get(f.sort, Alert.severity_rank)
    order = col.asc() if f.direction >= 0 else col.desc()
    # stable secondary ordering by recency so equal-severity rows keep a sane order
    rows = session.scalars(
        base.order_by(order, Alert.occurred_at.desc()).limit(f.limit).offset(f.offset)
    ).all()
    return list(rows), int(total or 0)


def get_alert(session: Session, exam_id: int, alarm_id: str) -> Alert | None:
    return session.scalar(
        select(Alert).where(Alert.exam_id == exam_id, Alert.alarm_id == alarm_id)
    )


def severity_counts(session: Session, exam_id: int) -> dict[str, int]:
    rows = session.execute(
        select(Alert.severity, func.count(Alert.id))
        .where(Alert.exam_id == exam_id).group_by(Alert.severity)
    ).all()
    counts = {s: 0 for s in SEVERITY_RANK}
    for sev, n in rows:
        counts[sev] = n
    return counts


def modality_counts(session: Session, exam_id: int) -> list[dict]:
    rows = session.execute(
        select(Alert.modality_code, Alert.display_label, func.count(Alert.id))
        .where(Alert.exam_id == exam_id)
        .group_by(Alert.modality_code, Alert.display_label)
    ).all()
    out = [{"code": c, "label": lbl, "count": n} for c, lbl, n in rows]
    out.sort(key=lambda x: -x["count"])
    return out


def district_options(session: Session, exam_id: int) -> list[str]:
    rows = session.execute(
        select(Alert.district).where(Alert.exam_id == exam_id, Alert.district != "")
        .distinct().order_by(Alert.district)
    ).all()
    return [r[0] for r in rows]


def status_counts(session: Session, exam_id: int) -> dict[str, int]:
    rows = session.execute(
        select(Alert.status, func.count(Alert.id))
        .where(Alert.exam_id == exam_id).group_by(Alert.status)
    ).all()
    return {s: n for s, n in rows}


def related_alerts(session: Session, alert: Alert, limit: int = 5) -> list[Alert]:
    return list(session.scalars(
        select(Alert)
        .where(
            Alert.exam_id == alert.exam_id,
            Alert.alarm_id != alert.alarm_id,
            (Alert.centre_code == alert.centre_code) | (Alert.district == alert.district),
        )
        .order_by(Alert.severity_rank, Alert.occurred_at.desc())
        .limit(limit)
    ))
