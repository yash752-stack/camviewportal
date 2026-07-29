"""Secure question-paper box (trunk) compliance — the canonical methodology.

Trunk is a COMPLIANCE archetype: the box's arrival (Trunk Placed, ch3) and
opening (Trunk Open, ch4) are measured against authorised time windows, not by
severity. The rule, identical to the shipped NEET/UPESSC reports:

  ARRIVAL  per centre per shift, the earliest Trunk Placed sighting is the
           arrival. Classified in-window / late (after) / early (before).

  OPENING  the official opening is the earliest Trunk Open AT OR AFTER the
           arrival window has ended (`arrend`). Trunk Open fires during the
           arrival/handling phase (before arrend) are box-handling noise, not
           the opening, and are discarded. The earliest qualifying open is
           classified in-window / late / early.
           Where arrival ends exactly when the opening window opens (NEET:
           13:15/13:15) an early opening is impossible by construction — "no
           box opened before its window". Where there is a gap (UPESSC:
           arrival ends 08:00, opening window 09:00) opens in the gap are early.

Repeat camera alerts for the same box collapse to the earliest. Authorised
windows are exam-level config (data/trunk_windows.json); defaults ship for
known exams. The breakdown dimension is STATE for multi-state exams, else
DISTRICT — exactly as the two reports were cut.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Alert, Exam
from .reporting import days_cond
from .settings import get_settings

_DEFAULTS: dict[str, list[dict]] = {
    "UPESSC-TGT-2026": [
        {"name": "Shift 1", "arrival": ["07:00", "08:00"], "opening": ["09:00", "09:15"]},
        {"name": "Shift 2", "arrival": ["12:30", "13:30"], "opening": ["14:00", "14:15"]},
    ],
    "NEET-2026": [
        {"name": "Single Shift", "arrival": ["10:00", "13:15"], "opening": ["13:15", "13:45"]},
    ],
}
_GENERIC = [{"name": "Single Shift", "arrival": ["07:00", "08:00"], "opening": ["09:00", "09:15"]}]


def _store() -> "Path":  # type: ignore[name-defined]
    return get_settings().data_dir / "trunk_windows.json"


def _date_key(date) -> str:
    return date.isoformat() if hasattr(date, "isoformat") else str(date)


def _split_entry(entry):
    """A stored entry is either a flat list (the exam default, legacy shape) or
    {"default": [...], "dates": {"YYYY-MM-DD": [...]}}. Return (default, per_date)."""
    if entry is None:
        return None, {}
    if isinstance(entry, list):
        return entry, {}
    return entry.get("default"), (entry.get("dates") or {})


def get_shifts(code: str, date=None) -> list[dict]:
    """Authorised shift windows for an exam. A specific date's windows win when
    configured; otherwise the exam default applies (so every existing exam and
    every unconfigured date behaves exactly as before)."""
    path = _store()
    entry = None
    if path.exists():
        entry = json.loads(path.read_text()).get(code)
    base, per = _split_entry(entry)
    if base is None:
        base = _DEFAULTS.get(code, _GENERIC)
    if date is not None:
        return per.get(_date_key(date), base)
    return base


def set_shifts(code: str, shifts: list[dict], date=None) -> None:
    """Persist shift windows for the whole exam (date=None) or for one date."""
    path = _store()
    cfg = json.loads(path.read_text()) if path.exists() else {}
    base, per = _split_entry(cfg.get(code))
    if base is None:
        base = _DEFAULTS.get(code, _GENERIC)
    if date is None:
        base = shifts
    else:
        per = {**per, _date_key(date): shifts}
    cfg[code] = {"default": base, "dates": per} if per else base
    path.write_text(json.dumps(cfg, indent=2))


def configured_dates(code: str) -> list[str]:
    """Dates that have their own window config (for the UI to surface)."""
    path = _store()
    if not path.exists():
        return []
    _, per = _split_entry(json.loads(path.read_text()).get(code))
    return sorted(per.keys())


def _m(hhmm: str) -> int:
    h, mn = hhmm.split(":")
    return int(h) * 60 + int(mn)


def hm(x: int) -> str:
    x = int(round(x))
    return f"{x // 60:02d}:{x % 60:02d}"


def _nearest(tmin: int, shifts: list[dict], kind: str) -> dict:
    best, bd = shifts[0], 10 ** 9
    for sh in shifts:
        s, e = _m(sh[kind][0]), _m(sh[kind][1])
        d = 0 if s <= tmin <= e else min(abs(tmin - s), abs(tmin - e))
        if d < bd:
            bd, best = d, sh
    return best


def _agg(recs: list[dict]) -> dict:
    t = len(recs)
    inw = sum(1 for r in recs if r["cls"] == "in")
    return {"n": t, "inw": inw,
            "late": sum(1 for r in recs if r["cls"] == "late"),
            "early": sum(1 for r in recs if r["cls"] == "early"),
            "pct": round(100 * inw / t) if t else 0}


def _by_dim(recs: list[dict], dim: str) -> list[dict]:
    g: dict[str, list[int]] = {}
    for r in recs:
        k = r.get(dim) or "—"
        a = g.setdefault(k, [0, 0])
        a[0] += 1
        a[1] += 1 if r["cls"] == "in" else 0
    out = [{"name": k, "n": v[0], "inw": v[1], "pct": round(100 * v[1] / v[0]) if v[0] else 0}
           for k, v in g.items()]
    out.sort(key=lambda x: (x["pct"], -x["n"]))
    return out


def centre_deviations(session: Session, exam: Exam, days=None) -> dict[str, dict]:
    """Per-centre trunk arrival & opening deviation from the authorised window.

    Returns {centre_code: {"arr": {...}|None, "opn": {...}|None}}. Each entry
    carries signed deviation minutes (`dev`: + = late, - = early, 0 = in-window),
    the classification, the window string and the actual sighting time — the same
    arrend rule as compute() (opens before the arrival window ends are box-handling
    noise, discarded). When a centre spans several shifts/days the worst (largest
    |dev|) is kept, so the inspector shows the most serious deviation.
    """
    _cache: dict = {}

    def shifts_for(d):
        if d not in _cache:
            _cache[d] = get_shifts(exam.code, d)
        return _cache[d]

    rows = session.execute(
        select(Alert.modality_code, Alert.centre_code, Alert.occurred_at)
        .where(Alert.exam_id == exam.id, Alert.modality_code.in_(["TP", "TO"]),
               Alert.occurred_at.is_not(None), *days_cond(days))
    ).all()

    arr_first: dict[tuple, dict] = {}
    opn_first: dict[tuple, dict] = {}
    for mod, cc, ts in rows:
        shifts = shifts_for(ts.date())
        tmin = ts.hour * 60 + ts.minute
        if mod == "TP":
            sh = _nearest(tmin, shifts, "arrival")
            key = (cc, ts.date(), sh["name"])
            cur = arr_first.get(key)
            if cur is None or tmin < cur["tmin"]:
                arr_first[key] = {"centre": cc, "tmin": tmin, "ts": ts, "win": sh["arrival"]}
        else:
            sh = _nearest(tmin, shifts, "opening")
            if tmin < _m(sh["arrival"][1]):
                continue
            key = (cc, ts.date(), sh["name"])
            cur = opn_first.get(key)
            if cur is None or tmin < cur["tmin"]:
                opn_first[key] = {"centre": cc, "tmin": tmin, "ts": ts, "win": sh["opening"]}

    def classify(rec: dict) -> dict:
        s, e = _m(rec["win"][0]), _m(rec["win"][1])
        t = rec["tmin"]
        if s <= t <= e:
            cls, dev = "in", 0
        elif t > e:
            cls, dev = "late", t - e
        else:
            cls, dev = "early", t - s
        return {"dev": dev, "cls": cls, "window": f"{rec['win'][0]}–{rec['win'][1]}",
                "actual": rec["ts"].strftime("%H:%M:%S")}

    out: dict[str, dict] = {}
    for kind, store in (("arr", arr_first), ("opn", opn_first)):
        for rec in store.values():
            d = classify(rec)
            slot = out.setdefault(rec["centre"], {})
            if slot.get(kind) is None or abs(d["dev"]) > abs(slot[kind]["dev"]):
                slot[kind] = d
    return out


def compute(session: Session, exam: Exam, days=None) -> dict:
    shifts = get_shifts(exam.code)          # exam default — used for shift ordering
    _cache: dict = {}

    def shifts_for(d):
        if d not in _cache:
            _cache[d] = get_shifts(exam.code, d)
        return _cache[d]

    rows = session.execute(
        select(Alert.modality_code, Alert.centre_code, Alert.centre_name,
               Alert.district, Alert.state, Alert.occurred_at, Alert.alarm_id)
        .where(Alert.exam_id == exam.id, Alert.modality_code.in_(["TP", "TO"]),
               Alert.occurred_at.is_not(None), *days_cond(days))
    ).all()

    alarms = len(rows)
    all_min = [r[5].hour * 60 + r[5].minute for r in rows]
    cctv = f"{hm(min(all_min))}–{hm(max(all_min))}" if all_min else ""

    # earliest qualifying sighting per centre/day/shift
    arr_first: dict[tuple, dict] = {}
    opn_first: dict[tuple, dict] = {}
    awo = 0  # opens during the arrival/handling phase — discarded
    for mod, cc, cn, dist, state, ts, alarm in rows:
        day_shifts = shifts_for(ts.date())
        tmin = ts.hour * 60 + ts.minute
        rec = {"centre": cc, "name": cn or cc, "district": dist or "", "state": state or "",
               "tmin": tmin, "ts": ts, "alarm": alarm}
        if mod == "TP":
            sh = _nearest(tmin, day_shifts, "arrival")
            key = (cc, ts.date(), sh["name"])
            cur = arr_first.get(key)
            if cur is None or tmin < cur["tmin"]:
                arr_first[key] = {**rec, "shift": sh, "win": sh["arrival"]}
        else:
            sh = _nearest(tmin, day_shifts, "opening")
            arrend = _m(sh["arrival"][1])
            if tmin < arrend:
                awo += 1
                continue
            key = (cc, ts.date(), sh["name"])
            cur = opn_first.get(key)
            if cur is None or tmin < cur["tmin"]:
                opn_first[key] = {**rec, "shift": sh, "win": sh["opening"]}

    def classify(rec: dict) -> dict:
        s, e = _m(rec["win"][0]), _m(rec["win"][1])
        t = rec["tmin"]
        if s <= t <= e:
            cls, dev = "in", 0
        elif t > e:
            cls, dev = "late", t - e
        else:
            cls, dev = "early", t - s
        return {**rec, "cls": cls, "dev": dev,
                "window": f"{rec['win'][0]}–{rec['win'][1]}"}

    arrivals = [classify(r) for r in arr_first.values()]
    openings = [classify(r) for r in opn_first.values()]

    states_present = {r["state"] for r in arrivals if r["state"]}
    dim = "state" if len(states_present) > 1 else "district"

    def vio_list(recs: list[dict], kind: str) -> list[dict]:
        out = []
        for r in recs:
            if r["cls"] == "in":
                continue
            label = ("Late arrival" if kind == "arr" else "Late opening") if r["cls"] == "late" \
                else ("Early arrival" if kind == "arr" else "Early opening")
            out.append({"kind": label, "cls": r["cls"], "centre": r["name"], "code": r["centre"],
                        "district": r["district"], "state": r["state"],
                        "window": r["window"], "actual": r["ts"].strftime("%H:%M:%S"),
                        "date": r["ts"].strftime("%d %b"), "shift": r.get("shift", {}).get("name", ""),
                        "time_hm": hm(r["tmin"]), "dev": r["dev"], "alarm": r["alarm"],
                        "tmin": r["tmin"]})
        return out

    arr_vios = vio_list(arrivals, "arr")
    opn_vios = vio_list(openings, "opn")
    queue = sorted(arr_vios + opn_vios, key=lambda e: abs(e["dev"]), reverse=True)

    def hist15(recs: list[dict]) -> dict:
        h: dict[int, int] = {}
        for r in recs:
            b = (r["tmin"] // 15) * 15
            h[b] = h.get(b, 0) + 1
        return h

    def by_shift(recs: list[dict]) -> list[dict]:
        order = [s["name"] for s in shifts]
        g: dict[str, dict] = {}
        for r in recs:
            sn = r["shift"]["name"]
            a = g.setdefault(sn, {"name": sn, "n": 0, "inw": 0, "late": 0, "early": 0,
                                  "win": f'{r["win"][0]}–{r["win"][1]}'})
            a["n"] += 1
            a["inw" if r["cls"] == "in" else r["cls"]] += 1
        out = list(g.values())
        for a in out:
            a["pct"] = round(100 * a["inw"] / a["n"]) if a["n"] else 0
        out.sort(key=lambda a: order.index(a["name"]) if a["name"] in order else 99)
        return out

    arr_agg, opn_agg = _agg(arrivals), _agg(openings)
    arr_agg["by_dim"] = _by_dim(arrivals, dim)
    opn_agg["by_dim"] = _by_dim(openings, dim)
    arr_agg["by_shift"] = by_shift(arrivals)
    opn_agg["by_shift"] = by_shift(openings)
    arr_agg["vios"] = arr_vios
    opn_agg["vios"] = opn_vios
    opn_agg["arrived"] = len(arrivals)

    # Opening COVERAGE vs COMPLIANCE — kept strictly separate. Every box that
    # arrived in a shift is *expected* to open in that shift; an opening is only
    # *captured* when a qualifying Trunk-Open fires within camera coverage (some
    # never do — model miss, or the CCTV feed ended before the box opened). The
    # in-window percentage is computed over CAPTURED openings only; uncaptured
    # openings are disclosed, never counted as violations (they are not).
    # Match openings to arrivals by (centre, date, shift) and report EXACTLY what was
    # observed — never a net figure. Three disjoint groups: boxes with both events,
    # boxes that arrived but whose opening was never captured, and openings detected
    # for a box whose arrival was never captured (orphan). The old net "arrived −
    # captured" silently cancelled orphans against genuine gaps.
    def _key(r):
        return (r["centre"], r["ts"].date(), r["shift"]["name"])
    arr_keys = {_key(r) for r in arrivals}
    opn_keys = {_key(r) for r in openings}
    arr_only = arr_keys - opn_keys          # arrived, opening NOT captured
    opn_only = opn_keys - arr_keys          # opening captured, arrival NOT captured
    from collections import Counter as _Counter
    arr_only_sh = _Counter(k[2] for k in arr_only)
    orphan_sh = _Counter(k[2] for k in opn_only)

    arr_shift_n = {a["name"]: a["n"] for a in arr_agg["by_shift"]}
    for so in opn_agg["by_shift"]:
        so["expected"] = arr_shift_n.get(so["name"], 0)
        so["orphans"] = orphan_sh.get(so["name"], 0)
        so["uncaptured"] = arr_only_sh.get(so["name"], 0)   # arrivals with NO opening
        so["matched"] = so["n"] - so["orphans"]
    opn_agg["captured"] = opn_agg["n"]
    opn_agg["expected"] = opn_agg["arrived"]
    opn_agg["matched"] = len(arr_keys & opn_keys)
    opn_agg["uncaptured"] = len(arr_only)                   # TRUE not-observed
    opn_agg["orphans"] = len(opn_only)                      # opened, arrival not seen

    centres = len({r["centre"] for r in arrivals + openings})
    districts = len({r["district"] for r in arrivals + openings if r["district"]})
    states = len(states_present)
    dates = sorted({r["ts"].date() for r in arrivals + openings})

    return {
        "shifts": shifts, "dim": dim,
        "arrival": arr_agg, "opening": opn_agg,
        "arr_hist": hist15(arrivals), "opn_hist": hist15(openings),
        "queue": queue, "awo": awo,
        "centres": centres, "districts_n": districts, "states_n": states,
        "dates": dates, "alarms": alarms, "cctv": cctv,
        "has_opening": len(openings) > 0,
        # legacy keys kept for any caller still reading the old shape
        "districts": arr_agg["by_dim"], "exceptions": queue,
    }
