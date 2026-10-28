"""The time-of-day clock from the manager's report.

Each shift gets its own 12-hour clock face. The exam window is a shaded wedge
on the face, and every 30-minute slot of the window is a line pointing out from
the centre: the longer the line, the more alerts fired in that slot. All the
clocks in one report share a scale, so line lengths compare across shifts.

Counted the way the shift comparisons count (exam_rules.Rec.counts): exam
alerts inside the exam window, warehouse alerts placed in the same slots.
Setup alerts before the exam are left off the clock and reported in the text.
"""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from html import escape as _esc

SHIFT_COLOURS = ("#3B5877", "#B07A2A", "#7189A4", "#8A97A6")
INK, MUTE, LINE = "#1E2A3D", "#8B95A3", "#D5DAE0"
SLOT = 30
LIST_MAX = 12          # slots listed beside a clock; longer windows list their busiest


def colour(shift: int) -> str:
    return SHIFT_COLOURS[(int(shift) - 1) % len(SHIFT_COLOURS)]


def hm12(m: int) -> str:
    h, mm = divmod(int(m) % 1440, 60)
    return f"{h % 12 or 12}:{mm:02d} {'AM' if h < 12 else 'PM'}"


def time_of_day(session, exam, codes, days=None, centre: str | None = None,
                district: str | None = None, by: str | None = None) -> dict | None:
    """Per shift: the exam window and the alerts in each of its 30-minute slots,
    with what makes each slot up (`by` = "centre" or "type"; default centre for
    one alert type, type for several). None when nothing lands on a clock."""
    from . import exam_rules as X
    recs = X.exam_records(session, exam, days)
    if not recs:
        return None
    windows = X.windows_for(exam.code, recs)
    if days:
        keep = {str(d)[:10] for d in days}
        windows = [w for w in windows if w.date.isoformat() in keep]
    if not windows:
        return None
    X.assign(recs, windows)
    codes = set(codes)
    by = by or ("type" if len(codes) > 1 else "centre")
    dist = (district or "").strip().lower()
    sel = [r for r in recs if r.code in codes
           and (centre is None or r.centre_code == centre)
           and (not dist or (r.district or "").strip().lower() == dist)]
    wmap = {(w.date, w.shift): w for w in windows}
    rep: dict[int, X.Window] = {}
    for w in sorted(windows, key=lambda w: w.date):
        rep.setdefault(w.shift, w)               # the clock shows the shift's first day
    slots: dict[int, Counter] = defaultdict(Counter)
    parts: dict[tuple, Counter] = defaultdict(Counter)
    setup: Counter = Counter()
    for r in sel:
        w = wmap.get((r.day, r.shift))
        if w is None:
            continue
        if r.phase == "pre" and r.sector == "exam":
            setup[r.shift] += 1
            continue
        if not r.counts or not (w.start <= r.minute < w.end):
            continue
        i = (r.minute - w.start) // SLOT
        slots[r.shift][i] += 1
        parts[(r.shift, i)][(r.label if by == "type" else (r.centre_name or r.centre_code))] += 1
    out = []
    for s in sorted(rep):
        w = rep[s]
        n = max(1, math.ceil((w.end - w.start) / SLOT))
        vals = [slots[s].get(i, 0) for i in range(n)]
        pk = max(range(n), key=lambda i: vals[i]) if any(vals) else None
        out.append({"shift": s, "start": w.start, "end": w.end, "label": f"{hm12(w.start)} to {hm12(w.end)}",
                    "slots": [{"m": w.start + i * SLOT, "n": v, "top": parts[(s, i)].most_common(3)}
                              for i, v in enumerate(vals)],
                    "peak": pk, "peak_n": vals[pk] if pk is not None else 0,
                    "peak_at": hm12(w.start + pk * SLOT) if pk is not None else "",
                    "total": sum(vals), "setup": setup.get(s, 0), "days": len({w2.date for w2 in windows if w2.shift == s})})
    if not any(x["total"] for x in out):
        return None
    return {"shifts": out, "by": by, "mx": max(v["n"] for x in out for v in x["slots"]) or 1,
            "total": sum(x["total"] for x in out)}


