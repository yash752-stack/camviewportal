"""Event-modality report engine — gold (trunk) chrome, graph-first.

Builds the per-AI-model graph dashboard used by BOTH the single-modality event
report and the combined report's per-modality sections. Reuses the trunk
report's exact chrome (comp_report.CSS + helpers) so every report in the family
looks identical. Facts as graphs, not prose.

A modality's WEIGHT is a severity-weighted centre score:
    weight = 4*critical + 3*high + 2*elevated + 1*normal   (centre counts)
Modalities are ordered heaviest-first in the combined report.
"""
from __future__ import annotations

from .comp_report import CSS as KCSS, donut, vbars, wave, legend, _page, esc, hm, _LOGO_IMG
from .geo import choropleth

TIER = {"r": "#C4553F", "o": "#C07A46", "y": "#A8955C", "g": "#4E8279"}
TNAME = {"r": "Critical", "o": "High", "y": "Elevated", "g": "Normal"}
INK, MUT = "#16202b", "#6a737d"

# a little extra CSS on top of the trunk chrome (severity dots, dashboard grid)
EXTRA = """
.chbox{min-width:0}
.dnwrap{display:flex;flex-direction:column;align-items:center;justify-content:center}
.dnwrap .legend{justify-content:center;margin-top:3mm}
.sd{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:6px;vertical-align:0}
.wbar text{font-family:system-ui}
.skkey{display:flex;flex-wrap:wrap;gap:3mm 6mm;justify-content:center;margin-top:3.5mm}
.skitem{display:flex;align-items:flex-start;gap:5px}
.skdot{width:9px;height:9px;border-radius:50%;margin-top:1.5px;flex:0 0 auto}
.skname{font-size:9.5px;font-weight:700;color:#33404d;line-height:1.15}
.skdef{font-size:8px;color:#8a929b;line-height:1.2}
.dash2x2{height:100%;display:flex;flex-direction:column;gap:6mm}
.qrow{flex:1 1 0;min-height:0;align-items:stretch}
.dash2x2 .chbox{display:flex;flex-direction:column;min-height:0;overflow:hidden}
.qfill{flex:1;min-height:0;display:flex;flex-direction:column;justify-content:center}
.dnwrap.qfill{align-items:center}
.hmapwrap{flex:1;min-height:0;display:flex;align-items:center;justify-content:center;background:#fafbfc;border:1px solid #e7eaee;border-radius:2px;overflow:hidden;padding:2mm}
.hmapwrap svg{width:100%;height:100%}
.cmpbox{margin-top:1mm}
.cmprow{display:flex;align-items:center;gap:7px;margin:0 0 5px}
.cmplab{flex:0 0 38mm;font-size:9px;color:#33404d;text-align:right;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.cmplab.self{font-weight:700;color:#16202b}
.cmptk{flex:1;height:13px;background:#f0f2f5;position:relative;border-radius:1px}
.cmpfl{height:100%;border-radius:1px}
.cmpvn{flex:0 0 auto;font-size:9px;font-family:ui-monospace;color:#16202b;min-width:13mm}
.svpanel{display:flex;align-items:center;justify-content:center;gap:8mm;width:100%}
.svdonut{flex:0 0 auto}
.svlist{display:flex;flex-direction:column;gap:2.8mm}
.svrow{display:flex;align-items:center;gap:7px}
.svrow .svdot{width:10px;height:10px;border-radius:50%;flex:0 0 auto}
.svrow .svn{font-family:ui-monospace;font-size:15px;font-weight:700;color:#16202b;min-width:8mm;text-align:right}
.svrow .svm{font-size:9px;color:#5b6670}
.dashwrap{height:100%;display:flex;flex-direction:column}
.dashlead{font-size:10px;color:#5b6670;line-height:1.5;margin-bottom:4mm;flex:none;max-width:182mm}
.dashwrap .dash2x2{flex:1;min-height:0;height:auto}
.findtbl{width:100%;border-collapse:collapse;font-size:10.5px}
.findtbl th{text-align:left;font-size:8px;letter-spacing:.08em;text-transform:uppercase;color:#8a929b;font-weight:600;padding:0 6px 5px;border-bottom:1px solid #e7eaee}
.findtbl th.num{text-align:right}
.findtbl td{padding:7px 6px;border-bottom:1px solid #eef1f4;vertical-align:middle}
.findtbl td.fm{font-weight:700;color:#16202b;white-space:nowrap}
.findtbl td.ff{color:#33404d}
.findtbl td.fc{text-align:right;font-family:ui-monospace;font-weight:700;color:#16202b}
.findtbl td.fb{width:42mm}
.mbar{display:flex;height:9px;border-radius:2px;overflow:hidden;background:#f0f2f5}
.mbar i{display:block;height:100%}
"""
CSS = KCSS + EXTRA


