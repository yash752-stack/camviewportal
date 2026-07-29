"""Canonical CamView modality registry.

CamView ships a bounded set of detection models, so the modality universe starts
as a closed catalogue loaded from config/modalities.json. Resolution is by the
channel code carried in the Alarm ID (stable); the alarm-type label is only a
fallback because its wording drifts between exam exports.

The catalogue is no longer a hard wall. When an exam export carries an Alarm ID
whose channel is not in the shipped catalogue, the registry ADOPTS it: a default
event modality is synthesised from the data (label taken from the Excel alarm-type
text, event archetype, Medium severity) so the alert is never dropped and renders
everywhere the built-in modalities do, including reports. Adopted modalities are
LEARNED — persisted to data/learned_modalities.json — so a given channel is only
new the first time it is ever seen; every later exam recognises it. An adopted
modality may be flagged `needs_code` when an operator judges it input-dependent
(needs bespoke handling like the trunk windows or mobile marking); that is a
signal for a developer to add a proper catalogue entry, not a block on rendering.
"""
from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass, replace
from functools import lru_cache
from pathlib import Path

from .settings import get_settings

SEVERITY_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Low": 3}

# Defaults applied to an alarm type adopted from the data (not in the shipped
# catalogue). Event archetype + Medium severity is the neutral, always-renderable
# baseline the report/dashboard layer already knows how to draw.
ADOPT_ARCHETYPE = "event"
ADOPT_SEVERITY = "Medium"


@dataclass(frozen=True)
class Modality:
    channel: str
    code: str
    evidence_folder: str
    label: str
    display_label: str
    aliases: tuple[str, ...]
    archetype: str
    default_severity: str
    escalation_zones: tuple[str, ...]
    escalation_to: str | None
    supports_window_compliance: bool
    synthetic: bool = False    # adopted from data, not in the shipped catalogue
    needs_code: bool = False   # operator-flagged as input-dependent -> wants a real catalogue entry

    def severity_for(self, zone: str | None) -> str:
        if self.escalation_to and zone and zone.strip().upper() in self.escalation_zones:
            return self.escalation_to
        return self.default_severity


def _adopt_code(channel: str, label: str) -> str:
    """A stable, catalogue-safe short code for an adopted modality. Keyed on the
    channel so the same channel always maps to the same code across exams; falls
    back to the label's letters when an Alarm ID carried no channel segment."""
    ch = re.sub(r"[^A-Za-z0-9]", "", str(channel or ""))
    if ch:
        return ("X" + ch)[:8]
    letters = re.sub(r"[^A-Za-z0-9]", "", (label or "")).upper()
    return ("X" + (letters or "NEW"))[:8]


def synthesize_modality(channel: str, label: str, *, needs_code: bool = False) -> Modality:
    """Build a default event modality for an alarm type seen in the data but absent
    from the catalogue. The label is the operator-facing name everywhere it renders."""
    clean = (label or "").strip() or (f"Channel {channel}" if channel else "New Alarm Type")
    code = _adopt_code(channel, clean)
    return Modality(
        channel=str(channel or ""),
        code=code,
        evidence_folder=code,
        label=clean,
        display_label=clean,
        aliases=(clean,) if clean else (),
        archetype=ADOPT_ARCHETYPE,
        default_severity=ADOPT_SEVERITY,
        escalation_zones=(),
        escalation_to=None,
        supports_window_compliance=False,
        synthetic=True,
        needs_code=needs_code,
    )


class Registry:
    def __init__(self, modalities: list[Modality], learned_path: Path | None = None):
        self.modalities = list(modalities)
        self._learned_path = learned_path
        self._lock = threading.Lock()
        self._reindex()

    def _reindex(self) -> None:
        self._by_channel = {m.channel: m for m in self.modalities if m.channel}
        self._by_alias = {}
        for m in self.modalities:
            for alias in m.aliases:
                self._by_alias[alias.strip().lower()] = m

    def by_channel(self, channel: str) -> Modality | None:
        return self._by_channel.get(str(channel).strip())

    def by_code(self, code: str) -> Modality | None:
        return next((m for m in self.modalities if m.code == code), None)

    def by_label(self, label: str) -> Modality | None:
        if not label:
            return None
        return self._by_alias.get(label.strip().lower())

    def resolve(self, channel: str | None, label: str | None) -> Modality | None:
        """Channel first (authoritative), label as fallback. Returns None for an
        alarm type neither the catalogue nor the learned set knows yet."""
        modality = self.by_channel(channel) if channel else None
        if modality is None:
            modality = self.by_label(label) if label else None
        return modality

    def _unique_code(self, base: str) -> str:
        codes = {m.code for m in self.modalities}
        if base not in codes:
            return base
        for i in range(2, 1000):
            cand = (base[:6] + str(i))[:8]
            if cand not in codes:
                return cand
        return base

    def adopt(self, channel: str | None, label: str | None, *, needs_code: bool = False) -> Modality:
        """Resolve an alarm type, or — if it is new — synthesise a default event
        modality for it, learn it (persist), and return it. Idempotent: the second
        row of a new type resolves to the modality the first row created. A later
        `needs_code=True` upgrades the flag on an already-adopted type."""
        with self._lock:
            existing = self.resolve(channel, label)
            if existing is not None:
                if needs_code and existing.synthetic and not existing.needs_code:
                    upgraded = replace(existing, needs_code=True)
                    self.modalities = [upgraded if m.code == existing.code else m
                                       for m in self.modalities]
                    self._reindex()
                    self._persist_learned()
                    return upgraded
                return existing
            mod = synthesize_modality(channel or "", label or "", needs_code=needs_code)
            mod = replace(mod, code=self._unique_code(mod.code),
                          evidence_folder=self._unique_code(mod.code))
            self.modalities.append(mod)
            self._reindex()
            self._persist_learned()
            return mod

    def _persist_learned(self) -> None:
        if not self._learned_path:
            return
        payload = {"modalities": [_to_json(m) for m in self.modalities if m.synthetic]}
        try:
            self._learned_path.parent.mkdir(parents=True, exist_ok=True)
            self._learned_path.write_text(json.dumps(payload, indent=2))
        except OSError:
            pass  # learning is best-effort; a read-only fs still renders in-process


