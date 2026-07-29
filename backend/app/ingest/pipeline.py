"""Ingest orchestration.

Streams a workbook, resolves each row's modality by channel, enriches it, links
its evidence file and writes the result. A channel not in the shipped catalogue is
never dropped: the registry ADOPTS it as a default event modality (learned for
future exams) so the alert renders everywhere the built-in modalities do, reports
included. Newly adopted types are reported back on the result. When the create-exam
wizard passed operator decisions (channel -> "is this input-dependent?"), a Yes marks
the adopted modality `needs_code` — a flag for a developer to add a bespoke
catalogue entry, not a block on ingest.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Alert, Exam
from ..registry import SEVERITY_RANK, get_registry
from .enrich import evidence_id, synthetic_confidence, vault_hash
from .evidence import EvidenceIndex
from .excel import read_workbook

_BATCH = 2000


@dataclass
class IngestResult:
    exam_id: int
    code: str
    alert_count: int
    evidence_linked: int
    by_modality: dict[str, int] = field(default_factory=dict)
    by_severity: dict[str, int] = field(default_factory=dict)
    unmapped_channels: dict[str, int] = field(default_factory=dict)  # retained; empty now that nothing is dropped
    new_modalities: dict[str, dict] = field(default_factory=dict)    # code -> {channel,code,label,needs_code,count}
    duplicates: int = 0   # rows skipped on append because the Alarm ID already exists


def _resolve_or_adopt(registry, raw, decisions, result: "IngestResult"):
    """Resolve a row's modality, adopting (and learning) a new one when the channel
    is not yet known. Records first-seen adoptions on the result so the caller can
    tell the operator what was newly recognised."""
    modality = registry.resolve(raw.channel, raw.alarm_type)
    if modality is not None:
        return modality
    needs_code = bool(decisions.get(raw.channel)) if decisions else False
    modality = registry.adopt(raw.channel, raw.alarm_type, needs_code=needs_code)
    entry = result.new_modalities.setdefault(modality.code, {
        "channel": raw.channel or "?", "code": modality.code,
        "label": modality.display_label, "needs_code": modality.needs_code, "count": 0,
    })
    entry["count"] += 1
    entry["needs_code"] = modality.needs_code
    return modality


def _finalize_new_modalities(result: "IngestResult") -> None:
    """The adopt branch fires once per truly-new type; the true alert count for
    each lands in by_modality as its rows are built. Reconcile so callers report
    the real volume, not just the first row."""
    for code, info in result.new_modalities.items():
        info["count"] = result.by_modality.get(code, info["count"])


def _build_alert_row(raw, modality, exam_id: int, index, result: "IngestResult") -> dict:
    """Build one Alert insert-mapping from a raw row + resolved modality."""
    severity = modality.severity_for(raw.zone)
    image = index.image_for(raw.alarm_id) if index else None
    video = index.video_for(raw.alarm_id) if index else None
    if image:
        result.evidence_linked += 1
    result.by_modality[modality.code] = result.by_modality.get(modality.code, 0) + 1
    result.by_severity[severity] = result.by_severity.get(severity, 0) + 1
    return {
        "exam_id": exam_id, "alarm_id": raw.alarm_id, "evidence_id": evidence_id(raw, modality),
        "channel": raw.channel, "modality_code": modality.code, "modality_label": modality.label,
        "display_label": modality.display_label, "alarm_type_raw": raw.alarm_type,
        "severity": severity, "severity_rank": SEVERITY_RANK[severity],
        "district": raw.district.title() if raw.district else "", "state": raw.state,
        "centre_code": raw.centre_code, "centre_name": raw.centre_name.title() if raw.centre_name else "",
        "zone": raw.zone, "camera_name": raw.camera_name,
        "occurred_at": _occurred(raw), "occurred_raw": raw.timestamp_raw,
        "confidence": synthetic_confidence(raw, modality), "confidence_synthetic": True,
        "dss_id": raw.dss_id, "ticket_id": raw.ticket_id, "vault_hash": vault_hash(raw),
        "evidence_image": str(image) if image else "", "evidence_video": str(video) if video else "",
        "status": "Open", "officer": "",
    }


def _epoch_from_alarm_id(alarm_id: str) -> int | None:
    parts = alarm_id.split("-")
    if len(parts) >= 5 and parts[3].isdigit():
        return int(parts[3]) // 1000
    return None


def _occurred(alarm) -> datetime | None:
    if alarm.timestamp:
        return alarm.timestamp
    epoch = _epoch_from_alarm_id(alarm.alarm_id)
    return datetime.fromtimestamp(epoch) if epoch else None


def ingest_exam(
    session: Session,
    *,
    code: str,
    name: str,
    session_label: str,
    exam_date: date | None,
    excel_path: Path,
    evidence_root: Path | None,
    decisions: dict[str, bool] | None = None,
) -> IngestResult:
    registry = get_registry()
    index = EvidenceIndex(evidence_root) if evidence_root else None

    exam = Exam(
        code=code, name=name, session=session_label, exam_date=exam_date,
        source_filename=excel_path.name,
        evidence_root=str(evidence_root) if evidence_root else "",
    )
    session.add(exam)
    session.flush()  # assign exam.id

    result = IngestResult(exam_id=exam.id, code=code, alert_count=0, evidence_linked=0)
    batch: list[dict] = []
    seen: set[str] = set()   # Alarm ID is the unique key — the same alert exported

    def flush_batch() -> None:
        if batch:
            session.bulk_insert_mappings(Alert, batch)
            batch.clear()

    for raw in read_workbook(excel_path):
        if not raw.alarm_id or raw.alarm_id in seen:
            # twice (repeated row, overlapping exports) must count once, or every
            # statistic downstream is inflated.
            if raw.alarm_id:
                result.duplicates += 1
            continue
        modality = _resolve_or_adopt(registry, raw, decisions, result)
        seen.add(raw.alarm_id)
        batch.append(_build_alert_row(raw, modality, exam.id, index, result))
        result.alert_count += 1
        if len(batch) >= _BATCH:
            flush_batch()

    flush_batch()
    _finalize_new_modalities(result)
    exam.alert_count = result.alert_count
    exam.evidence_count = result.evidence_linked
    session.commit()
    return result


def link_evidence(session: Session, *, exam: Exam, evidence_root: Path) -> int:
    """Link frames from an evidence folder to EXISTING alerts by Alarm ID — for
    adding evidence to an exam whose alerts were ingested without it (e.g. alert
    files appended earlier, frames arriving later). Returns the number newly linked."""
    index = EvidenceIndex(evidence_root)
    linked = 0
    for a in session.execute(select(Alert).where(Alert.exam_id == exam.id)).scalars():
        if not a.evidence_image:
            img = index.image_for(a.alarm_id)
            if img:
                a.evidence_image = str(img)
                linked += 1
        if not a.evidence_video:
            vid = index.video_for(a.alarm_id)
            if vid:
                a.evidence_video = str(vid)
    exam.evidence_count = (exam.evidence_count or 0) + linked
    session.commit()
    return linked


def append_to_exam(
    session: Session,
    *,
    exam: Exam,
    excel_path: Path,
    evidence_root: Path | None,
    decisions: dict[str, bool] | None = None,
) -> IngestResult:
    """Merge another alert export (a later shift/day) into an EXISTING exam.
    Rows whose Alarm ID already exists on the exam are skipped, so re-uploading
    an overlapping file is safe and idempotent."""
    registry = get_registry()
    index = EvidenceIndex(evidence_root) if evidence_root else None
    seen = {r[0] for r in session.execute(select(Alert.alarm_id).where(Alert.exam_id == exam.id))}

    result = IngestResult(exam_id=exam.id, code=exam.code, alert_count=0, evidence_linked=0)
    batch: list[dict] = []

    def flush_batch() -> None:
        if batch:
            session.bulk_insert_mappings(Alert, batch)
            batch.clear()

    for raw in read_workbook(excel_path):
        if not raw.alarm_id or raw.alarm_id in seen:
            if raw.alarm_id:
                result.duplicates += 1
            continue
        modality = _resolve_or_adopt(registry, raw, decisions, result)
        seen.add(raw.alarm_id)
        batch.append(_build_alert_row(raw, modality, exam.id, index, result))
        result.alert_count += 1
        if len(batch) >= _BATCH:
            flush_batch()

    flush_batch()
    _finalize_new_modalities(result)
    exam.alert_count = (exam.alert_count or 0) + result.alert_count
    exam.evidence_count = (exam.evidence_count or 0) + result.evidence_linked
    if evidence_root and not exam.evidence_root:
        exam.evidence_root = str(evidence_root)
    session.commit()
    return result