def weight(sev: dict) -> int:
    return 4 * sev["r"] + 3 * sev["o"] + 2 * sev["y"] + 1 * sev["g"]


def hbar_val(items, unit=""):
    """Ranked horizontal bars: items = [(label, value, color)] scaled to max."""
    rowh, step, x0, plotw = 13, 18, 132, 250
    mx = max((v for _, v, _ in items), default=1) or 1
    h = max(18, len(items) * step)
    s = []
    for i, (lab, val, col) in enumerate(items):
        y = i * step
        fill = plotw * val / mx
        s.append(f'<text x="127" y="{y + 10}" text-anchor="end" font-size="8.5" fill="#33404d">{esc(lab)}</text>'
                 f'<rect x="{x0}" y="{y}" width="{plotw}" height="{rowh}" fill="#f0f2f5"/>'
                 f'<rect x="{x0}" y="{y}" width="{fill:.1f}" height="{rowh}" fill="{col}"/>'
                 f'<text x="{x0 + plotw + 5}" y="{y + 10}" font-size="8.5" font-family="ui-monospace" fill="#16202b">{val:,}{unit}</text>')
    return (f'<svg viewBox="0 0 430 {h}" width="100%" preserveAspectRatio="xMidYMid meet" '
            f'class="wbar" style="display:block">{"".join(s)}</svg>')


def stacked_pct(rows):
    """100%-stacked severity bars: rows = [(label, sev_dict)] -> compare composition."""
    rows = [r for r in rows if sum(r[1].values()) > 0]
    if not rows:
        return ""
    x0, plot, step = 150, 840, 20
    h = len(rows) * step
    s = []
    for i, (name, sv) in enumerate(rows):
        tot = sum(sv.values()) or 1
        y = i * step
        s.append(f'<text x="143" y="{y + 10}" text-anchor="end" font-size="9.5" fill="#33404d">{esc(name)}</text>')
        cur = x0
        for t in ("r", "o", "y", "g"):
            if not sv[t]:
                continue
            w = plot * sv[t] / tot
            s.append(f'<rect x="{cur:.1f}" y="{y}" width="{w:.1f}" height="13" fill="{TIER[t]}"/>')
            if w > 16:
                s.append(f'<text x="{cur + w/2:.1f}" y="{y + 9}" text-anchor="middle" font-size="8" fill="#fff" font-family="ui-monospace">{sv[t]}</text>')
            cur += w
        s.append(f'<text x="{cur + 6:.1f}" y="{y + 10}" font-size="9" font-family="ui-monospace" fill="{INK}">{tot}</text>')
    return (f'<svg viewBox="0 0 1060 {h}" width="100%" preserveAspectRatio="xMidYMid meet" style="display:block">{"".join(s)}</svg>')


def _sev_legend():
    # plain tier legend — still used by the combined report's composition panel
    return legend([(TNAME[t], TIER[t]) for t in ("r", "o", "y", "g")])


def _tier_defs(mode):
    """What each severity tier actually means for this model, spelled out so the
    words 'Critical/High/Elevated/Normal' aren't undefined."""
    if mode == "count":
        return {"r": "5+ alerts", "o": "2–4 alerts", "y": "1 alert", "g": ""}
    # sustained / sustained_count -> longest unbroken run, in minutes
    return {"r": "75 min+ sustained", "o": "45–74 min", "y": "15–44 min", "g": "under 15 min"}


