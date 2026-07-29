"""Per-alert enrichment: severity from the registry, and a confidence stand-in.

Severity is resolved from the modality's registry default with zone escalation.
Confidence is not present in current CamView Excel exports; rather than fabricate
a measured-looking number, a deterministic value is derived from the Alarm ID and
the exam is flagged so the UI labels it as synthetic. When CamView begins exporting
a real confidence column it is read straight through and the flag clears.
"""
from __future__ import annotations

import hashlib

from .excel import RawAlert
from ..registry import Modality

_CONFIDENCE_BASE = {
    "ZI": 0.86, "MD": 0.88, "CT": 0.83, "TP": 0.81,
    "CD": 0.80, "NP": 0.78, "INM": 0.74,
}


def _digest(alarm_id: str, salt: str = "") -> int:
    return int(hashlib.md5((alarm_id + salt).encode()).hexdigest(), 16)


def synthetic_confidence(alarm: RawAlert, modality: Modality) -> float:
    base = _CONFIDENCE_BASE.get(modality.code, 0.80)
    return round(min(0.99, base + (_digest(alarm.alarm_id, "c") % 130) / 1000.0), 2)


def vault_hash(alarm: RawAlert) -> str:
    return hashlib.sha256(f"{alarm.alarm_id}:{alarm.dss_id}".encode()).hexdigest()


def evidence_id(alarm: RawAlert, modality: Modality) -> str:
    return f"EV-{modality.code}-{alarm.alarm_id.split('-')[1]}"
