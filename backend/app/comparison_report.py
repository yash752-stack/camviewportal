"""Combined multi-modality report — graph-first, weighted by severity.

Page 1 is the combined picture of every selected AI model: their severity
WEIGHT (4*critical+3*high+2*elevated+1*normal centres), severity composition,
and alert volume — all graphs, no prose. Then each model, ordered heaviest
first, gets up to two pages: a graph dashboard and an evidence page. Reuses the
trunk report's chrome via event_report so the whole family looks identical.
"""
from __future__ import annotations

from . import event_report as EV
from .comp_report import _page, esc
from .geo import choropleth

TIER, TNAME = EV.TIER, EV.TNAME


def _kpi(cells):
    return ('<div class="bstrip">' + "".join(
        f'<div class="bstat"><div class="bn">{v}</div><div class="bl">{k}</div></div>' for v, k in cells)
        + '</div>')


def _finding(p: dict) -> str:
    """One-line finding in the modality's OWN terms — what the client asks of it."""
    code, c, crit, comp = p.get("code", ""), p["centres"], p["crit"], p.get("compliance")
    if comp:
        a, o = comp.get("arr"), comp.get("opn")
        parts = []
        if a:
            parts.append(f'arrival <b>{a["pct"]}%</b> in window ({a["late"]} late, {a["early"]} early)')
        parts.append(f'opening <b>{o["pct"]}%</b> in window ({o["late"]} late)' if o else 'opening not captured')
        return " · ".join(parts)
    return {
        "INM": f'<b>{crit}</b> centres held 75 min+ sustained inactivity' if crit else f'{c} centres flagged for invigilator inactivity',
        "CD": f'sustained crowd formation in <b>{c}</b> centres' + (f' · <b>{crit}</b> for 75 min+' if crit else ''),
        "NP": f'monitoring room unmanned 75 min+ at <b>{crit}</b> centres (no person)' if crit else f'no person in the monitoring room at <b>{c}</b> centres',
        "ZI": f'restricted-zone entry across <b>{c}</b> centres',
        "MD": f'phones detected in <b>{c}</b> centres',
        "CT": f'camera tampering in <b>{c}</b> centres',
    }.get(code, f'<b>{c}</b> centres detected')


def _reach(n: int, maxc: int) -> str:
    return (f'<div style="display:flex;align-items:center;gap:6px;justify-content:flex-end">'
            f'<span>{n:,}</span>'
            f'<span style="display:inline-block;width:16mm;height:7px;background:#f0f2f5;border-radius:2px;position:relative;overflow:hidden">'
            f'<span style="position:absolute;left:0;top:0;bottom:0;width:{100 * n / (maxc or 1):.0f}%;background:#5b6670"></span></span></div>')


def _minibar(sev: dict) -> str:
    tot = sum(sev.values()) or 1
    segs = "".join(f'<i style="width:{100 * sev[t] / tot:.1f}%;background:{TIER[t]}"></i>'
                   for t in ("r", "o", "y", "g") if sev[t])
    return f'<div class="mbar">{segs}</div>'


def build(exam, profs: list[dict], dt: str, geo: dict | None = None) -> str:
    # rank by REACH — the count of distinct centres that detected each model — a
    # single directly-measurable number, not a composite severity score
    profs = sorted(profs, key=lambda p: -p["centres"])
    n = len(profs)

    total_alerts = sum(p["total"] for p in profs)
    centres = len({c for p in profs for c in p["centre_codes"]})
    districts = len({d for p in profs for d, _ in p["dist"]})
    crit = sum(p["crit"] for p in profs)
    t0 = min((p["tmin_m"] for p in profs if p["tmin_m"] is not None), default=None)
    t1 = max((p["tmax_m"] for p in profs if p["tmax_m"] is not None), default=None)
    win = f"{EV.hm(t0)}–{EV.hm(t1)}" if t0 is not None else "—"

    foot = EV._foot(exam, dt, f"{n} modalities · ranked by centres detected")

    # page budget: overview + per-model (dashboard [+ evidence])
    total = 1 + sum(1 + (1 if p.get("frames") else 0) for p in profs)

    # ---- Page 1 — combined overview (graphs only) ----
    maxc = max((p["centres"] for p in profs), default=1)
    findrows = "".join(
        f'<tr><td class="fm">{esc(p["label"])}</td><td class="ff">{_finding(p)}</td>'
        f'<td class="fc">{_reach(p["centres"], maxc)}</td><td class="fb">{_minibar(p["sev"])}</td></tr>'
        for p in profs)
    findtbl = (f'<table class="findtbl"><thead><tr><th>Modality</th><th>What it found · in its own terms</th>'
               f'<th class="num">Centres</th><th>Severity mix</th></tr></thead><tbody>{findrows}</tbody></table>')
    hmap = choropleth(geo or {}, light=True, label_top=6, pulse=3, fit_full=True)
    body1 = (
        _kpi([(f"{n}", "Modalities"), (f"{centres:,}", "Centres"), (f"{districts}", "Districts"),
              (f"{crit}", "Critical centres"), (win, "Active window")])
        + f'<div style="margin-top:5mm">{findtbl}</div>'
        + EV.legend([("75 min+ sustained · or 5+ alerts", TIER["r"]),
                     ("45–74 min · or 2–4 alerts", TIER["o"]),
                     ("15–44 min · or 1 alert", TIER["y"]),
                     ("under 15 min · brief", TIER["g"])])
        + '<div class="chbox" style="margin-top:6mm">'
        + '<div class="h5">Alert concentration across the state · all selected modalities</div>'
        + f'<div class="hmapwrap" style="height:62mm">{hmap}</div>'
        + '<div class="cap" style="font-size:8.5px;color:#8a929b;margin-top:1.5mm">District colour = total alerts across the selected modalities; darker = more.</div>'
        + '</div>')
    pages = [_page(f"{exam.code} · {n} modalities", "Combined detection overview", 1, total, body1, foot)]

    # ---- Per model — dashboard (+ evidence), most widespread first ----
    pno = 2
    for p in profs:
        pages.append(_page(f"{exam.code} · {p['label']}", p["label"], pno, total,
                           EV.dashboard_body(p, kpi=True), foot))
        pno += 1
        if p.get("frames"):
            pages.append(_page(f"{p['label']} · evidence", "Evidence frames", pno, total,
                               EV.evidence_body(p["frames"][:6]), foot))
            pno += 1

    return f'<!doctype html><html><head><meta charset="utf-8"><style>{EV.CSS}</style></head><body>{"".join(pages)}</body></html>'