# ── drawing ─────────────────────────────────────────────────────────────────
def _pt(m: float, r: float, cx=150.0, cy=150.0) -> tuple[float, float]:
    a = ((m % 720) / 720) * 2 * math.pi - math.pi / 2
    return cx + math.cos(a) * r, cy + math.sin(a) * r


def clock_svg(sh: dict, mx: int, size: str = "100%") -> str:
    """One shift's 12-hour clock: shaded exam-window wedge, hour numerals (the
    window's hours bold in the shift colour), one line per 30-minute slot."""
    cx = cy = 150
    ro, ri = 116, 38
    col = colour(sh["shift"])
    st, en = sh["start"], sh["end"]
    span = max(SLOT, min(en - st, 719))
    f = lambda p: f"{p[0]:.1f},{p[1]:.1f}"  # noqa: E731
    p1, p2, p3, p4 = _pt(st, ri), _pt(st, ro), _pt(st + span, ro), _pt(st + span, ri)
    big = 1 if span > 360 else 0
    s = [f'<path d="M{f(p1)} L{f(p2)} A{ro} {ro} 0 {big} 1 {f(p3)} L{f(p4)} A{ri} {ri} 0 {big} 0 {f(p1)} Z" '
         f'fill="{col}" fill-opacity="0.10"/>',
         f'<circle cx="{cx}" cy="{cy}" r="{ro}" fill="none" stroke="{LINE}"/>',
         f'<circle cx="{cx}" cy="{cy}" r="{ri}" fill="none" stroke="{LINE}"/>']
    lo = st % 720
    for n in range(12):
        m = n * 60
        on = (lo <= m <= lo + span) or (lo <= m + 720 <= lo + span)
        x, y = _pt(m, ro + 15)
        s.append(f'<text x="{x:.1f}" y="{y + 4:.1f}" text-anchor="middle" '
                 f'style="font-size:{15 if on else 13}px;font-weight:{700 if on else 400};fill:{col if on else MUTE}">{n or 12}</text>')
    for i, v in enumerate(sh["slots"]):
        if not v["n"]:
            continue
        m = st + i * SLOT + SLOT / 2
        a, b = _pt(m, ri + 2), _pt(m, ri + 2 + (v["n"] / mx) * (ro - ri - 4))
        w = 9 if len(sh["slots"]) <= 12 else 6
        s.append(f'<line x1="{a[0]:.1f}" y1="{a[1]:.1f}" x2="{b[0]:.1f}" y2="{b[1]:.1f}" stroke="{col}" '
                 f'stroke-width="{w}" stroke-linecap="round"><title>{hm12(v["m"])} to {hm12(v["m"] + SLOT)}: {v["n"]} alerts</title></line>')
    if sh["peak"] is not None:
        s.append(f'<text x="{cx}" y="{cy - 3}" text-anchor="middle" style="font-size:12px;font-weight:700;fill:{INK}">Peak</text>'
                 f'<text x="{cx}" y="{cy + 13}" text-anchor="middle" style="font-size:12px;font-weight:700;fill:{col}">{sh["peak_at"].replace(" ", "&#160;")}</text>')
    return (f'<svg viewBox="0 0 300 300" width="{size}" xmlns="http://www.w3.org/2000/svg" '
            f'style="font-family:inherit;display:block">{"".join(s)}</svg>')