def _modality_from_entry(entry: dict, *, synthetic: bool = False) -> Modality:
    esc = entry.get("severityEscalation") or {}
    return Modality(
        channel=str(entry.get("channel", "")),
        code=entry["code"],
        evidence_folder=entry.get("evidenceFolder", entry["code"]),
        label=entry.get("label", entry["code"]),
        display_label=entry.get("displayLabel", entry.get("label", entry["code"])),
        aliases=tuple(entry.get("aliases", [])),
        archetype=entry.get("archetype", ADOPT_ARCHETYPE),
        default_severity=entry.get("defaultSeverity", ADOPT_SEVERITY),
        escalation_zones=tuple(z.strip().upper() for z in esc.get("zone", [])),
        escalation_to=esc.get("to"),
        supports_window_compliance=bool(entry.get("supportsWindowCompliance", False)),
        synthetic=bool(entry.get("synthetic", synthetic)),
        needs_code=bool(entry.get("needsCode", False)),
    )


def _to_json(m: Modality) -> dict:
    return {
        "channel": m.channel, "code": m.code, "evidenceFolder": m.evidence_folder,
        "label": m.label, "displayLabel": m.display_label, "aliases": list(m.aliases),
        "archetype": m.archetype, "defaultSeverity": m.default_severity,
        "supportsWindowCompliance": m.supports_window_compliance,
        "synthetic": True, "needsCode": m.needs_code,
    }


def _load(path: Path, learned_path: Path | None = None) -> Registry:
    # The external config/modalities.json is meant to be the operator-editable
    # source of truth, but it lives outside backend/ (the folder every install
    # or fix touches), so it's the one file that can go missing without anyone
    # noticing — that used to be an unhandled FileNotFoundError deep inside
    # whatever feature happened to touch the registry first. It now falls back
    # to a bundled copy shipped alongside this file, so the app keeps working;
    # main.py's startup check separately makes the fallback loudly visible so
    # it still gets fixed, rather than silently masking a real deployment bug.
    bundled = Path(__file__).resolve().parent / "default_modalities.json"
    try:
        raw = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        import logging
        logging.getLogger("camview.registry").error(
            "Could not read modality catalogue at %s (%s: %s) — falling back to the "
            "copy bundled with the app. Reports/analysis will still work, but any "
            "custom entries in the external file won't be picked up until it's restored.",
            path, type(e).__name__, e,
        )
        raw = json.loads(bundled.read_text())
    modalities = [_modality_from_entry(e) for e in raw["modalities"]]
    registry = Registry(modalities, learned_path=learned_path)
    # merge previously learned (adopted) modalities so a channel seen in an earlier
    # exam is recognised, never re-adopted or re-prompted.
    if learned_path and learned_path.exists():
        try:
            data = json.loads(learned_path.read_text())
            known_codes = {m.code for m in registry.modalities}
            for e in data.get("modalities", []):
                m = _modality_from_entry(e, synthetic=True)
                if m.channel and m.channel in registry._by_channel:
                    continue
                if m.code in known_codes:
                    continue
                registry.modalities.append(m)
                known_codes.add(m.code)
            registry._reindex()
        except (OSError, ValueError, KeyError):
            pass
    return registry


def catalogue_status() -> dict:
    """Whether the registry is running on the external config file or the
    bundled fallback — used by the startup check so a missing config/ folder
    is caught immediately instead of surfacing later inside a random feature."""
    settings = get_settings()
    ok = settings.modalities_path.exists()
    return {"ok": ok, "path": str(settings.modalities_path),
            "bundled_fallback_active": not ok}


@lru_cache
def get_registry() -> Registry:
    settings = get_settings()
    return _load(settings.modalities_path, settings.data_dir / "learned_modalities.json")
