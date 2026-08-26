"""Persistence model.

An Exam owns many Alerts. An Alert is one AI detection joined to its modality,
severity, evidence path and investigation state. Investigation fields (status,
officer, reviewed) start neutral on ingest and are advanced only by operator
action, so the table is an honest record of what the AI reported plus what humans
did with it.
"""
from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (
    Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text, func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

INVESTIGATION_STATES = ("Open", "Assigned", "Under Review", "Closed")


class Exam(Base):
    __tablename__ = "exams"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    # The conducting authority (UPSSSC, UPPSC, NTA...). Distinct from the
    # exam name -- one body runs many exams, and the library colours by
    # body so an authority's exams read as a family.
    body: Mapped[str] = mapped_column(String(128), default="", index=True)
    session: Mapped[str] = mapped_column(String(64), default="")
    exam_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    source_filename: Mapped[str] = mapped_column(String(512), default="")
    evidence_root: Mapped[str] = mapped_column(String(1024), default="")
    confidence_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_count: Mapped[int] = mapped_column(Integer, default=0)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    centre_total: Mapped[int] = mapped_column(Integer, default=0)  # operator-entered true total (denominator)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())

    alerts: Mapped[list["Alert"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan"
    )
    roster: Mapped[list["OfficialCentre"]] = relationship(
        back_populates="exam", cascade="all, delete-orphan"
    )


class OfficialCentre(Base):
    """The authoritative list of exam centres, uploaded separately from the alert
    export. The alert export only contains centres that fired >=1 alert, so a
    centre that stayed silent is invisible there — this roster is the true
    denominator and lets us flag silent (no-alert) centres."""
    __tablename__ = "official_centres"

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), index=True)
    centre_code: Mapped[str] = mapped_column(String(32), default="", index=True)
    centre_name: Mapped[str] = mapped_column(String(255), default="")
    district: Mapped[str] = mapped_column(String(128), default="")
    state: Mapped[str] = mapped_column(String(64), default="")

    exam: Mapped["Exam"] = relationship(back_populates="roster")


class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = (
        Index("ix_alerts_exam_sev", "exam_id", "severity_rank"),
        Index("ix_alerts_exam_district", "exam_id", "district"),
        # Covers the dominant report query: one exam, one modality, a date range.
        # occurred_at is the third column so a day filter is served by the index
        # range itself rather than by filtering every row the first two match.
        # Supersedes a plain (exam_id, modality_code) index, which this contains
        # as a leading prefix and which both engines can use just as well.
        Index("ix_alerts_exam_modality_time", "exam_id", "modality_code", "occurred_at"),
        Index("ix_alerts_exam_status", "exam_id", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    exam_id: Mapped[int] = mapped_column(ForeignKey("exams.id", ondelete="CASCADE"), index=True)

    alarm_id: Mapped[str] = mapped_column(String(128), index=True)
    evidence_id: Mapped[str] = mapped_column(String(64), default="")
    channel: Mapped[str] = mapped_column(String(8), default="")
    modality_code: Mapped[str] = mapped_column(String(8), default="")
    modality_label: Mapped[str] = mapped_column(String(64), default="")
    display_label: Mapped[str] = mapped_column(String(64), default="")
    alarm_type_raw: Mapped[str] = mapped_column(String(128), default="")

    severity: Mapped[str] = mapped_column(String(16), default="Low")
    severity_rank: Mapped[int] = mapped_column(Integer, default=3)

    district: Mapped[str] = mapped_column(String(128), default="")
    state: Mapped[str] = mapped_column(String(64), default="")
    centre_code: Mapped[str] = mapped_column(String(32), default="", index=True)
    centre_name: Mapped[str] = mapped_column(String(255), default="")
    zone: Mapped[str] = mapped_column(String(64), default="")
    camera_name: Mapped[str] = mapped_column(String(128), default="")

    occurred_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    occurred_raw: Mapped[str] = mapped_column(String(64), default="")

    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    confidence_synthetic: Mapped[bool] = mapped_column(Boolean, default=True)

    dss_id: Mapped[str] = mapped_column(String(32), default="")
    ticket_id: Mapped[str] = mapped_column(String(32), default="")
    vault_hash: Mapped[str] = mapped_column(String(64), default="")

    evidence_image: Mapped[str] = mapped_column(String(1024), default="")
    evidence_video: Mapped[str] = mapped_column(String(1024), default="")

    status: Mapped[str] = mapped_column(String(24), default="Open")
    officer: Mapped[str] = mapped_column(String(128), default="")
    notes: Mapped[str] = mapped_column(Text, default="")

    exam: Mapped["Exam"] = relationship(back_populates="alerts")

    @property
    def has_image(self) -> bool:
        return bool(self.evidence_image)