def _cmp_box(cmp, self_label):
    """Co-occurrence bars: the selected model's flagged centres as the 100%
    baseline, then how many of those same centres each other model also flagged."""
    if not cmp or not cmp.get("base_n"):
        return (f'<div class="empty" style="padding:14mm 0;font-size:10px">No centre reached Critical or '
                f'High for {esc(self_label)} — nothing to cross-compare.</div>')
    base = cmp["base_n"]
    out = [f'<div class="cmprow"><div class="cmplab self">{esc(self_label)} · flagged</div>'
           f'<div class="cmptk"><div class="cmpfl" style="width:100%;background:{TIER["r"]}"></div></div>'
           f'<div class="cmpvn">{base}</div></div>']
    for lab, ov, _c in cmp["rows"]:
        w = 100 * ov / base
        out.append(f'<div class="cmprow"><div class="cmplab">{esc(lab)}</div>'
                   f'<div class="cmptk"><div class="cmpfl" style="width:{max(w, 0.6):.1f}%;background:#5b6670"></div></div>'
                   f'<div class="cmpvn">{ov}<span style="color:#9aa3ab"> · {w:.0f}%</span></div></div>')
    return f'<div class="cmpbox">{"".join(out)}</div>'


LN = "#dfe3e7"


def centre_timeline(rows, tmin_m, tmax_m):
    """Two-axis plot: Y = busiest centres (named), X = time. Each cell shaded by
    how many detections that centre had in that 15-min window."""
    if not rows or tmin_m is None or tmax_m is None:
        return '<div class="empty" style="padding:14mm 0;font-size:10px">No timeline data for this model.</div>'
    x0 = (tmin_m // 15) * 15
    x1 = ((tmax_m + 14) // 15) * 15
    bins = list(range(x0, x1 + 1, 15)) or [x0]
    nb = len(bins)
    W, gutter, rowh, top = 1040, 250, 17, 6
    cw = (W - gutter - 14) / nb
    mx = max((c for r in rows for c in r["act"].values()), default=1) or 1
    H = top + len(rows) * rowh + 22

    def X(b):
        return gutter + (b - x0) / 15 * cw

    def blue(t):
        a, z = (210, 226, 246), (10, 90, 214)
        r = round(a[0] + (z[0] - a[0]) * t)
        g = round(a[1] + (z[1] - a[1]) * t)
        bl = round(a[2] + (z[2] - a[2]) * t)
        return f"#{r:02x}{g:02x}{bl:02x}"

    s = []
    for i, r in enumerate(rows):
        y = top + i * rowh
        s.append(f'<circle cx="6" cy="{y + rowh / 2:.1f}" r="3" fill="{TIER[r["tier"]]}"/>')
        s.append(f'<text x="14" y="{y + rowh / 2 + 3:.1f}" font-size="8.3" fill="{INK}">{esc(r["name"][:32])}</text>')
        for b in bins:
            c = r["act"].get(b, 0)
            if c <= 0:
                continue
            t = (c / mx) ** 0.65
            s.append(f'<rect x="{X(b):.1f}" y="{y + 2:.1f}" width="{max(cw - 1.2, 1):.1f}" '
                     f'height="{rowh - 4:.1f}" rx="1" fill="{blue(t)}"/>')
    yax = top + len(rows) * rowh + 3
    s.append(f'<line x1="{gutter}" y1="{yax:.1f}" x2="{W - 14}" y2="{yax:.1f}" stroke="{LN}"/>')
    t = ((x0 // 60) + (1 if x0 % 60 else 0)) * 60
    while t <= x1:
        s.append(f'<text x="{X(t):.1f}" y="{yax + 11:.1f}" text-anchor="middle" font-size="7.5" fill="{MUT}">{hm(t)}</text>')
        t += 30
    return (f'<svg viewBox="0 0 {W} {H}" width="100%" preserveAspectRatio="xMidYMid meet" '
            f'style="display:block">{"".join(s)}</svg>')


def _sev_key(mode):
    # drop the tier words — just the colour dot + what it actually means
    d = _tier_defs(mode)
    order = ("r", "o", "y") if mode == "count" else ("r", "o", "y", "g")
    cells = "".join(
        f'<div class="skitem"><span class="skdot" style="background:{TIER[t]}"></span>'
        f'<div class="sktxt"><div class="skname">{d[t]}</div></div></div>'
        for t in order)
    return f'<div class="skkey">{cells}</div>'


def _kpi(P):
    cells = [
        (f"{P['total']:,}", "Alerts"), (f"{P['centres']}", "Centres"),
        (f"{P['districts']}", "Districts"), (f"{P['cameras']}", "Cameras"),
        (P["win"], "Active window"), (f"{P['crit']}", "Critical centres"),
    ]
    return ('<div class="bstrip">' + "".join(
        f'<div class="bstat"><div class="bn">{v}</div><div class="bl">{k}</div></div>' for v, k in cells)
        + '</div>')


# Per-modality framing: each lens answers a different question, so the lead line
# and all four quadrant headings are tailored — never one generic template.
FRAMING = {
    "INM": dict(lead="Sustained invigilator absence — the seat empty on camera for a continuous stretch, not a momentary blip. Ranked by how long it persisted, across how many centres.",
                sev="Centres by longest sustained absence", top="Longest unbroken absence · worst centres",
                subh="Where the seat sat empty · by camera location",
                geo="Where invigilator absence concentrated", time="When absences peaked through the day"),
    "CD": dict(lead="Sustained crowd formation — gatherings that formed and held on camera, not a momentary clustering. What matters: in how many centres, and for how long they persisted.",
               sev="Centres by sustained crowd formation", top="Longest sustained crowding · top centres",
               subh="Where crowds formed · by camera location",
               geo="Where crowding concentrated", time="When crowds formed"),
    "NP": dict(lead="No person in the monitoring room — the control room left unmanned, no one watching the feeds, for a sustained stretch. Ranked by how long it stayed unattended.",
               sev="Centres by how long the monitoring room was unmanned", top="Longest unmanned monitoring room · worst centres",
               geo="Where unmanned monitoring rooms concentrated", time="When monitoring rooms emptied"),
    "ZI": dict(lead="Restricted-zone entry — incursions into out-of-bounds areas, measured by how often and how persistently they recurred.",
               sev="Centres by restricted-zone intrusion", top="Most intrusion bursts · top centres",
               geo="Where intrusions concentrated", time="When intrusions peaked"),
    "MD": dict(lead="Mobile-phone sightings — devices detected inside the examination hall.",
               sev="Centres with phone sightings · by volume", top="Most phone sightings · top centres",
               geo="Where phone sightings concentrated", time="When phones appeared"),
    "CT": dict(lead="Camera tampering — interference with or obstruction of the surveillance feed.",
               sev="Centres with tampering · by volume", top="Most tampering alerts · top centres",
               geo="Where tampering occurred", time="When tampering occurred"),
    "TP": dict(lead="Secure question-paper box arrival — whether the trunk reached each centre inside its authorised arrival window. A window-compliance check, not an alert tally.",
               sev="Arrival window compliance", top="Worst arrival deviations · minutes off the window",
               geo="Where arrival sightings concentrated", time="When boxes arrived"),
    "TO": dict(lead="Secure box opening — whether each centre opened the trunk inside its authorised opening window. A window-compliance check, not an alert tally.",
               sev="Opening window compliance", top="Worst opening deviations · minutes off the window",
               geo="Where opening sightings concentrated", time="When boxes opened"),
}
_FRAME_DEFAULT = {
    "count": dict(lead="", sev="Centres by alert volume", top="Most alerts · top centres",
                  geo="Where it concentrated", time="When it peaked"),
    "sustained": dict(lead="", sev="Centres by sustained duration", top="Longest sustained · top centres",
                      geo="Where it concentrated", time="When it peaked"),
    "sustained_count": dict(lead="", sev="Centres by intensity", top="Most/longest bursts · top centres",
                            geo="Where it concentrated", time="When it peaked"),
}


def _frame(P):
    return FRAMING.get(P.get("code", ""), _FRAME_DEFAULT.get(P.get("mode", "count"), _FRAME_DEFAULT["count"]))


def _severity_panel(P):
    sev = P["sev"]
    TN = {"r": "Critical", "o": "High", "y": "Elevated", "g": "Normal"}
    _top = next((k for k in ("r", "o", "y", "g") if sev.get(k, 0) > 0), "g")
    dn = donut([(sev["r"], TIER["r"]), (sev["o"], TIER["o"]), (sev["y"], TIER["y"]), (sev["g"], TIER["g"])],
               size=118, center=str(sev[_top]), sub=TN[_top].lower())
    defs = _tier_defs(P["mode"])
    order = ("r", "o", "y") if P["mode"] == "count" else ("r", "o", "y", "g")
    rows = "".join(
        f'<div class="svrow"><span class="svdot" style="background:{TIER[t]}"></span>'
        f'<span class="svn">{sev.get(t, 0)}</span>'
        f'<span class="svm">{TN[t]}{(" · " + defs[t]) if defs.get(t) else ""}</span></div>' for t in order)
    return f'<div class="svpanel"><div class="svdonut">{dn}</div><div class="svlist">{rows}</div></div>'


# distinct categorical palette for camera sub-locations (NOT severity colours);
# a control-room / monitoring-room slice is forced red — that reads very
# differently from a routine hall hit.
SUBLOC_PAL = ["#0A5AD6", "#2E9E8F", "#C2410C", "#7C3AED", "#A8955C", "#94A3B8"]


def _subloc_col(i, name):
    low = (name or "").lower()
    if "control" in low or "monitor" in low:
        return TIER["r"]
    return SUBLOC_PAL[i % len(SUBLOC_PAL)]


def _subloc_panel(P):
    """Camera sub-location split (INM/CD): WHERE inside the centre the alerts fell
    — halls vs control room vs corridor — read straight off the Excel 'Camera Sub
    Location'. Donut of the top locations + a ranked list. Falls back to the
    severity donut when no sub-location was recorded."""
    sl = [(z, n) for z, n in (P.get("subloc") or []) if n > 0]
    if len(sl) < 2:
        # one location (or none) makes a meaningless "100%" donut — show the
        # duration/severity breakdown instead, which is what actually informs
        return _severity_panel(P)
    total = sum(n for _, n in sl) or 1
    items = sl[:5]
    rest = sum(n for _, n in sl[5:])
    if rest > 0:
        items = items + [("Other locations", rest)]
    segs = [(n, _subloc_col(i, z)) for i, (z, n) in enumerate(items)]
    lead = items[0]
    dn = donut(segs, size=118, center=f"{round(100 * lead[1] / total)}%", sub=lead[0][:16].lower())
    rows = "".join(
        f'<div class="svrow"><span class="svdot" style="background:{_subloc_col(i, z)}"></span>'
        f'<span class="svn">{n:,}</span>'
        f'<span class="svm">{esc(z[:24])} · {round(100 * n / total)}%</span></div>'
        for i, (z, n) in enumerate(items))
    return f'<div class="svpanel"><div class="svdonut">{dn}</div><div class="svlist">{rows}</div></div>'


def _compliance_panel(c):
    g, r, o = c["in"], c["late"], c["early"]
    dn = donut([(g, TIER["g"]), (r, TIER["r"]), (o, TIER["o"])], size=118, center=f'{c["pct"]}%', sub="in window")
    rows = [("g", g, "In window", c.get("win", "")), ("r", r, "Late", "after window"), ("o", o, "Early", "before window")]
    body = "".join(
        f'<div class="svrow"><span class="svdot" style="background:{TIER[t]}"></span>'
        f'<span class="svn">{v}</span><span class="svm">{lab}{(" · " + sub) if sub else ""}</span></div>'
        for t, v, lab, sub in rows)
    return f'<div class="svpanel"><div class="svdonut">{dn}</div><div class="svlist">{body}</div></div>'


def _deviation_bars(c):
    w = c.get("worst") or []
    if not w:
        return '<div class="empty" style="padding:11mm 0;font-size:10px">Every centre with a sighting was within its window.</div>'
    bars = hbar_val([(lab[:20], abs(dev), TIER["r"] if cls == "late" else TIER["o"]) for lab, dev, cls in w], unit=" min")
    return (bars + '<div class="cap" style="font-size:8px;color:#8a929b;margin-top:1mm">'
            '<span style="color:#C4553F">red = late</span> · <span style="color:#C07A46">amber = early</span> · bar = minutes off the window</div>')


def _na_panel(title, sub):
    return (f'<div class="qfill" style="display:flex;flex-direction:column;align-items:center;justify-content:center;text-align:center">'
            f'<div style="font-size:32px;color:#cbd2d9;line-height:1">—</div>'
            f'<div style="font-size:12px;font-weight:700;color:#33404d;margin-top:2.5mm">{title}</div>'
            f'<div style="font-size:9px;color:#8a929b;margin-top:1mm">{sub}</div></div>')


def _trunk_dashboard(P):
    """Secure-box page — BOTH arrival and opening window compliance, always, so
    opening is never silently dropped (shown 'not assessed' when no Trunk-Open)."""
    comp = P.get("compliance") or {}
    arr, opn = comp.get("arr"), comp.get("opn")
    kind = comp.get("kind", "Arrival")
    fr = _frame(P)
    q_arr = _compliance_panel(arr) if arr else _na_panel("No arrival captured", "No Trunk-Placed events in this export")
    q_opn = _compliance_panel(opn) if opn else _na_panel("No opening captured", "No Trunk-Open events in this export")
    dev_src = opn if (kind == "Opening" and opn) else arr
    q_dev = _deviation_bars(dev_src) if dev_src else '<div class="empty" style="padding:11mm 0;font-size:10px">No deviations to rank.</div>'
    hmap = choropleth(P.get("geo", {}), light=True, label_top=6, pulse=3, fit_full=True)
    hot = P["dist"][0] if P.get("dist") else None
    hotcap = (f'Hottest {P["dimlbl"]}: <b>{esc(hot[0])}</b> — {hot[1]:,} alerts.' if hot else "")
    lead = f'<div class="dashlead">{fr["lead"]}</div>' if fr.get("lead") else ""
    kl = kind.lower()
    return (
        f'<div class="dashwrap">{lead}'
        '<div class="dash2x2">'
        '<div class="qrow chgrid2">'
        f'<div class="chbox"><div class="h5">Arrival window compliance</div><div class="qfill">{q_arr}</div></div>'
        f'<div class="chbox"><div class="h5">Opening window compliance</div><div class="qfill">{q_opn}</div></div>'
        '</div>'
        '<div class="qrow chgrid2">'
        f'<div class="chbox"><div class="h5">Worst {kl} deviations · minutes off the window</div><div class="qfill">{q_dev}</div></div>'
        f'<div class="chbox"><div class="h5">Where {kl} sightings concentrated</div>'
        f'<div class="hmapwrap qfill">{hmap}</div>'
        f'<div class="cap" style="font-size:8px;color:#8a929b;margin-top:1.5mm">{hotcap} Darker = more alerts.</div></div>'
        '</div>'
        '</div></div>')


def dashboard_body(P, kpi=True):
    """Per-modality graph page — four always-populated quadrants, framed to the
    question THIS modality answers (headings + lead tailored per lens). Trunk
    modalities show full window-compliance (arrival + opening)."""
    if P.get("compliance"):
        return _trunk_dashboard(P)
    fr = _frame(P)
    # INM / CD: the first graph segregates by camera sub-location (control room vs
    # halls vs corridor); the heat map below stays geographic, as requested.
    # only break out camera sub-location when there are 2+ distinct locations —
    # a single-location "100%" donut is meaningless and misreads as a compliance figure
    use_subloc = P.get("code") in ("INM", "CD") and len([1 for _, n in (P.get("subloc") or []) if n > 0]) >= 2
    q1 = _subloc_panel(P) if use_subloc else _severity_panel(P)
    q1_head = (fr.get("subh") or fr["sev"]) if use_subloc else fr["sev"]
    tb = P.get("top_bars") or []
    q2 = (hbar_val([(lab[:20], v, c) for lab, v, c in tb], unit=P.get("metric_unit", ""))
          if tb else '<div class="empty" style="padding:12mm 0;font-size:10px">No centres detected.</div>')
    hmap = choropleth(P.get("geo", {}), light=True, label_top=6, pulse=3, fit_full=True)
    hot = P["dist"][0] if P.get("dist") else None
    hotcap = (f'Hottest {P["dimlbl"]}: <b>{esc(hot[0])}</b> — {hot[1]:,} alerts.' if hot else "")
    sp = P.get("spike"); mark = None
    if sp and sp.get("anomalous"):
        mark = (sp["min"] + 7, f'▲ {hm(sp["min"])} {esc(sp["centre"][:16])} — {sp["count"]}/15m', "#B42318")
    curve = (wave(P.get("series", {}), None, "", mark) if P.get("series")
             else '<div class="empty" style="padding:14mm 0;font-size:10px">No timed alerts for this modality.</div>')
    pkcap = (f'Peak <b>{P.get("peak_hm", "--")}</b> · {P.get("peak_v", 0):,} alerts in the busiest 15 min.'
             if P.get("peak_v") else "")
    lead = f'<div class="dashlead">{fr["lead"]}</div>' if fr.get("lead") else ""
    return (
        f'<div class="dashwrap">{lead}'
        '<div class="dash2x2">'
        '<div class="qrow chgrid2">'
        f'<div class="chbox"><div class="h5">{q1_head}</div><div class="qfill">{q1}</div></div>'
        f'<div class="chbox"><div class="h5">{fr["top"]}</div><div class="qfill">{q2}</div></div>'
        '</div>'
        '<div class="qrow chgrid2">'
        f'<div class="chbox"><div class="h5">{fr["geo"]}</div>'
        f'<div class="hmapwrap qfill">{hmap}</div>'
        f'<div class="cap" style="font-size:8px;color:#8a929b;margin-top:1.5mm">{hotcap} Darker = more alerts; same colour scale as the workspace map.</div></div>'
        f'<div class="chbox"><div class="h5">{fr["time"]}</div>'
        f'<div class="qfill">{curve}</div>'
        f'<div class="cap" style="font-size:8px;color:#8a929b;margin-top:1.5mm">{pkcap}</div></div>'
        '</div>'
        '</div></div>')


def evidence_body(frames):
    if not frames:
        return '<div class="empty">No evidence frames linked for this modality.</div>'
    cards = "".join(
        f'<div class="ecard"><div class="eimg"><img src="file://{f["img"]}">'
        f'<span class="etag">{esc(f["tag"])}</span><span class="eday">{esc(f["day"])}</span></div>'
        f'<div class="emeta"><div class="ec">{esc(f["centre"][:34])}</div>'
        f'<div class="ed"><span>{esc(f["loc"])}</span><span class="mono">{esc(f["time"])}</span></div></div></div>'
        for f in frames)
    return f'<div class="egrid2">{cards}</div>'


def _foot(exam, dt, tail):
    return (f'<div class="pf"><span>{_LOGO_IMG}</span><span>{esc(exam.name)} · {dt}</span>'
            f'<span>{tail}</span></div>')


def build_event(exam, P, frames, dt):
    """Single-modality event report: graph dashboard + paginated evidence."""
    tail = f'{P["centres"]} centres · {P["districts"]} districts'
    foot = _foot(exam, dt, tail)
    EVCAP = 6
    chunks = [frames[i:i + EVCAP] for i in range(0, len(frames), EVCAP)]
    total = 1 + max(1, len(chunks))
    kick = f"{exam.code} · {P['label']}"

    pages = [_page(kick, P["label"], 1, total, dashboard_body(P), foot)]
    if not chunks:
        pages.append(_page("Evidence", "Evidence frames", 2, total, evidence_body([]), foot))
    for ci, ch in enumerate(chunks):
        ttl = "Evidence frames" + ("" if ci == 0 else " (continued)")
        pages.append(_page(f"{P['label']} · evidence", ttl, 2 + ci, total, evidence_body(ch), foot))
    return f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>{"".join(pages)}</body></html>'
