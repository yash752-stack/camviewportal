"""JSON API and evidence streaming.

Evidence is served by alert identity, never by raw client-supplied path: the file
is looked up from the alert record and its real path is confirmed to sit inside the
exam's registered evidence root before a byte is returned, which closes path
traversal."""
from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy.orm import Session

from ..db import get_session
from ..models import Alert
from ..queries import (
    AlertFilter, district_options, get_alert, get_exam, list_alerts,
    modality_counts, related_alerts, severity_counts, status_counts,
)

router = APIRouter(prefix="/api")

_MONTHS = ("", "Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _fmt_ts(alert: Alert) -> str:
    dt = alert.occurred_at
    if not dt:
        return alert.occurred_raw or "--"
    return f"{dt.day:02d} {_MONTHS[dt.month]} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}"


def _camera(alert: Alert) -> str:
    if alert.camera_name and not alert.camera_name.replace("_", "").isdigit():
        return alert.camera_name
    suffix = (alert.zone or "CAM").split()[0][:3].upper()
    return f"CAM-{(alert.dss_id or '0000')[-4:]}-{suffix}"


def _row(alert: Alert) -> dict:
    return {
        "id": alert.alarm_id,
        "evid": alert.evidence_id,
        "type": alert.display_label,
        "rawtype": alert.alarm_type_raw or alert.modality_label,
        "modalityCode": alert.modality_code,
        "sev": alert.severity,
        "district": alert.district,
        "centreCode": alert.centre_code,
        "centre": alert.centre_name,
        "zone": alert.zone,
        "camera": _camera(alert),
        "ts": _fmt_ts(alert),
        "conf": alert.confidence,
        "confSynthetic": alert.confidence_synthetic,
        "status": alert.status,
        "officer": alert.officer,
        "hash": alert.vault_hash[:16],
        "hasImage": bool(alert.evidence_image),
    }


def _filter_from_query(
    severity: str | None, modality: str | None, district: str | None,
    status: str | None, q: str | None, sort: str, dir: int, limit: int, offset: int,
) -> AlertFilter:
    return AlertFilter(
        severity=severity, modality=modality, district=district, status=status,
        query=q, sort=sort, direction=dir, limit=min(limit, 1000), offset=offset,
    )


@router.get("/exams/{code}/summary")
def exam_summary(code: str, session: Session = Depends(get_session)):
    exam = get_exam(session, code)
    if not exam:
        raise HTTPException(404, "exam not found")
    return {
        "code": exam.code, "name": exam.name, "session": exam.session,
        "date": exam.exam_date.isoformat() if exam.exam_date else None,
        "alertCount": exam.alert_count, "evidenceCount": exam.evidence_count,
        "confidenceSynthetic": exam.confidence_synthetic,
        "severity": severity_counts(session, exam.id),
        "status": status_counts(session, exam.id),
        "modalities": modality_counts(session, exam.id),
        "districts": district_options(session, exam.id),
    }


@router.get("/exams/{code}/alerts")
def exam_alerts(
    code: str,
    severity: str | None = None, modality: str | None = None,
    district: str | None = None, status: str | None = None, q: str | None = None,
    centre: str | None = None,
    sort: str = "ts", dir: int = -1, limit: int = 300, offset: int = 0,
    session: Session = Depends(get_session),
):
    exam = get_exam(session, code)
    if not exam:
        raise HTTPException(404, "exam not found")
    f = _filter_from_query(severity, modality, district, status, q, sort, dir, limit, offset)
    f.centre_code = centre
    rows, total = list_alerts(session, exam.id, f)
    return JSONResponse({"total": total, "shown": len(rows), "alerts": [_row(a) for a in rows]})


@router.get("/exams/{code}/alerts/{alarm_id:path}")
def alert_detail(code: str, alarm_id: str, session: Session = Depends(get_session)):
    exam = get_exam(session, code)
    if not exam:
        raise HTTPException(404, "exam not found")
    alert = get_alert(session, exam.id, alarm_id)
    if not alert:
        raise HTTPException(404, "alert not found")
    data = _row(alert)
    data.update({
        "alarmId": alert.alarm_id, "dssId": alert.dss_id, "ticketId": alert.ticket_id,
        "vaultHash": alert.vault_hash, "modalityLabel": alert.modality_label,
        "occurredRaw": alert.occurred_raw, "notes": alert.notes,
        "related": [_row(r) for r in related_alerts(session, alert)],
    })
    return data


@router.get("/evidence/{code}/{alarm_id:path}")
def evidence_image(code: str, alarm_id: str, session: Session = Depends(get_session)):
    exam = get_exam(session, code)
    if not exam:
        raise HTTPException(404, "exam not found")
    alert = get_alert(session, exam.id, alarm_id)
    if not alert or not alert.evidence_image:
        raise HTTPException(404, "no evidence on file")
    target = os.path.realpath(alert.evidence_image)
    root = os.path.realpath(exam.evidence_root) if exam.evidence_root else ""
    if not root or not target.startswith(root + os.sep) or not os.path.isfile(target):
        raise HTTPException(404, "evidence unavailable")
    return FileResponse(target, media_type="image/jpeg",
                        headers={"Cache-Control": "private, max-age=3600"})