def _slot_list(sh: dict) -> str:
    col = colour(sh["shift"])
    rows = list(enumerate(sh["slots"]))
    note = ""
    if len(rows) > LIST_MAX:
        keep = {i for i, _ in sorted(rows, key=lambda t: -t[1]["n"])[:LIST_MAX]}
        rows = [t for t in rows if t[0] in keep]
        note = f'<div class="tod-more">Busiest {LIST_MAX} of {len(sh["slots"])} slots.</div>'
    li = "".join(
        f'<div class="tod-row"><b style="color:{col}">{hm12(v["m"])} to {hm12(v["m"] + SLOT)}</b>'
        f'<span class="tod-n"> · {v["n"]:,} alert{"s" if v["n"] != 1 else ""}</span>'
        + (f'<br><span class="tod-top">{_esc(", ".join(f"{k} {n}" for k, n in v["top"]))}</span>' if v["top"] else "")
        + '</div>' for _, v in rows)
    return li + note


CSS = """
.tod{display:grid;gap:6mm 9mm;margin-top:2mm}
.tod-sh{min-width:0}
.tod-hd{display:flex;align-items:center;gap:2mm;font-weight:600;font-size:9px;color:#1E2A3D;margin-bottom:2mm}
.tod-hd i{width:3mm;height:3mm;border-radius:1px;display:inline-block}
.tod-body{display:grid;grid-template-columns:80mm 1fr;gap:5mm;align-items:start}
.tod-row{padding:1.4mm 0;border-bottom:.4pt solid #E6EAEE;font-size:8.5px;line-height:1.4}
.tod-n{color:#8B95A3}
.tod-top{color:#4A5565;font-size:8px}
.tod-more{font-size:7px;color:#8B95A3;margin-top:1mm}
.tod-note{font-size:8.5px;color:#4A5565;margin-bottom:4mm;max-width:240mm;line-height:1.45}
.tod-take{margin-top:4mm;font-size:8.5px;color:#1E2A3D;border-left:2px solid #B6403A;padding:1mm 0 1mm 3mm;line-height:1.45}
"""


def take(data: dict) -> str:
    sh = [x for x in data["shifts"] if x["total"]]
    parts = [f'Shift {x["shift"]} peaks in the slot starting <b>{x["peak_at"]}</b> with {x["peak_n"]:,} '
             f'alert{"s" if x["peak_n"] != 1 else ""}' for x in sh]
    s = (" and ".join(parts) + ".") if parts else ""
    setup = [x for x in data["shifts"] if x["setup"]]
    if setup:
        s += (" Setup alerts before the exam are left out here: "
              + " and ".join(f'{x["setup"]:,} before Shift {x["shift"]}' for x in setup) + ".")
    return s


def page_body(data: dict, subject: str = "") -> str:
    """The report page: one clock and its slot list per shift, side by side."""
    n = len(data["shifts"])
    what = "alert types" if data["by"] == "type" else "centres"
    multi = any(x["days"] > 1 for x in data["shifts"])
    note = (f'{_esc(subject) + " alerts" if subject else "Alerts"} in each 30-minute slot of the exam windows, placed on '
            f'each shift\'s own 12-hour clock. The shaded wedge is the exam window; each line is one slot, and the '
            f'longer the line, the more alerts. Every clock uses the same scale, so line lengths can be compared. '
            f'Setup alerts before the exam starts are not included. Beside each clock: the alerts in every slot and '
            f'the {what} that make it up.'
            + (" Days are added together; each shift is drawn on its first day's window." if multi else ""))
    cols = "1fr 1fr" if n >= 2 else "1fr"
    cells = "".join(
        f'<div class="tod-sh"><div class="tod-hd"><i style="background:{colour(x["shift"])}"></i>'
        f'Shift {x["shift"]} · exam window {x["label"]}</div>'
        f'<div class="tod-body"><div>{clock_svg(x, data["mx"])}</div><div>{_slot_list(x)}</div></div></div>'
        for x in data["shifts"])
    return (f'<style>{CSS}</style><div class="tod-note">{note}</div>'
            f'<div class="tod" style="grid-template-columns:{cols}">{cells}</div>'
            f'<div class="tod-take">{take(data)}</div>')
