"""Overview aggregates: per-modality rollups for the exam command view.

All work is grouped in the database. Hour extraction is dialect-aware so the same
code runs on SQLite locally and Postgres in production.
"""
from __future__ import annotations

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from .db import engine
from .models import Alert
from .registry import SEVERITY_RANK, get_registry


def _hour_buckets(session: Session, exam_id: int) -> dict[str, list[int]]:
    # returns modality_code -> 24-slot hourly counts
    if engine.dialect.name == "sqlite":
        hour = func.strftime("%H", Alert.occurred_at)
    else:
        hour = func.extract("hour", Alert.occurred_at)
    rows = session.execute(
        select(Alert.modality_code, hour, func.count(Alert.id))
        .where(Alert.exam_id == exam_id, Alert.occurred_at.is_not(None))
        .group_by(Alert.modality_code, hour)
    ).all()
    out: dict[str, list[int]] = {}
    for code, h, n in rows:
        try:
            hi = int(h)
        except (TypeError, ValueError):
            continue
        if 0 <= hi < 24:
            out.setdefault(code, [0] * 24)[hi] = n
    return out


def modality_cards(session: Session, exam_id: int) -> list[dict]:
    registry = get_registry()

    totals = dict(session.execute(
        select(Alert.modality_code, func.count(Alert.id))
        .where(Alert.exam_id == exam_id).group_by(Alert.modality_code)
    ).all())

    sev_rows = session.execute(
        select(Alert.modality_code, Alert.severity, func.count(Alert.id))
        .where(Alert.exam_id == exam_id).group_by(Alert.modality_code, Alert.severity)
    ).all()
    sev: dict[str, dict[str, int]] = {}
    for code, s, n in sev_rows:
        sev.setdefault(code, {})[s] = n

    ev_rows = dict(session.execute(
        select(Alert.modality_code, func.count(Alert.id))
        .where(Alert.exam_id == exam_id, Alert.evidence_image != "")
        .group_by(Alert.modality_code)
    ).all())

    dist_rows = session.execute(
        select(Alert.modality_code, Alert.district, func.count(Alert.id))
        .where(Alert.exam_id == exam_id, Alert.district != "")
        .group_by(Alert.modality_code, Alert.district)
    ).all()
    top_district: dict[str, tuple[str, int]] = {}
    for code, district, n in dist_rows:
        cur = top_district.get(code)
        if cur is None or n > cur[1]:
            top_district[code] = (district, n)

    spark = _hour_buckets(session, exam_id)

    cards = []
    for code, total in totals.items():
        modality = next((m for m in registry.modalities if m.code == code), None)
        s = sev.get(code, {})
        cards.append({
            "code": code,
            "label": modality.display_label if modality else code,
            "archetype": modality.archetype if modality else "event",
            "count": total,
            "severity": {k: s.get(k, 0) for k in SEVERITY_RANK},
            "evidence_pct": round(100 * ev_rows.get(code, 0) / total) if total else 0,
            "top_district": top_district.get(code, ("", 0))[0],
            "spark": spark.get(code, [0] * 24),
        })
    # most operationally urgent first: by critical, then high, then volume
    cards.sort(key=lambda c: (-c["severity"]["Critical"], -c["severity"]["High"], -c["count"]))
    return cards


def overview_kpis(session: Session, exam_id: int) -> dict:
    total = session.scalar(select(func.count(Alert.id)).where(Alert.exam_id == exam_id)) or 0
    critical_open = session.scalar(
        select(func.count(Alert.id)).where(
            Alert.exam_id == exam_id, Alert.severity == "Critical", Alert.status != "Closed")
    ) or 0
    centres = session.scalar(
        select(func.count(func.distinct(Alert.centre_code))).where(Alert.exam_id == exam_id)) or 0
    districts = session.scalar(
        select(func.count(func.distinct(Alert.district))).where(
            Alert.exam_id == exam_id, Alert.district != "")) or 0
    with_evidence = session.scalar(
        select(func.count(Alert.id)).where(
            Alert.exam_id == exam_id, Alert.evidence_image != "")) or 0
    return {
        "alerts": total,
        "critical_open": critical_open,
        "centres": centres,
        "districts": districts,
        "evidence_pct": round(100 * with_evidence / total) if total else 0,
    }


def critical_feed(session: Session, exam_id: int, limit: int = 8) -> list[Alert]:
    return list(session.scalars(
        select(Alert)
        .where(Alert.exam_id == exam_id, Alert.severity.in_(("Critical", "High")))
        .order_by(Alert.severity_rank, Alert.occurred_at.desc())
        .limit(limit)
    ))


def top_districts(session: Session, exam_id: int, limit: int = 12) -> list[dict]:
    rows = session.execute(
        select(Alert.district,
               func.count(Alert.id),
               func.sum(case((Alert.severity == "Critical", 1), else_=0)))
        .where(Alert.exam_id == exam_id, Alert.district != "")
        .group_by(Alert.district)
        .order_by(func.count(Alert.id).desc())
        .limit(limit)
    ).all()
    return [{"district": d, "count": n, "critical": int(c or 0)} for d, n, c in rows]
