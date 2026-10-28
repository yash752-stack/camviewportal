"""Combined multi-modality report — graph-first, weighted by severity.

Page 1 is the summary of every selected AI model: what each found, its alerts,
its reach, its severity mix and the page its section starts on, with the map of
all of them together. Then one numbered section per model, most widespread
first, each complete in itself: its graph dashboard, its time-of-day clocks and
its evidence frames. Photographs fall only between sections, never inside one.
Reuses the trunk report's chrome via event_report so the whole family looks
identical.
"""
from __future__ import annotations

from . import event_report as EV, iv_paper
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
            f'<span style="display:inline-block;width:16mm;height:7px;background:#EEF1F4;border-radius:2px;position:relative;overflow:hidden">'
            f'<span style="position:absolute;left:0;top:0;bottom:0;width:{100 * n / (maxc or 1):.0f}%;background:#8A97A6"></span></span></div>')


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
    # A centre that is Critical under four modalities is still ONE critical centre.
    # Summing per-modality counts double-counted it, which is how a single-centre
    # exam reported "4 CRITICAL CENTRES". Deduplicate by centre code, exactly as
    # `centres` and `districts` above already do.
    crit = len({c for p in profs for c in p.get("crit_codes", ())})
    t0 = min((p["tmin_m"] for p in profs if p["tmin_m"] is not None), default=None)
    t1 = max((p["tmax_m"] for p in profs if p["tmax_m"] is not None), default=None)
    win = f"{EV.hm(t0)}–{EV.hm(t1)}" if t0 is not None else "—"

    foot = EV._foot(exam, dt, f"{n} modalities · ranked by centres detected")

    # The report is a summary page, then one section per modality, each section
    # complete in itself: its dashboard, its time-of-day clocks, its evidence.
    def _section_pages(p) -> int:
        return 1 + (1 if p.get("clock") else 0) + (1 if p.get("frames") else 0)
    starts, pno = [], 2
    for p in profs:
        starts.append(pno)
        pno += _section_pages(p)
    total = pno - 1

    # ---- Page 1 — summary of every modality, with where its section starts ----
    maxc = max((p["centres"] for p in profs), default=1)
    findrows = "".join(
        f'<tr><td class="fm"><span class="fsec">{i}</span>{esc(p["label"])}</td><td class="ff">{_finding(p)}</td>'
        f'<td class="fc">{p["total"]:,}</td>'
        f'<td class="fc">{_reach(p["centres"], maxc)}</td><td class="fb">{_minibar(p["sev"])}</td>'
        f'<td class="fp">p.&#160;{st}</td></tr>'
        for i, (p, st) in enumerate(zip(profs, starts), 1))
    # one summary page whatever the count: rows tighten and the map shrinks
    # as modalities are added, so the map is never cut off at the foot
    tight = n > 6
    rows_mm = n * (6.05 if tight else 7.9)          # measured row heights in the rendered PDF
    map_h = min(62, max(28, round(106 - rows_mm + (3 if tight else 0))))
    findtbl = (f'<table class="findtbl{" tight" if tight else ""}"><thead><tr><th>Section · modality</th><th>What it found · in its own terms</th>'
               f'<th class="num">Alerts</th><th class="num">Centres</th><th>Severity mix</th><th class="num">Page</th></tr></thead>'
               f'<tbody>{findrows}</tbody></table>')
    hmap = choropleth(geo or {}, light=True, label_top=6, pulse=3, fit_full=True)
    body1 = (
        _kpi([(f"{n}", "Modalities"), (f"{total_alerts:,}", "Alerts"), (f"{centres:,}", "Centres"), (f"{districts}", "Districts"),
              (f"{crit}", "Critical centres"), (win, "Active window")])
        + f'<div style="margin-top:5mm">{findtbl}</div>'
        + EV.legend([("75 min+ sustained · or 5+ alerts", TIER["r"]),
                     ("45–74 min · or 2–4 alerts", TIER["o"]),
                     ("15–44 min · or 1 alert", TIER["y"]),
                     ("under 15 min · brief", TIER["g"])])
        + f'<div class="chbox" style="margin-top:{3 if tight else 6}mm">'
        + '<div class="h5">Alert concentration across the state · all selected modalities</div>'
        + f'<div class="hmapwrap" style="height:{map_h}mm">{hmap}</div>'
        + '<div class="cap" style="font-size:8.5px;color:#8B95A3;margin-top:1.5mm">District colour = total alerts across the selected modalities; darker = more.</div>'
        + '</div>')
    pages = [_page(f"{exam.code} · {n} modalities · summary", "Summary: every modality at a glance", 1, total, body1, foot)]

    # ---- Section per model — dashboard, time of day, evidence; most widespread first ----
    from .clock_chart import page_body as _tod
    firsts = []
    for i, (p, pno) in enumerate(zip(profs, starts), 1):
        kick = f"Section {i} of {n} · {p['label']}"
        firsts.append(len(pages))
        pages.append(_page(kick, p["label"], pno, total, EV.dashboard_body(p, kpi=True), foot))
        pno += 1
        if p.get("clock"):
            pages.append(_page(kick, f"{p['label']} · time of day", pno, total, _tod(p["clock"], p["label"]), foot))
            pno += 1
        if p.get("frames"):
            pages.append(_page(kick, f"{p['label']} · evidence frames", pno, total,
                               EV.evidence_body(p["frames"][:6]), foot))
            pno += 1

    # photographs: before the summary, before the first section, then the
    # cameras and the review station before later sections
    photos = {0: "hall"}
    for idx, key in zip(firsts[:3], ("monitoring", "cameras", "evidence")):
        photos[idx] = key
    cover = iv_paper.cover(exam.name, "Combined detection report",
                           f"{n} AI modalities read together: a one-page summary, then a section for each modality "
                           f"with its dashboard, its time of day and its evidence.",
                           [dt, f"{centres:,} centres · {districts} districts · {crit} critical", f"active window {win}"],
                           body=getattr(exam, "body", ""), esc=esc)
    return iv_paper.document(EV.CSS, pages, cover, photos, at=sorted(photos))
