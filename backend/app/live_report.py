"""The live report: an examination as one animated, single-screen HTML file.

It opens on a summary of every modality, one tile each. Clicking a tile opens
that modality full-screen: the finding as the headline, the numbers, the
scatter of every centre, the district map and the time curve. Nothing scrolls;
every view fits the screen and replays its motion each time it opens. Back (or
Esc) returns to the summary, the arrow keys step between modalities, and the
address keeps the open view (#INM) so a link can point straight at one.

Colours are the house palette exactly as the PDFs and the portal use it — navy
proves, grey is context, oxide red is the one thing that matters — read from
event_report rather than redefined. Fonts are Jost, Source Serif and IBM Plex
Mono, embedded. No Innovatiview mark: a rendered report names the examination
and nothing else (the iv_paper rule).

One map is shared by every view: the district geometry is drawn once and each
view recolours it, so switching modality animates the map from one pattern to
the next and the file stays small.
"""
from __future__ import annotations

import base64
import html
import json
import re
from functools import lru_cache

from sqlalchemy import func, select

from .comp_report import INK, MUT
from .event_report import TIER, TNAME, _frame, _jit, _nice, _ticks
from .geo import choropleth
from .settings import get_settings

esc = html.escape
NAVY, RED = TIER["o"], TIER["r"]


@lru_cache(maxsize=1)
def _fonts() -> str:
    """fonts.css with every font file inlined, so the page works offline."""
    a = get_settings().assets_dir
    css = (a / "fonts.css").read_text(encoding="utf-8")

    def inline(m):
        p = a / "fonts" / m.group(1)
        if not p.exists():
            return m.group(0)
        return f'url("data:font/woff2;base64,{base64.b64encode(p.read_bytes()).decode()}")'
    return re.sub(r'url\("fonts/([^"]+)"\)', inline, css)


# ---------------------------------------------------------------- icons
# Line glyphs in the portal's own icon style (24-unit box, stroked, no fill).
# Matched on the modality's name, because the channel codes drift (X15, X17…).
_ICONS = [
    (("invigilator",), '<circle cx="9" cy="6.5" r="3"/><path d="M3 21v-2.5a6 6 0 0 1 12 0V21"/><path d="M18.5 9v6M21.5 9v6"/>'),
    (("crowd", "worker"), '<circle cx="12" cy="6" r="2.5"/><circle cx="5" cy="9" r="2"/><circle cx="19" cy="9" r="2"/><path d="M7.5 20v-2a4.5 4.5 0 0 1 9 0v2"/><path d="M1.5 19v-1.5a3.5 3.5 0 0 1 4.5-3.3M22.5 19v-1.5a3.5 3.5 0 0 0-4.5-3.3"/>'),
    (("zone", "perimeter", "intrusion"), '<path d="M4 4h16v16H4z" stroke-dasharray="3 2.4"/><path d="M1 12h11M8.5 8.5 12 12l-3.5 3.5"/>'),
    (("no person", "monitoring"), '<rect x="3" y="4" width="18" height="12" rx="1.5"/><path d="M8 20.5h8M12 16v4.5"/><path d="m4 3 16 14"/>'),
    (("trunk tamper",), '<path d="M3 10h18v10H3z"/><path d="M5 10V7h14v3"/><path d="m13 12-3 4h4l-3 4"/>'),
    (("trunk open",), '<path d="M3 12h18v8H3z"/><path d="M4 9 18 4l1 3"/><path d="M12 15v2"/>'),
    (("trunk",), '<path d="M3 10h18v10H3z"/><path d="M5 10V7h14v3"/><path d="M12 1.5v6M9.5 5 12 7.5 14.5 5"/>'),
    (("mobile", "phone"), '<rect x="7" y="2.5" width="10" height="19" rx="2"/><path d="M11 18.5h2"/>'),
    (("camera",), '<path d="M3 7h4l2-2.5h6L17 7h4v12H3z"/><circle cx="12" cy="13" r="3.5"/><path d="M2 3l20 18"/>'),
    (("cheat",), '<path d="M2 12s3.5-6.5 10-6.5S22 12 22 12s-3.5 6.5-10 6.5S2 12 2 12z"/><circle cx="15" cy="12" r="2.6"/>'),
    (("standing", "multiple"), '<circle cx="8" cy="4.5" r="2.2"/><circle cx="16" cy="4.5" r="2.2"/><path d="M8 8v7m0 0-2 6m2-6 2 6M5 10.5h6M16 8v7m0 0-2 6m2-6 2 6M13 10.5h6"/>'),
    (("fire", "smoke"), '<path d="M12 22a6 6 0 0 0 6-6c0-4-3-6-4-10-2 2-3 4-3 6-1-1-2-2-2-3.5C7 10 6 12.5 6 16a6 6 0 0 0 6 6z"/>'),
]
_ICON_DEFAULT = '<path d="M12 3 3 8l9 5 9-5-9-5z"/><path d="m3 13 9 5 9-5"/>'


def _icon(label: str) -> str:
    low = label.lower()
    body = next((g for keys, g in _ICONS if any(k in low for k in keys)), _ICON_DEFAULT)
    # pathLength=1 on every stroke so the glyph can draw itself
    body = re.sub(r"<(path|circle|rect)\b", r'<\1 pathLength="1"', body)
    return f'<svg class="ico" viewBox="0 0 24 24">{body}</svg>'


# ---------------------------------------------------------------- words
def _headline(P) -> tuple[str, str]:
    """The finding in one line, then the context. Built from the data, so a view
    leads with what happened rather than what the modality is."""
    sev, top, mode = P["sev"], (P.get("top") or [None])[0], P["mode"]
    if P["total"] == 0:
        return "No alerts were raised.", ""
    if sev["r"]:
        h = f'<b>{sev["r"]} of {P["centres"]} centres</b> reached critical'
        if top:
            h += f'; the worst, <span class="lk" data-c="{esc(top["code"])}">{esc(top["name"] or top["code"])}</span>, at {esc(top["metric"])}'
        h += "."
    elif sev["o"]:
        h = f'No centre reached critical; <b>{sev["o"]}</b> reached high.'
    else:
        h = f'All {P["centres"]} centres stayed below the high threshold.'
    sub = []
    hot = (P.get("dist") or [None])[0]
    if hot and P["total"]:
        sub.append(f'<span class="lk" data-dist="{esc(hot[0])}">{esc(hot[0])}</span> carried {round(100 * hot[1] / P["total"])}% of the alerts')
    if P.get("peak_v"):
        sub.append(f'the busiest 15 minutes began at {P["peak_hm"]}')
    line = ", and ".join(sub) + "." if sub else ""
    return h, (line[:1].upper() + line[1:]) if line else ""


def _summary_headline(profs) -> str:
    most = max(profs, key=lambda p: p["total"])
    crit = max(profs, key=lambda p: p["crit"])
    h = f'<b class="lk" data-go="{esc(most["code"])}">{esc(most["label"])}</b> raised the most alerts ({most["total"]:,})'
    if crit["crit"] and crit is not most:
        h += f'; <b class="lk" data-go="{esc(crit["code"])}">{esc(crit["label"])}</b> left the most centres critical ({crit["crit"]})'
    elif most["crit"]:
        h += f', with {most["crit"]} critical centres'
    return h + "."


# ---------------------------------------------------------------- charts
def _scatter(P) -> str:
    pts = P.get("points") or []
    if not pts:
        return '<p class="empty">No centres detected.</p>'
    mode = P["mode"]
    ylab = {"sustained": "Longest sustained run · min", "sustained_count": "Peak burst · alerts in 15 min",
            "count": "Distinct detections"}.get(mode, "Metric")
    W, H, L, R, T, B = 900, 520, 84, 26, 30, 66
    xmax, ymax = _nice(max(p[2] for p in pts) or 1), _nice(max(p[3] for p in pts) or 1)
    X = lambda v: L + v / xmax * (W - L - R)
    Y = lambda v: (H - B) - v / ymax * (H - B - T)
    s = []
    for v in _ticks(0, ymax, 5):
        s.append(f'<line class="grid" x1="{L}" y1="{Y(v):.1f}" x2="{W-R}" y2="{Y(v):.1f}"/>'
                 f'<text class="tick" x="{L-12}" y="{Y(v)+6:.1f}" text-anchor="end">{v:g}</text>')
    for v in _ticks(0, xmax, 6):
        s.append(f'<line class="grid v" x1="{X(v):.1f}" y1="{T}" x2="{X(v):.1f}" y2="{H-B}"/>'
                 f'<text class="tick" x="{X(v):.1f}" y="{H-B+28}" text-anchor="middle">{v:g}</text>')
    if mode == "count":
        for v, t, lab in ((2, "o", "2 · high"), (5, "r", "5 · critical")):
            if v < xmax:
                s.append(f'<g class="thr"><line pathLength="1" x1="{X(v):.1f}" y1="{H-B}" x2="{X(v):.1f}" y2="{T}" stroke="{TIER[t]}"/>'
                         f'<text x="{X(v)+6:.1f}" y="{T+20}" fill="{TIER[t]}">{lab}</text></g>')
    else:
        for v, t, lab in ((15, "y", "15 min · elevated"), (45, "o", "45 min · high"), (75, "r", "75 min · critical")):
            if v < ymax:
                s.append(f'<g class="thr"><line pathLength="1" x1="{L}" y1="{Y(v):.1f}" x2="{W-R}" y2="{Y(v):.1f}" stroke="{TIER[t]}"/>'
                         f'<text x="{W-R-4}" y="{Y(v)-8:.1f}" text-anchor="end" fill="{TIER[t]}">{lab}</text></g>')
    order = {"g": 0, "y": 1, "o": 2, "r": 3}
    ranked = sorted(pts, key=lambda p: (order.get(p[4], 0), p[3], p[2]))
    n = len(ranked)
    for i, (name, code, ax, ay, tier, dist) in enumerate(ranked):
        cx, cy = X(ax) + _jit(code, 0), Y(ay) + _jit(code, 1)
        r = 10 if tier == "r" else 7.5
        delay = 0.35 + 1.5 * i / max(1, n - 1)          # quiet tiers land first, critical last
        tip = esc(json.dumps({"n": name or code, "d": dist or "", "a": ax, "m": ay, "t": TNAME[tier]}))
        s.append(f'<circle class="pt t{tier}" cx="{cx:.1f}" cy="{cy:.1f}" r="{r}" fill="{TIER[tier]}" '
                 f'style="--d:{delay:.2f}s" data-tip="{tip}" data-c="{esc(code)}"/>')
    placed = []
    for name, code, ax, ay, tier, _ in sorted(list(reversed(ranked))[:5], key=lambda p: -p[3]):
        cx, cy = X(ax) + _jit(code, 0), Y(ay) + _jit(code, 1)
        ty = cy + 7
        while any(abs(ty - q) < 28 for q in placed):
            ty += 28
        placed.append(ty)
        right = cx > W - 300
        s.append(f'<text class="olab" x="{cx-15 if right else cx+15:.1f}" y="{ty:.1f}" '
                 f'text-anchor="{"end" if right else "start"}">{esc((name or code)[:24])}</text>')
    s.append(f'<text class="axt" x="{(L+W-R)/2:.1f}" y="{H-8}" text-anchor="middle">Alerts per centre</text>'
             f'<text class="axt" transform="translate(24 {(T+H-B)/2:.1f}) rotate(-90)" text-anchor="middle">{ylab}</text>')
    return f'<svg class="scatter" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">{"".join(s)}</svg>'


def _bins(series: dict, lo: int, hi: int, step: int) -> list[int]:
    out = [0] * ((hi - lo) // step + 1)
    for m, v in series.items():
        if lo <= m <= hi:
            out[(m - lo) // step] += v
    return out


def _smooth(pts, top, bottom) -> str:
    """A Catmull-Rom curve through the points, as cubic Beziers, with the control
    points clamped to the plot so the curve never dips below zero."""
    if len(pts) < 3:
        return " ".join(f'{"M" if i == 0 else "L"}{x:.1f},{y:.1f}' for i, (x, y) in enumerate(pts))
    cl = lambda y: max(top, min(bottom, y))
    d = [f"M{pts[0][0]:.1f},{pts[0][1]:.1f}"]
    for i in range(len(pts) - 1):
        p0, p1, p2 = pts[max(0, i - 1)], pts[i], pts[i + 1]
        p3 = pts[min(len(pts) - 1, i + 2)]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6, cl(p1[1] + (p2[1] - p0[1]) / 6))
        c2 = (p2[0] - (p3[0] - p1[0]) / 6, cl(p2[1] - (p3[1] - p1[1]) / 6))
        d.append(f"C{c1[0]:.1f},{c1[1]:.1f} {c2[0]:.1f},{c2[1]:.1f} {p2[0]:.1f},{p2[1]:.1f}")
    return " ".join(d)


def _curve(P) -> str:
    ms = P.get("series") or {}
    if not ms:
        return '<p class="empty">No timed alerts for this modality.</p>'
    lo, hi = min(ms), max(ms)
    BIN = 15   # the same window as "the busiest 15 minutes"; 5-min bins saw-tooth on cameras that report every ~10 min
    vals = _bins(ms, lo, hi, BIN)
    nb = len(vals)
    W, H, L, R, T, B = 820, 400, 62, 22, 30, 44
    vmax = _nice(max(vals) or 1)
    X = lambda i: L + i / max(1, nb - 1) * (W - L - R)
    Y = lambda v: (H - B) - v / vmax * (H - B - T)
    line = _smooth([(X(i), Y(v)) for i, v in enumerate(vals)], T, H - B)
    area = line + f" L{X(nb-1):.1f},{H-B} L{X(0):.1f},{H-B} Z"
    s = []
    for v in _ticks(0, vmax, 4):
        s.append(f'<line class="grid" x1="{L}" y1="{Y(v):.1f}" x2="{W-R}" y2="{Y(v):.1f}"/>'
                 f'<text class="tick" x="{L-10}" y="{Y(v)+6:.1f}" text-anchor="end">{v:g}</text>')
    step = 60 if hi - lo > 150 else 30
    for m in range((lo // step + 1) * step, hi + 1, step):
        s.append(f'<text class="tick" x="{X((m - lo) / BIN):.1f}" y="{H-B+28}" text-anchor="middle">{m//60:02d}:{m%60:02d}</text>')
    gid = f'cg{abs(hash(P.get("code", ""))) % 99999}'
    s.insert(0, f'<defs><linearGradient id="{gid}" x1="0" y1="0" x2="0" y2="1">'
                f'<stop offset="0" stop-color="{NAVY}" stop-opacity=".30"/>'
                f'<stop offset="1" stop-color="{NAVY}" stop-opacity="0"/></linearGradient></defs>')
    # the hour bands: alternate faint columns so the day reads at a glance
    for k, m in enumerate(range((lo // 60) * 60, hi + 1, 60)):
        if k % 2 == 0:
            xa, xb = X(max(0, (m - lo) / BIN)), X(min(nb - 1, (m + 60 - lo) / BIN))
            if xb > xa:
                s.insert(1, f'<rect class="hband" x="{xa:.1f}" y="{T}" width="{xb-xa:.1f}" height="{H-B-T}"/>')
    s.append(f'<path class="area" d="{area}" fill="url(#{gid})"/><path class="line" d="{line}" pathLength="1"/>'
             f'<circle class="head" r="6" cx="{X(0):.1f}" cy="{Y(vals[0]):.1f}"/>')
    if P.get("peak_v") and P.get("peak_hm", "--") != "--":
        ph, pm = map(int, P["peak_hm"].split(":"))
        pi = (ph * 60 + pm - lo) / BIN
        x0, x1 = X(pi), X(min(nb - 1, pi + 1))
        # ring the highest bin inside the peak window
        win = range(int(pi), min(nb, int(pi) + 2))
        bi = max(win, key=lambda i: vals[i]) if len(win) else int(pi)
        px, py = X(bi), Y(vals[bi])
        right = x0 > W - 300
        s.append(f'<g class="peak" style="--d:{0.5 + 2.4 * pi / max(1, nb - 1):.2f}s">'
                 f'<rect x="{x0:.1f}" y="{T}" width="{max(5, x1-x0):.1f}" height="{H-B-T}"/>'
                 f'<circle class="pring" cx="{px:.1f}" cy="{py:.1f}" r="15"/>'
                 f'<circle class="pdot" cx="{px:.1f}" cy="{py:.1f}" r="5.5"/>'
                 f'<text x="{x0 - 8 if right else x1 + 8:.1f}" y="{T+18}" text-anchor="{"end" if right else "start"}">'
                 f'Peak {P["peak_hm"]} · {P["peak_v"]:,} in 15 min</text></g>')
    return f'<svg class="curve" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">{"".join(s)}</svg>'


def _rank_key(P):
    """What a modality is ranked on: its own severity metric where it has one,
    otherwise the alert count."""
    if P["mode"] in ("sustained", "sustained_count"):
        unit = " min" if P["mode"] == "sustained" else "/15m"
        return (lambda p: p[3]), unit
    return (lambda p: p[2]), ""


def _ranked(P, n: int = 8) -> str:
    """The worst centres as lollipops: a stem that grows, a dot that rides out to
    the value, the value written at the end, tier thresholds drawn behind."""
    pts = P.get("points") or []
    if not pts:
        return '<p class="empty">No centres detected.</p>'
    key, unit = _rank_key(P)
    top = sorted(pts, key=lambda p: (-key(p), -p[2]))[:n]
    W, H, L, R, T, B = 760, 420, 250, 86, 30, 34
    vmax = _nice(max(key(p) for p in top) or 1)
    X = lambda v: L + v / vmax * (W - L - R)
    rh = (H - T - B) / n
    s = []
    for v in _ticks(0, vmax, 4):
        s.append(f'<line class="grid v" x1="{X(v):.1f}" y1="{T-6}" x2="{X(v):.1f}" y2="{H-B}"/>'
                 f'<text class="tick sm" x="{X(v):.1f}" y="{H-B+24}" text-anchor="middle">{v:g}</text>')
    if P["mode"] == "sustained":
        for v, t, lab, anc in ((45, "o", "45 high", "end"), (75, "r", "75 critical", "start")):
            if v < vmax:
                dx = -6 if anc == "end" else 6
                s.append(f'<g class="thr"><line x1="{X(v):.1f}" y1="{H-B}" x2="{X(v):.1f}" y2="{T-6}" stroke="{TIER[t]}"/>'
                         f'<text x="{X(v)+dx:.1f}" y="{T-12}" fill="{TIER[t]}" class="sm" text-anchor="{anc}">{lab}</text></g>')
    for i, (name, code, ax, ay, tier, dist) in enumerate(top):
        y = T + rh * (i + .5)
        v = key((name, code, ax, ay, tier, dist))
        x = X(v)
        c = TIER[tier]
        d = .35 + i * .09
        tip = esc(json.dumps({"n": name or code, "d": dist or "", "a": ax, "m": ay, "t": TNAME[tier]}))
        s.append(f'<g class="lol" style="--d:{d:.2f}s;--dx:{L - x:.1f}px" data-tip="{tip}" data-c="{esc(code)}">'
                 f'<rect class="hit" x="0" y="{y - rh/2:.1f}" width="{W}" height="{rh:.1f}"/>'
                 f'<text class="lname" x="{L-14}" y="{y+6:.1f}" text-anchor="end">{esc((name or code)[:28])}</text>'
                 f'<line class="track" x1="{L}" y1="{y:.1f}" x2="{W-R}" y2="{y:.1f}"/>'
                 f'<line class="stem" x1="{L}" y1="{y:.1f}" x2="{x:.1f}" y2="{y:.1f}" stroke="{c}"/>'
                 f'<circle class="ldot{" lr" if tier == "r" else ""}" cx="{x:.1f}" cy="{y:.1f}" r="{10 if tier == "r" else 8}" fill="{c}"/>'
                 f'<text class="lval" x="{x+16:.1f}" y="{y+6:.1f}" fill="{c}">{v:,}{unit}</text></g>')
    return f'<svg class="ranked" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">{"".join(s)}</svg>'


def _ring(P) -> str:
    """Every centre by tier as a ring that sweeps round, the critical count in
    the middle, the tiers listed beside it."""
    sev = P["sev"]
    tot = sum(sev.values()) or 1
    R0, C = 74, 2 * 3.14159 * 74
    segs, start = [], 0.0
    for k, t in enumerate(("r", "o", "y", "g")):
        frac = sev[t] / tot
        if frac <= 0:
            continue
        gap = 1.2 if frac < 1 else 0
        segs.append(f'<circle class="arc" cx="100" cy="100" r="{R0}" stroke="{TIER[t]}" '
                    f'style="--s:{max(0.1, frac * 100 - gap):.2f};--o:{-start:.2f};--d:{.5 + k * .28:.2f}s" pathLength="100"/>')
        start += frac * 100
    mid = sev["r"]
    legend = "".join(
        f'<g class="rleg" style="--d:{.9 + k * .12:.2f}s"><circle cx="232" cy="{46 + k * 36}" r="7" fill="{TIER[t]}"/>'
        f'<text x="248" y="{52 + k * 36}" class="rlt">{TNAME[t]}</text>'
        f'<text x="390" y="{52 + k * 36}" class="rln" text-anchor="end">{sev[t]}</text></g>'
        for k, t in enumerate(("r", "o", "y", "g")))
    return (f'<svg class="ring" viewBox="0 0 400 200" preserveAspectRatio="xMidYMid meet">'
            f'<circle cx="100" cy="100" r="{R0}" class="rtrack"/>'
            f'<g transform="rotate(-90 100 100)">{"".join(segs)}</g>'
            f'<text x="100" y="104" text-anchor="middle" class="rnum{" red" if mid else ""}" data-n="{mid}">0</text>'
            f'<text x="100" y="130" text-anchor="middle" class="rcap">critical of {P["centres"]}</text>'
            f'{legend}</svg>')


def _subloc(P, n: int = 5) -> str:
    """Where inside the centre the camera was: the top camera locations as
    proportional bars, the largest in red."""
    rows = (P.get("subloc") or [])[:n]
    if not rows:
        return '<p class="empty sm">No camera locations recorded.</p>'
    tot = sum(v for _, v in P.get("subloc") or []) or 1
    vmax = rows[0][1] or 1
    W, rh = 400, 38
    H = rh * len(rows) + 4
    s = []
    for i, (z, v) in enumerate(rows):
        y = i * rh
        w = (W - 70) * v / vmax
        c = RED if i == 0 else (TIER["o"] if i < 3 else TIER["y"])
        s.append(f'<g class="sb" style="--d:{.6 + i * .1:.2f}s">'
                 f'<text x="0" y="{y+13}" class="sbn">{esc(z[:34])}</text>'
                 f'<rect class="sbt" x="0" y="{y+19}" width="{W-70}" height="9" rx="4.5"/>'
                 f'<rect class="sbr" x="0" y="{y+19}" width="{max(4, w):.1f}" height="9" rx="4.5" fill="{c}"/>'
                 f'<text x="{W}" y="{y+28}" class="sbv" text-anchor="end">{round(100 * v / tot)}%</text></g>')
    return f'<svg class="subloc" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMin meet">{"".join(s)}</svg>'


def _dial(series: dict, lo: int, hi: int, total: int, hot: bool) -> str:
    """The exam day as a dial: one radial bar per 15-minute slice, clockwise from
    the top, all tiles on the same day window so dials compare at a glance. The
    busiest slice is the one red bar; the count sits in the hub."""
    import math
    bins = _bins(series, lo, hi, 15) if series and hi > lo else []
    n = len(bins)
    vmax = max(bins) if bins else 0
    cx = cy = 60
    r0, r1, gap = 27, 56, 26          # hub radius, outer radius, degrees left open at the top
    s = [f'<circle cx="{cx}" cy="{cy}" r="{r0 - 3}" class="dhub"/>',
         f'<circle cx="{cx}" cy="{cy}" r="{r1}" class="dring"/>']
    pk = max(range(n), key=lambda i: bins[i]) if n and vmax else -1
    span = 360 - gap
    for i, v in enumerate(bins):
        a = math.radians(gap / 2 + span * (i + .5) / n - 90)
        rr = r0 + (r1 - r0) * (v / vmax if vmax else 0)
        x0, y0 = cx + math.cos(a) * r0, cy + math.sin(a) * r0
        x1, y1 = cx + math.cos(a) * max(rr, r0 + .6), cy + math.sin(a) * max(rr, r0 + .6)
        cls = "db pk" if i == pk else ("db" if v else "db z")
        s.append(f'<line class="{cls}" x1="{x0:.1f}" y1="{y0:.1f}" x2="{x1:.1f}" y2="{y1:.1f}" pathLength="1" '
                 f'style="--d:{.55 + .9 * i / max(1, n):.2f}s"><title>{(lo + i * 15) // 60:02d}:{(lo + i * 15) % 60:02d} · {v:,} alerts</title></line>')
    # hour ticks and the start/end of the day window
    for m in range(((lo // 60) + 1) * 60, hi, 60):
        a = math.radians(gap / 2 + span * (m - lo) / max(1, hi - lo) - 90)
        s.append(f'<line class="dtk" x1="{cx + math.cos(a) * (r1 + 1.5):.1f}" y1="{cy + math.sin(a) * (r1 + 1.5):.1f}" '
                 f'x2="{cx + math.cos(a) * (r1 + 4):.1f}" y2="{cy + math.sin(a) * (r1 + 4):.1f}"/>')
    s.append(f'<text x="{cx - 4}" y="7" text-anchor="end" class="dlab">{lo // 60:02d}</text>'
             f'<text x="{cx + 4}" y="7" class="dlab">{hi // 60:02d}</text>')
    s.append(f'<text x="{cx}" y="{cy + 2}" text-anchor="middle" class="dnum{" red" if hot else ""}" data-n="{total}">0</text>'
             f'<text x="{cx}" y="{cy + 13}" text-anchor="middle" class="dcap">alerts</text>')
    return f'<svg class="dial" viewBox="-4 -4 128 128">{"".join(s)}</svg>'


def _spark(series: dict, lo: int, hi: int) -> str:
    if not series or hi <= lo:
        return '<svg class="spark" viewBox="0 0 200 40"></svg>'
    vals = _bins(series, lo, hi, 15)
    vmax = max(vals) or 1
    n = len(vals)
    pts = [(i / max(1, n - 1) * 200, 38 - v / vmax * 34) for i, v in enumerate(vals)]
    d = " ".join(f'{"M" if i == 0 else "L"}{x:.1f},{y:.1f}' for i, (x, y) in enumerate(pts))
    return (f'<svg class="spark" viewBox="0 0 200 40" preserveAspectRatio="none">'
            f'<path class="sa" d="{d} L200,40 L0,40 Z"/><path class="sl" d="{d}" pathLength="1"/></svg>')


def _tierbar(sev: dict) -> str:
    tot = sum(sev.values()) or 1
    return '<div class="tbar">' + "".join(
        f'<i style="flex:{sev[t] / tot:.4f};background:{TIER[t]};--d:{0.55 + k * .12:.2f}s"></i>'
        for k, t in enumerate(("r", "o", "y", "g")) if sev[t]) + '</div>'


def _kpis(cells) -> str:
    out = []
    for v, k, cls in cells:
        num = (f'<div class="kn" data-n="{v}">0</div>' if isinstance(v, int)
               else f'<div class="kn txt">{esc(v)}</div>')
        out.append(f'<div class="kpi{cls}">{num}<div class="kl">{k}</div></div>')
    return '<div class="kpis">' + "".join(out) + "</div>"


# ---------------------------------------------------------------- the map
_FILL = re.compile(r'data-d="([^"]+)" d="[^"]*" fill="([^"]+)"')


def _map_parts(geo: dict) -> tuple[str, dict]:
    """The choropleth for these values, and {district: fill} read back out of it,
    so the same ramp the PDFs use colours the shared map."""
    svg = choropleth(geo, light=True, label_top=0, pulse=0, fit_full=True)
    return svg, {d: f for d, f in _FILL.findall(svg)}


def _counts(geo: dict) -> dict:
    out: dict = {}
    for k, n in geo.items():
        d = k[1] if isinstance(k, tuple) else k
        out[d] = out.get(d, 0) + n
    return out


# ---------------------------------------------------------------- the manager's graphs
def _clock_cells(clk) -> str:
    """The manager's time-of-day clocks (clock_chart): one 12-hour face per
    shift, the exam window as a wedge, a line per 30-minute slot. The slot
    lines are given pathLength so they grow out from the hub when shown."""
    if not clk:
        return '<p class="empty">No alerts landed inside an exam window.</p>'
    from .clock_chart import clock_svg, colour
    cells = []
    for x in clk["shifts"]:
        svg = clock_svg(x, clk["mx"])
        k = iter(range(10_000))
        svg = re.sub(r'<line (x1=[^>]*stroke-linecap="round")',
                     lambda m: f'<line class="cl" pathLength="1" style="--i:{next(k)}" {m.group(1)}', svg)
        svg = svg.replace("<path ", '<path class="wedge" ', 1).replace('width="100%"', "")
        cells.append(f'<div class="ck"><div class="ckh"><i style="background:{colour(x["shift"])}"></i>'
                     f'Shift {x["shift"]} · {esc(x["label"])}</div><div class="ckf">{svg}</div>'
                     f'<div class="ckn">{x["total"]:,} alerts in the window'
                     + (f' · peak <b style="color:{colour(x["shift"])}">{esc(x["peak_at"])}</b>, {x["peak_n"]:,}' if x["peak_n"] else "")
                     + '</div></div>')
    return "".join(cells)


def _compact(n: int) -> str:
    return f"{n / 1000:.1f}k".replace(".0k", "k") if n >= 1000 else str(n)


def _mring(c: int, n: int, colour: str, title: str, txt: str, i: int = 0) -> str:
    """The manager's ring card: a small ring filled to c of n, the count inside,
    "c of n" and one line beside it."""
    p = 100 * c / n if n else 0
    return (f'<div class="mr" style="--i:{i}"><small><i style="background:{colour}"></i>{esc(title)}</small>'
            f'<div class="mrw"><svg viewBox="0 0 64 64"><circle cx="32" cy="32" r="24" class="mrt"/>'
            f'<circle cx="32" cy="32" r="24" class="mra" stroke="{colour}" pathLength="100" style="--p:{p:.1f}" '
            f'transform="rotate(-90 32 32)"/><text x="32" y="38" text-anchor="middle" class="mrn">{_compact(c)}</text></svg>'
            f'<div><b>{c:,} <span>of {n:,}</span></b><p>{esc(txt)}</p></div></div></div>')


def _mod_rings(P) -> str:
    clk_n = (P.get("clock") or {}).get("total", 0)
    cards = [
        (P["crit"], P["centres"], RED, "Critical centres", "centres that crossed the critical threshold"),
        (P["centres"], P.get("all_centres") or P["centres"], TIER["o"], "Centres alerting", "of every centre in the examination"),
        (clk_n, P["total"], TIER["y"], "Inside the exam window", "alerts raised while the exam was running"),
        (P.get("framed", 0), P["total"], TIER["g"] if not P.get("framed") else NAVY, "With an evidence frame", "alerts that carry a camera image"),
    ]
    return "".join(_mring(c, n, col, t, x, i) for i, (c, n, col, t, x) in enumerate(cards))


# ---------------------------------------------------------------- header statistics
def _short(label: str) -> str:
    return label.split(" · ")[0].replace("Multiple People", "Multiple").replace("Restricted ", "")


def _compbar(comp, sel: str | None = None) -> str:
    """Every alert in the examination as one bar split by modality, widths to
    scale. A red cap on a segment is the share of that modality's centres that
    reached critical. Each segment opens its modality; hover gives the numbers."""
    tot = sum(c["n"] for c in comp) or 1
    W, H, gap = 1000, 30, 2
    x, s, labs = 0.0, [], []
    usable = W - gap * (len(comp) - 1)
    for i, c in enumerate(comp):
        w = usable * c["n"] / tot
        on = sel is None or c["code"] == sel
        fill = (NAVY if c["crit"] else TIER["y"]) if on else "#D5DAE0"
        cap = w * (c["crit"] / c["centres"]) if c["centres"] else 0
        lab = ""
        if w > 62:
            labs.append(f'<span class="cbl{" on" if on else ""}" data-go="{esc(c["code"])}" style="left:{100 * x / W:.2f}%">'
                        f'{esc(_short(c["l"]))}<i>{c["n"]:,} · {100 * c["n"] / tot:.0f}%</i></span>')
        capr = (f'<rect class="cbc" x="{x:.1f}" y="2" width="{cap:.1f}" height="4" fill="{RED if on else "#E3B6B3"}"/>'
                if cap else "")
        s.append(f'<g class="cseg{" sel" if sel and on else ""}" data-go="{esc(c["code"])}" style="--d:{.25 + i * .06:.2f}s">'
                 f'<title>{esc(c["l"])}: {c["n"]:,} alerts, {100 * c["n"] / tot:.1f}% of all · '
                 f'{c["crit"]} of {c["centres"]} centres critical</title>'
                 f'<rect class="cbr" x="{x:.1f}" y="6" width="{max(w, 1):.1f}" height="24" fill="{fill}"/>{capr}{lab}</g>')
        x += w + gap
    svg = f'<svg class="compbar" viewBox="0 0 {W} {H}" preserveAspectRatio="none">{"".join(s)}</svg>'
    # labels are HTML over the bar so the stretched SVG never distorts the type
    return f'<div class="cbw">{svg}<div class="cblabs">{"".join(labs)}</div></div>' if sel is None else svg


def _stat(i, label, value, ctx, vis="") -> str:
    return (f'<div class="st" style="--i:{i}"><div class="stl">{label}</div>'
            f'<div class="stv">{value}</div>{vis}<div class="stc">{ctx}</div></div>')


def _sum_stats(profs, totals) -> str:
    """Three figures, each drawn: the day's alert curve under the total, the
    district split under the centres, the critical share as a ring."""
    # the whole examination's day, in 15-minute bins
    series: dict = {}
    for p in profs:
        for m, v in (p.get("series") or {}).items():
            series[m] = series.get(m, 0) + v
    spark, peak_txt = "", ""
    if series:
        # whole-hour start, the same 15-minute grid as the rings below, so both name the same peak
        lo, hi = (min(series) // 60) * 60, max(series)
        bins = _bins(series, lo, hi, 15)
        n, mx = len(bins), max(bins) or 1
        W, H = 150, 40
        X = lambda i: 2 + (W - 4) * i / max(1, n - 1)  # noqa: E731
        Y = lambda v: H - 3 - (H - 8) * v / mx  # noqa: E731
        line = _smooth([(X(i), Y(v)) for i, v in enumerate(bins)], 3, H - 3)
        pk = bins.index(max(bins))
        spark = (f'<svg class="hsp" viewBox="0 0 {W} {H}"><path class="hspa" d="{line} L{X(n - 1):.1f},{H} L2,{H} Z"/>'
                 f'<path class="hspl" d="{line}" pathLength="1"/>'
                 f'<circle class="hspd" cx="{X(pk):.1f}" cy="{Y(bins[pk]):.1f}" r="3.6"/></svg>')
        pm = lo + pk * 15
        peak_txt = f'busiest at <b>{pm // 60:02d}:{pm % 60:02d}</b>, {bins[pk]:,} alerts in 15 min'
    # the district split
    geo: dict = {}
    for p in profs:
        for d, v in _counts(p.get("geo", {})).items():
            geo[d] = geo.get(d, 0) + v
    gt = sum(geo.values()) or 1
    segs, x = [], 0.0
    for i, (d, v) in enumerate(sorted(geo.items(), key=lambda kv: -kv[1])):
        w = 150 * v / gt
        segs.append(f'<g class="hds" data-dist="{esc(d)}" style="--d:{.5 + i * .12:.2f}s"><title>{esc(d)}: {v:,} alerts, {100 * v / gt:.0f}%</title>'
                    f'<rect x="{x + (1 if i else 0):.1f}" y="10" width="{max(1.5, w - (1 if i else 0)):.1f}" height="14" fill="{NAVY if i == 0 else TIER["y"] if i == 1 else TIER["g"]}"/></g>')
        x += w
    dbar = f'<svg class="hdb" viewBox="0 0 150 30" preserveAspectRatio="none">{"".join(segs)}</svg>'
    dtxt = " · ".join(f'<span class="lk" data-dist="{esc(d)}">{esc(d)}</span> {100 * v / gt:.0f}%'
                      for d, v in sorted(geo.items(), key=lambda kv: -kv[1])[:3])
    # the critical share: centre x modality pairs that reached critical
    crit = sum(p["crit"] for p in profs)
    pairs = sum(p["centres"] for p in profs) or 1
    k = sum(1 for p in profs if p["crit"])
    pct = 100 * crit / pairs
    ring = (f'<svg class="hrg" viewBox="0 0 44 44"><circle cx="22" cy="22" r="17" class="hrgt"/>'
            f'<circle cx="22" cy="22" r="17" class="hrga" pathLength="100" style="--p:{pct:.1f}" transform="rotate(-90 22 22)"/>'
            f'<text x="22" y="26" text-anchor="middle" class="hrgn">{pct:.0f}%</text></svg>')

    def tile(i, label, num, vis, ctx):
        return (f'<div class="ht" style="--i:{i}"><div class="htl2">{label}</div>'
                f'<div class="htr"><div class="htn">{num}</div>{vis}</div><div class="htc">{ctx}</div></div>')
    return ('<div class="hstats">'
            + tile(0, "Alerts", f'<b data-n="{totals["alerts"]}">0</b>', spark, peak_txt)
            + tile(1, f'Centres · {totals["districts"]} districts', f'<b data-n="{totals["centres"]}">0</b>', dbar, dtxt)
            + tile(2, "Critical findings", f'<b class="red" data-n="{crit}">0</b>', ring,
                   f'{crit} of {pairs:,} centre–modality pairs')
            + '</div>')


def _sum_bar(profs) -> str:
    comp = sorted(({"code": p["code"], "l": p["label"], "n": p["total"], "crit": p["crit"], "centres": p["centres"]}
                   for p in profs), key=lambda c: -c["n"])
    return ('<div class="sumbar rv"><div class="stl">Alerts by modality · click a segment to open it · '
            '<span style="color:var(--red)">red cap</span> = share of its centres at critical</div>'
            f'{_compbar(comp)}</div>')


def _mod_stats(P) -> str:
    comp = P.get("comp") or []
    tot = sum(c["n"] for c in comp) or 1
    rank = 1 + sum(1 for c in comp if c["n"] > P["total"])
    allc = P.get("all_centres") or P["centres"]
    cols = 27
    sq = []
    for j in range(allc):          # unit chart: one square per centre in the examination
        cls = "ur" if j < P["crit"] else ("un" if j < P["centres"] else "ug")
        sq.append(f'<rect class="{cls}" x="{(j % cols) * 6}" y="{(j // cols) * 6}" width="4.6" height="4.6" '
                  f'style="--d:{.5 + j * .012:.2f}s"/>')
    units = f'<svg class="units" viewBox="0 0 {cols * 6} {((allc - 1) // cols + 1) * 6}">{"".join(sq)}</svg>'
    critpts = sorted((pt for pt in P.get("points") or [] if pt[4] == "r"), key=lambda pt: -pt[3])
    if critpts:
        crit_ctx = ", ".join(f'<span class="lk" data-c="{esc(pt[1])}">{esc((pt[0] or pt[1])[:26])}</span>'
                             for pt in critpts[:2])
        if len(critpts) > 2:
            crit_ctx += f" and {len(critpts) - 2} more"
    else:
        crit_ctx = "None reached critical."
    lo, hi = P.get("day_lo", 0), P.get("day_hi", 0)
    track = ""
    if hi > lo and P.get("tmin_m") is not None:
        X = lambda m: 2 + 156 * (m - lo) / (hi - lo)  # noqa: E731
        pk = ""
        if P.get("peak_hm", "--") != "--":
            h, m = map(int, P["peak_hm"].split(":"))
            pk = f'<line x1="{X(h * 60 + m):.1f}" y1="3" x2="{X(h * 60 + m):.1f}" y2="19" class="wpk"/>'
        track = (f'<svg class="sstrip" viewBox="0 0 160 22" preserveAspectRatio="none">'
                 f'<line x1="2" y1="11" x2="158" y2="11" class="ssl"/>'
                 f'<rect class="wbar" x="{X(P["tmin_m"]):.1f}" y="7" '
                 f'width="{max(2, X(P["tmax_m"]) - X(P["tmin_m"])):.1f}" height="8" rx="2"/>{pk}</svg>')
    mini = _compbar(comp, P["code"]).replace('class="compbar"', 'class="compbar mini"')
    key = ('<span style="color:var(--red)">■</span> critical · <span style="color:var(--navy)">■</span> alerting · '
           '<span style="color:var(--g1)">■</span> silent')
    cells = [
        _stat(0, "Alerts", f'<b data-n="{P["total"]}">0</b><small>{100 * P["total"] / tot:.0f}% of all</small>',
              f'Rank {rank} of {len(comp)} modalities by volume.', mini),
        _stat(1, "Centres alerting", f'<b data-n="{P["centres"]}">0</b><small>of {allc}</small>', key, units),
        _stat(2, "Critical centres", f'<b class="{"red" if P["crit"] else ""}" data-n="{P["crit"]}">0</b>', crit_ctx),
        _stat(3, "Active window", f'<b class="txt">{esc(P["win"])}</b>',
              f'Peak 15 minutes from {esc(P.get("peak_hm") or "--")}; {P["cameras"]} cameras raised alerts.', track),
    ]
    return '<div class="stats mods">' + "".join(cells) + "</div>"


def _flat(P) -> bool:
    """True when the modality's own metric is the same for every centre, so a
    ranking on it would say nothing; rank on alerts instead."""
    pts = P.get("points") or []
    key, _ = _rank_key(P)
    return len(pts) > 1 and len({key(p) for p in pts}) == 1


def _tip(p) -> str:
    name, code, ax, ay, tier, dist = p
    return esc(json.dumps({"n": name or code, "d": dist or "", "a": ax, "m": ay, "t": TNAME[tier]}))


def _bars(P, n: int = 8) -> str:
    """The worst centres as capsule bars, tier-coloured, value at the end."""
    pts = P.get("points") or []
    if not pts:
        return '<p class="empty">No centres detected.</p>'
    key, unit = _rank_key(P)
    if _flat(P):
        key, unit = (lambda q: q[2]), " alerts"
    top = sorted(pts, key=lambda q: (-key(q), -q[2]))[:n]
    vmax = max(key(q) for q in top) or 1
    rows = []
    for i, q in enumerate(top):
        name, code, ax, ay, tier, dist = q
        v = key(q)
        rows.append(f'<div class="br t{tier}" data-c="{esc(code)}" data-tip="{_tip(q)}" '
                    f'style="--d:{.3 + i * .08:.2f}s;--w:{max(3, 100 * v / vmax):.1f}%;--c:{TIER[tier]}">'
                    f'<span class="brk">{i + 1}</span>'
                    f'<span class="brn" title="{esc(name or code)}"><b>{esc(name or code)}</b><small>{esc(dist or "")}</small></span>'
                    f'<span class="brb"><i></i></span>'
                    f'<span class="brv">{v:,}<small>{esc(unit.strip())}</small></span></div>')
    return '<div class="bars">' + "".join(rows) + '</div>'


def _hexes(P) -> str:
    """Every centre in the examination as one hexagon: worst first, coloured by
    tier; centres where this modality never fired are outlines."""
    import math
    pts = P.get("points") or []
    allc = max(P.get("all_centres") or 0, len(pts))
    if not allc:
        return '<p class="empty">No centres detected.</p>'
    order = {"r": 0, "o": 1, "y": 2, "g": 3}
    key, _ = _rank_key(P)
    ranked = sorted(pts, key=lambda q: (order.get(q[4], 3), -key(q), -q[2]))
    cols = max(6, math.ceil(math.sqrt(allc * 2.4)))
    nrows = math.ceil(allc / cols)
    r = 16.0
    w, h = math.sqrt(3) * r, 1.5 * r
    W, H = cols * w + w / 2 + 6, (nrows - 1) * h + 2 * r + 6

    def hexd(cx, cy, rr):
        c = [(cx + rr * math.cos(math.radians(60 * k - 30)), cy + rr * math.sin(math.radians(60 * k - 30))) for k in range(6)]
        return "M" + " L".join(f"{x:.1f},{y:.1f}" for x, y in c) + "Z"
    out = []
    step = min(.03, 1.6 / allc)
    for j in range(allc):
        rr, cc = divmod(j, cols)
        cx = 3 + w / 2 + cc * w + (w / 2 if rr % 2 else 0)
        cy = 3 + r + rr * h
        d = .3 + j * step
        if j < len(ranked):
            q = ranked[j]
            out.append(f'<path class="hx t{q[4]}" d="{hexd(cx, cy, r - 1.6)}" fill="{TIER[q[4]]}" '
                       f'data-c="{esc(q[1])}" data-tip="{_tip(q)}" style="--d:{d:.2f}s"/>')
        else:
            out.append(f'<path class="hx sil" d="{hexd(cx, cy, r - 2.6)}" style="--d:{d:.2f}s"/>')
    return f'<svg class="hexes" viewBox="0 0 {W:.1f} {H:.1f}" preserveAspectRatio="xMidYMid meet">{"".join(out)}</svg>'


def _dots(P) -> str:
    """The day as a dot plot: every alert is a dot, stacked in its 10- or
    15-minute column; when a column would overflow, one dot stands for k alerts.
    The busiest column is red."""
    import math
    ms = P.get("series") or {}
    if not ms:
        return '<p class="empty">No timed alerts for this modality.</p>'
    lo, hi = min(ms), max(ms)
    if hi - lo < 60:
        mid = (lo + hi) // 2
        lo, hi = mid - 30, mid + 30
    step = 10 if hi - lo <= 300 else 15
    lo = lo // step * step
    vals = _bins(ms, lo, hi, step)
    nb = len(vals)
    W, H, L, R, T, B = 820, 330, 20, 20, 46, 40
    cw = (W - L - R) / nb
    dd = min(cw * .84, 17)
    cap = max(1, int((H - T - B) // dd))
    vmax = max(vals) or 1
    k = 1
    for nice in (1, 2, 5, 10, 20, 25, 50, 100, 200, 500, 1000):
        k = nice
        if math.ceil(vmax / nice) <= cap:
            break
    pk = vals.index(vmax)
    o = [f'<line class="dbase" x1="{L}" y1="{H - B + 4}" x2="{W - R}" y2="{H - B + 4}"/>']
    first = lo if lo % 60 == 0 else (lo // 60 + 1) * 60
    every = 60 if hi - lo <= 480 else 120
    for m in range(first, hi + 1, every):
        x = L + (m - lo) / step * cw
        o.append(f'<line class="dgrid" x1="{x:.1f}" y1="{T - 6}" x2="{x:.1f}" y2="{H - B + 8}"/>'
                 f'<text class="tick sm" x="{x:.1f}" y="{H - B + 30}" text-anchor="middle">{m // 60:02d}:{m % 60:02d}</text>')
    for i, v in enumerate(vals):
        if not v:
            continue
        cx = L + cw * (i + .5)
        n = math.ceil(v / k)
        cls = "dd pk" if i == pk else "dd"
        for j in range(n):
            o.append(f'<circle class="{cls}" cx="{cx:.1f}" cy="{H - B - dd * (j + .5):.1f}" r="{dd * .4:.1f}" '
                     f'style="--d:{.3 + i * .03 + j * .015:.2f}s"/>')
        m0 = lo + i * step
        o.append(f'<rect class="dhit" x="{cx - cw / 2:.1f}" y="{T - 6}" width="{cw:.1f}" height="{H - B - T + 10}">'
                 f'<title>{m0 // 60:02d}:{m0 % 60:02d}–{(m0 + step) // 60:02d}:{(m0 + step) % 60:02d} · {v:,} alert{"s" if v != 1 else ""}</title></rect>')
    px = min(W - R - 90, max(L + 90, L + cw * (pk + .5)))
    py = H - B - dd * math.ceil(vmax / k) - 14
    pm = lo + pk * step
    o.append(f'<text class="dpk" x="{px:.1f}" y="{max(T - 14, py):.1f}" text-anchor="middle">'
             f'Peak {pm // 60:02d}:{pm % 60:02d} · {vmax:,} in {step} min</text>')
    o.append(f'<g class="dkey"><circle cx="{W - R - 196}" cy="14" r="6"/><text x="{W - R - 184}" y="20">'
             f'one dot = {k} alert{"s" if k > 1 else ""}</text></g>')
    return f'<svg class="dots" viewBox="0 0 {W} {H}" preserveAspectRatio="xMidYMid meet">{"".join(o)}</svg>'


def _tiers(P) -> str:
    """Severity as four number tiles, and where in the centre the cameras were."""
    sev = P["sev"]
    tot = sum(sev.values()) or 1
    tiles = "".join(
        f'<div class="tt{" z" if not sev[t] else ""}" style="--c:{TIER[t]};--w:{100 * sev[t] / tot:.1f}%;--d:{.35 + k * .1:.2f}s">'
        f'<b data-n="{sev[t]}">0</b><span>{TNAME[t]}</span><i></i></div>'
        for k, t in enumerate(("r", "o", "y", "g")))
    allrows = P.get("subloc") or []
    stot = sum(v for _, v in allrows) or 1
    sl = "".join(
        f'<div class="sl" style="--w:{max(1.5, 100 * v / stot):.1f}%;--d:{.8 + i * .1:.2f}s{";--c:var(--red)" if i == 0 else ""}">'
        f'<span>{esc(z.title()[:30])}</span><i></i><b>{round(100 * v / stot)}%</b></div>'
        for i, (z, v) in enumerate(allrows[:4]))
    return (f'<div class="tiers"><div class="tts">{tiles}</div>'
            f'<div class="slh">Where in the centre the cameras were</div>'
            f'<div class="sls">{sl or "<p class=\'empty sm\'>No camera locations recorded.</p>"}</div></div>')


def _dleg(P) -> str:
    c = _counts(P.get("geo", {}))
    tot = sum(c.values()) or 1
    rows = sorted(c.items(), key=lambda kv: -kv[1])[:4]
    return '<div class="dleg">' + "".join(
        f'<div class="dl" data-dist="{esc(d)}" style="--w:{100 * v / tot:.1f}%;--d:{.9 + i * .1:.2f}s">'
        f'<span>{esc(d)}</span><i></i><b>{v:,}</b></div>' for i, (d, v) in enumerate(rows)) + '</div>'


# ---------------------------------------------------------------- views
def _summary_view(exam, dt, profs, totals) -> str:
    kpis = _sum_stats(profs, totals)
    return f"""
<section class="view summary" id="v-summary" data-id="summary">
  <div class="top">
    <div><div class="kick rv">{esc(exam.code)} · every modality</div>
      <h1 class="rv">{esc(exam.name)}</h1>
      <div class="exam rv">{esc(dt)} · summary of all AI modalities</div>
      <button class="tourbtn rv" data-tour>Tour the findings</button></div>
    {kpis}
  </div>
  <div class="leadrow"><p class="lead rv">{_summary_headline(profs)}</p>
    <div class="replay rv"><button class="rpb" id="rp-play" title="Replay the exam day">▶ Replay the day</button>
      <div class="rptrack" id="rp-track"><div class="rpfill" id="rp-fill"></div><div class="rpknob" id="rp-knob"></div></div>
      <span class="rpt" id="rp-t"></span></div></div>
  <div class="hub">
    <div class="panel hr rv" data-tabs>
      <div class="phead"><div class="fig">The exam day · every modality on one clock</div>
        <div class="seg"><button data-tab="rings" class="sel">Day rings</button><button data-tab="mclock">Shift clocks</button></div></div>
      <div class="pane" data-pane="rings"><div class="fill" id="h-radial"></div>
        <div class="cap">One ring per AI modality, the busiest outermost. One cell per 15 minutes, clockwise from the top; darker means more alerts, <b style="color:var(--red)">red</b> is the busiest cell of the day.</div></div>
      <div class="pane" data-pane="mclock" hidden><div class="clockrow">{_clock_cells(totals.get("clock"))}</div>
        <div class="cap">The shaded wedge is each shift's exam window; each line is a 30-minute slot.</div></div>
    </div>
    <div class="panel hf rv" data-tabs><div class="phead"><div class="fig">How the alerts connect</div>
        <div class="seg"><button data-tab="flow" class="sel">To districts</button><button data-tab="chord">Fired together</button></div></div>
      <div class="pane" data-pane="flow"><div class="fill" id="h-flow"></div>
        <div class="cap">Ribbon width is alerts. Hover a modality or a district to follow it; click to open it.</div></div>
      <div class="pane" data-pane="chord" hidden><div class="fill" id="h-chord"></div>
        <div class="cap">A ribbon joins two modalities that fired at the same centre in the same 15 minutes; wider means more often.</div></div></div>
    <div class="hcol">
      <div class="panel mapcol rv"><div class="fig" id="h-mapt">All alerts by district</div><div class="mapslot"></div></div>
      <div class="panel hl rv"><div class="phead"><div class="fig" id="h-lbt">Centres to look at first</div><span class="lbk" id="h-lbk">critical modalities · alerts</span></div>
        <div class="lb" id="h-lb"></div></div>
    </div>
  </div>
</section>"""


def _mod_view(exam, dt, P, i, n) -> str:
    fr = _frame(P)
    head, ctx = _headline(P)
    legend = "".join(f'<span style="--c:{TIER[t]}">{TNAME[t]} · {P["sev"][t]}</span>' for t in ("r", "o", "y", "g"))
    kpis = _mod_stats(P)
    return f"""
<section class="view mod" id="v-{esc(P['code'])}" data-id="{esc(P['code'])}">
  <div class="top">
    <div class="ttl">
      <button class="back" data-go="summary" title="All modalities (Esc)">← All modalities</button>
      <div class="kick rv">{esc(exam.code)} · modality {i} of {n}</div>
      <h1 class="rv">{_icon(P['label'])}{esc(P['label'])}</h1>
    </div>
    {kpis}
  </div>
  <p class="lead rv">{head} <span class="ctx">{ctx}</span></p>
  <div class="vtabs seg big" data-tabs-for="v-{esc(P['code'])}">
    <button data-tab="dash" class="sel">Dashboard</button><button data-tab="clock">Clock &amp; rings</button>
    <span class="hint">Click any centre to open it</span></div>
  <div class="pane cgrid" data-pane="clock" hidden>
    <div class="panel rv"><div class="fig">Time of day · each shift on its own 12-hour clock</div>
      <div class="clockrow">{_clock_cells(P.get("clock"))}</div>
      <div class="cap">The shaded wedge is the exam window; each line is a 30-minute slot, longer means more alerts. Hover a line for its count.</div></div>
    <div class="panel rv"><div class="fig">At a glance</div><div class="mrings">{_mod_rings(P)}</div></div>
  </div>
  <div class="mgrid pane" data-pane="dash">
    <div class="panel a rv"><div class="fig">{"Top centres by alerts" if _flat(P) else esc(fr['top'])}</div><div class="fill top">{_bars(P)}</div></div>
    <div class="panel s rv"><div class="fig">Every centre · one tile each, worst first</div><div class="fill">{_hexes(P)}</div>
      <div class="legend">{legend}<span class="sil">Silent · {max(0, (P.get("all_centres") or 0) - P["centres"])}</span></div></div>
    <div class="panel b rv"><div class="fig">{esc(fr['geo'])}</div><div class="mapslot"></div>{_dleg(P)}</div>
    <div class="panel c rv"><div class="fig">{esc(fr['time'])} · every alert a dot</div><div class="fill">{_dots(P)}</div></div>
    <div class="panel d rv"><div class="fig">Severity tiers · where in the centre</div>{_tiers(P)}</div>
  </div>
  <div class="nav"><button data-step="-1" title="Previous (←)">‹</button><button data-step="1" title="Next (→)">›</button></div>
</section>"""


CSS = """
:root{--navy:%(navy)s;--navy2:%(navy2)s;--red:%(red)s;--ink:%(ink)s;--mut:%(mut)s;--grey:%(grey)s;
  --g1:#8A97A6;--g3:#D5DAE0;--g4:#E6EAEE;--paper:#FBFBFC;--panel:#FFFFFF}
*{box-sizing:border-box;margin:0}
html,body{height:100%%;overflow:hidden}
body{background:var(--paper);color:var(--ink);font-family:Jost,sans-serif;-webkit-font-smoothing:antialiased}
button{font:inherit;color:inherit;background:none;border:0;cursor:pointer}
.band{position:fixed;inset:0 0 auto 0;height:5px;z-index:5;background:linear-gradient(90deg,var(--red) 0 22%%,var(--navy) 22%% 100%%);
  transform-origin:left;animation:grow 1.2s cubic-bezier(.2,.7,.2,1) both}
.band::after{content:"";position:absolute;inset:0;background:linear-gradient(90deg,transparent,rgba(255,255,255,.55),transparent);
  width:18%%;animation:sheen 5s ease-in-out 1.4s infinite}
@keyframes grow{from{transform:scaleX(0)}}
@keyframes sheen{0%%{transform:translateX(-100%%)}60%%,100%%{transform:translateX(600%%)}}

.view{position:fixed;inset:5px 0 0 0;padding:2.4vh 2.6vw 2vh;display:flex;flex-direction:column;gap:1.6vh;
  visibility:hidden;opacity:0;pointer-events:none}
.view.cur{visibility:visible;opacity:1;pointer-events:auto}
.view.enter{animation:vin .75s cubic-bezier(.2,.8,.2,1) both}
.view.leave{visibility:visible;animation:vout .45s ease both}
.view.enter.fwd{animation-name:vinR}.view.leave.fwd{animation-name:voutL}
.view.enter.bk{animation-name:vinL}.view.leave.bk{animation-name:voutR}
@keyframes vin{from{opacity:0;transform:scale(.94);filter:blur(6px)}}
@keyframes vout{to{opacity:0;transform:scale(1.05);filter:blur(6px)}}
@keyframes vinR{from{opacity:0;transform:translateX(6vw)}}@keyframes voutL{to{opacity:0;transform:translateX(-6vw)}}
@keyframes vinL{from{opacity:0;transform:translateX(-6vw)}}@keyframes voutR{to{opacity:0;transform:translateX(6vw)}}

.top{display:flex;justify-content:space-between;align-items:flex-end;gap:3vw}
.kick{font-size:clamp(10px,1.15vh,13px);font-weight:600;letter-spacing:.16em;text-transform:uppercase;color:var(--red)}
h1{font-size:clamp(22px,4.2vh,46px);font-weight:700;line-height:1.05;letter-spacing:-.01em;margin-top:.6vh;display:flex;align-items:center;gap:.9vw}
h1 .ico{width:1em;height:1em;stroke:var(--navy)}
.exam{font-family:SourceSerif,serif;font-size:clamp(12px,1.7vh,18px);color:var(--mut);margin-top:.4vh}
.back{font-size:clamp(11px,1.4vh,14px);font-weight:600;color:var(--navy);margin-bottom:1vh;padding:.4vh 0;
  border-bottom:1.5px solid transparent;transition:border-color .2s,transform .2s}
.back:hover{border-color:var(--navy);transform:translateX(-3px)}
.lead{font-family:SourceSerif,serif;font-size:clamp(14px,2.3vh,24px);line-height:1.35;max-width:78vw}
.lead b{font-family:Jost,sans-serif;font-weight:700;color:var(--red)}
.lead .ctx{color:var(--mut);font-size:.8em}
.kpis{display:flex;gap:2.4vw;flex-shrink:0}
.kpi{min-width:5vw}
.kn{font-family:IBMPlexMono,monospace;font-size:clamp(18px,3.6vh,38px);font-weight:500;color:var(--navy);line-height:1}
.kn.txt{font-size:clamp(13px,2.3vh,24px)}
.kpi.red .kn{color:var(--red)}
.kl{font-size:clamp(9px,1.1vh,12px);letter-spacing:.09em;text-transform:uppercase;color:var(--mut);margin-top:.6vh}

.panel{background:var(--panel);border:1px solid var(--g4);border-radius:6px;padding:1.4vh 1.2vw;display:flex;flex-direction:column;min-height:0;min-width:0}
.fig{font-size:clamp(10px,1.25vh,13px);font-weight:700;letter-spacing:.1em;text-transform:uppercase;color:var(--red);margin-bottom:.8vh}
.fill{flex:1;min-height:0;display:flex}
.fill svg,.mapslot svg{width:100%%;height:100%%;display:block;overflow:visible}
.mapslot{flex:1;min-height:0;position:relative}
.cap{font-size:clamp(10px,1.2vh,12px);color:var(--g1);margin-top:.6vh}

/* summary */
.sgrid{flex:1;min-height:0;display:grid;grid-template-columns:2.15fr 1fr;gap:1.4vw}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);grid-auto-rows:1fr;gap:1.1vw;min-height:0}
.tile{position:relative;text-align:left;background:var(--panel);border:1px solid var(--g4);border-radius:6px;
  padding:1.3vh 1vw 1vh;display:flex;flex-direction:column;min-height:0;overflow:hidden;
  transition:transform .25s cubic-bezier(.2,.8,.2,1),box-shadow .25s,border-color .25s}
.tile::before{content:"";position:absolute;left:0;top:0;bottom:0;width:3px;background:var(--navy);transform:scaleY(0);
  transform-origin:top;transition:transform .3s}
.tile.hot::before{background:var(--red)}
.tile:hover{transform:translateY(-4px);box-shadow:0 12px 26px -14px rgba(30,42,61,.45);border-color:var(--g3)}
.tile:hover::before{transform:scaleY(1)}
.tile:active{transform:scale(.97)}
.th{display:flex;align-items:center;gap:.6vw}
.tile .ico{width:clamp(18px,2.8vh,30px);height:clamp(18px,2.8vh,30px);stroke:var(--navy);flex-shrink:0}
.tile.hot .ico{stroke:var(--red)}
.tname{font-size:clamp(11px,1.45vh,15px);font-weight:600;line-height:1.15}
.tn{font-family:IBMPlexMono,monospace;font-size:clamp(18px,3.4vh,36px);font-weight:500;color:var(--navy);margin-top:.8vh;line-height:1}
.tsub{font-size:clamp(10px,1.2vh,12px);color:var(--mut);margin-top:.4vh}.tsub .red{color:var(--red);font-weight:600}
.spark{flex:1;min-height:12px;width:100%%;margin-top:.6vh}
.spark .sl{fill:none;stroke:var(--navy2);stroke-width:2}.tile.hot .spark .sl{stroke:var(--red)}
.spark .sa{fill:var(--navy);fill-opacity:.07}
.tbar{display:flex;height:5px;border-radius:3px;overflow:hidden;gap:2px;margin-top:.6vh}
.tbar i{display:block}
.go{position:absolute;right:1vw;top:1.3vh;font-size:clamp(9px,1.1vh,12px);font-weight:600;color:var(--navy);opacity:0;
  transform:translateX(-6px);transition:.25s}
.tile:hover .go{opacity:1;transform:none}
.mapcol .mapslot{flex:1}

/* modality */
.mod .ttl{min-width:0}
.mgrid{flex:1;min-height:0;display:grid;grid-template-columns:1.12fr 1fr .92fr;grid-template-rows:1fr 1fr;gap:1vw}
.mgrid .a{grid-row:1;grid-column:1}.mgrid .s{grid-row:1;grid-column:2}.mgrid .b{grid-row:1 / 3;grid-column:3}
.mgrid .c{grid-row:2;grid-column:1}.mgrid .d{grid-row:2;grid-column:2}
.split{flex:1;min-height:0;display:grid;grid-template-columns:1.05fr 1fr;gap:1vw}
.split .top{align-items:flex-start}
.empty.sm{font-size:13px}
/* ranked lollipops */
.lname{font-size:19px;font-weight:500;fill:var(--ink)}
.track{stroke:var(--g4);stroke-width:2}
.stem{stroke-width:4;stroke-linecap:round}
.lval{font-family:IBMPlexMono,monospace;font-size:19px;font-weight:600}
.lval,.olab,.thr text,.peak text,.lname{paint-order:stroke;stroke:#fff;stroke-width:5px;stroke-linejoin:round}
.tick.sm,.thr text.sm{font-size:16px}
.hit{fill:transparent}.lol{cursor:pointer}.lol:hover .hit{fill:var(--g4);fill-opacity:.55}
/* ring */
.rtrack{fill:none;stroke:var(--g4);stroke-width:22}
.arc{fill:none;stroke-width:22;stroke-dasharray:0 100;stroke-dashoffset:var(--o)}
.rnum{font-family:IBMPlexMono,monospace;font-size:46px;font-weight:600;fill:var(--navy)}.rnum.red{fill:var(--red)}
.rcap{font-size:14px;fill:var(--mut);letter-spacing:.04em}
.rlt{font-size:17px;fill:var(--ink)}.rln{font-family:IBMPlexMono,monospace;font-size:18px;font-weight:600;fill:var(--navy)}
/* camera locations */
.sbn{font-size:15px;fill:var(--ink)}.sbt{fill:var(--g4)}.sbv{font-family:IBMPlexMono,monospace;font-size:15px;font-weight:600;fill:var(--mut)}
/* curve extras */
.hband{fill:var(--g4);fill-opacity:.45}
.pring{fill:none;stroke:var(--red);stroke-width:2.5}.pdot{fill:var(--red);stroke:#fff;stroke-width:2}
.legend{display:flex;gap:1.4vw;flex-wrap:wrap;font-size:clamp(10px,1.2vh,12px);color:var(--mut);margin-top:.5vh}
.legend span::before{content:"";display:inline-block;width:9px;height:9px;border-radius:50%%;background:var(--c);margin-right:6px}
.nav{position:absolute;right:2.6vw;bottom:2vh;display:flex;gap:8px;z-index:3}
.nav button{width:34px;height:34px;border-radius:50%%;border:1px solid var(--g3);background:var(--panel);font-size:20px;
  color:var(--navy);line-height:1;transition:.2s}
.nav button:hover{background:var(--navy);color:#fff;border-color:var(--navy)}
.empty{font-family:SourceSerif,serif;color:var(--mut);margin:auto}

svg{font-family:Jost,sans-serif}
.grid{stroke:var(--g3);stroke-width:1}.grid.v{stroke:var(--g4)}
.tick{font-family:IBMPlexMono,monospace;font-size:19px;fill:var(--mut)}
.axt{font-size:19px;fill:var(--mut)}
.thr line{stroke-width:2;stroke-dasharray:7 5;transform-box:fill-box;transform-origin:left bottom}.thr text{font-size:18px;font-weight:700}
.olab{font-size:21px;font-weight:700;fill:var(--ink)}
.pt{fill-opacity:.62;stroke:#fff;stroke-width:1.2;cursor:pointer}.pt.tr{fill-opacity:.95}
.pt:hover{fill-opacity:1;stroke:var(--ink);stroke-width:2.5}
.area{stroke:none}
.line{fill:none;stroke:var(--navy);stroke-width:3;stroke-linejoin:round}
.head{fill:var(--red);stroke:#fff;stroke-width:2;opacity:0}
.peak rect{fill:var(--red);fill-opacity:.13}.peak text{font-size:19px;font-weight:700;fill:var(--red)}
.dpath{transition:fill .9s ease,opacity .5s ease,transform .5s ease;transform-box:fill-box;transform-origin:center;cursor:default}
.dpath:hover{stroke:var(--ink);stroke-width:1.6}

#tip{position:fixed;pointer-events:none;background:var(--ink);color:#fff;padding:8px 11px;border-radius:4px;
  font-size:13px;line-height:1.45;opacity:0;transition:opacity .12s;max-width:270px;z-index:9}
#tip .m{font-family:IBMPlexMono,monospace;color:var(--g3)}

/* ---------- motion: replayed each time a view opens (.on) ---------- */
.rv{opacity:0;transform:translateY(14px)}
.on .rv{animation:rise .8s cubic-bezier(.2,.8,.2,1) both}
.on .rv:nth-of-type(2){animation-delay:.08s}.on .rv:nth-of-type(3){animation-delay:.16s}
.on .lead{animation-delay:.3s}.on .panel.a{animation-delay:.35s}.on .panel.b{animation-delay:.5s}.on .panel.c{animation-delay:.65s}
.on .mapcol{animation-delay:.4s}
@keyframes rise{to{opacity:1;transform:none}}
.kpi{opacity:0}.on .kpi{animation:rise .7s cubic-bezier(.2,.8,.2,1) both}
.on .kpi:nth-child(1){animation-delay:.15s}.on .kpi:nth-child(2){animation-delay:.22s}.on .kpi:nth-child(3){animation-delay:.29s}
.on .kpi:nth-child(4){animation-delay:.36s}.on .kpi:nth-child(5){animation-delay:.43s}.on .kpi:nth-child(6){animation-delay:.5s}
.on .kpi.red .kn{animation:flash 1.1s ease 1.6s 2}
@keyframes flash{50%%{text-shadow:0 0 18px rgba(182,64,58,.55)}}

.tile{opacity:0}
.on .tile{animation:tilein .7s cubic-bezier(.2,.9,.25,1.15) calc(.35s + var(--i) * .07s) both}
@keyframes tilein{from{opacity:0;transform:translateY(26px) scale(.92)}to{opacity:1;transform:none}}
.on .tile.hot::before{animation:barin .5s ease calc(1.1s + var(--i) * .07s) both}
@keyframes barin{to{transform:scaleY(1)}}
.ico *{fill:none;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round;stroke-dasharray:1;stroke-dashoffset:1}
.on .ico *{animation:draw 1s ease calc(.5s + var(--i,0) * .07s) forwards}
@keyframes draw{to{stroke-dashoffset:0}}
.ico [stroke-dasharray="3 2.4"]{stroke-dasharray:3 2.4;stroke-dashoffset:0}
.spark .sl{stroke-dasharray:1;stroke-dashoffset:1}
.on .spark .sl{animation:draw 1.4s cubic-bezier(.45,.05,.3,1) calc(.8s + var(--i) * .07s) forwards}
.spark .sa{opacity:0}.on .spark .sa{animation:fade .8s ease calc(1.8s + var(--i) * .07s) forwards}
.tbar i{transform:scaleX(0);transform-origin:left}
.on .tbar i{animation:barx .6s cubic-bezier(.2,.8,.2,1) calc(var(--d) + var(--i) * .07s) forwards}
@keyframes barx{to{transform:scaleX(1)}}
.on .tile.hot .ico{animation:beat 2.4s ease-in-out 2.4s infinite}
@keyframes beat{0%%,100%%{transform:scale(1)}8%%{transform:scale(1.18)}16%%{transform:scale(1)}}

.pt{opacity:0;transform-box:fill-box;transform-origin:center;transform:scale(0)}
.on .pt{animation:pop .5s cubic-bezier(.3,1.7,.5,1) calc(var(--d) + .4s) both}
.on .pt.tr{animation:pop .5s cubic-bezier(.3,1.7,.5,1) calc(var(--d) + .4s) both,ring 2.2s ease-out calc(var(--d) + 1s) infinite}
@keyframes pop{to{opacity:1;transform:scale(1)}}
@keyframes ring{0%%{stroke:var(--red);stroke-width:1;stroke-opacity:1}70%%,100%%{stroke:var(--red);stroke-width:16;stroke-opacity:0}}
.thr line{transform:scale(0)}.on .thr line{animation:grow2 .9s cubic-bezier(.2,.8,.2,1) 1.9s forwards}
@keyframes grow2{to{transform:none}}
.thr text,.olab{opacity:0}.on .thr text{animation:fade .5s ease 2.5s forwards}
.on .olab{animation:rise .6s ease 2.4s both}
.line{stroke-dasharray:1;stroke-dashoffset:1}
.on .line{animation:draw 2.9s cubic-bezier(.45,.05,.3,1) .9s forwards}
.area{opacity:0}.on .area{animation:fade 1s ease 3.4s forwards}
.peak{opacity:0}.on .peak{animation:fade .4s ease calc(var(--d) + .9s) forwards,blink 1.6s ease calc(var(--d) + 1.3s) 3}
@keyframes blink{50%%{opacity:.45}}
.on .panel.s{animation-delay:.45s}.on .panel.d{animation-delay:.75s}
/* lollipops: names slide in, the stem grows, the dot rides out to the value */
.lol .lname{opacity:0}.on .lol .lname{animation:rise .5s ease var(--d) both}
.stem{transform-box:fill-box;transform-origin:left center;transform:scaleX(0)}
.on .stem{animation:barx .9s cubic-bezier(.2,.8,.2,1) calc(var(--d) + .25s) forwards}
.ldot{transform:translateX(var(--dx));opacity:0}
.on .ldot{animation:ride .9s cubic-bezier(.2,.8,.2,1) calc(var(--d) + .25s) forwards}
@keyframes ride{0%%{opacity:1;transform:translateX(var(--dx))}100%%{opacity:1;transform:none}}
.on .ldot.lr{animation:ride .9s cubic-bezier(.2,.8,.2,1) calc(var(--d) + .25s) forwards,glow 2.2s ease-out calc(var(--d) + 1.3s) infinite}
@keyframes glow{0%%{stroke:var(--red);stroke-width:0;stroke-opacity:.7}100%%{stroke:var(--red);stroke-width:18;stroke-opacity:0}}
.lval{opacity:0}.on .lval{animation:fade .4s ease calc(var(--d) + 1s) forwards}
/* ring sweeps round tier by tier */
.on .arc{animation:sweep 1s cubic-bezier(.45,.05,.3,1) var(--d) forwards}
@keyframes sweep{to{stroke-dasharray:var(--s) 100}}
.rleg{opacity:0}.on .rleg{animation:rise .5s ease var(--d) both}
/* camera-location bars */
.sbr{transform-box:fill-box;transform-origin:left;transform:scaleX(0)}
.on .sbr{animation:barx .8s cubic-bezier(.2,.8,.2,1) var(--d) forwards}
.sb text{opacity:0}.on .sb text{animation:fade .4s ease var(--d) forwards}
.pring{transform-box:fill-box;transform-origin:center}
.on .peak .pring{animation:pulse 1.8s ease-out calc(var(--d) + 1.2s) infinite}
@keyframes pulse{0%%{transform:scale(.6);opacity:1}100%%{transform:scale(2.2);opacity:0}}
@keyframes fade{to{opacity:1}}

@media (max-width:900px),(max-height:520px){html,body{overflow:auto}.view{position:absolute;min-height:100%%;height:auto}
  .top{flex-direction:column;align-items:flex-start}.kpis{flex-wrap:wrap}.sgrid,.mgrid{grid-template-columns:1fr;grid-template-rows:auto}
  .tiles{grid-template-columns:repeat(2,1fr)}.mgrid>.panel{grid-row:auto!important;grid-column:auto!important;min-height:300px}
  .mapcol{min-height:320px}.tile{min-height:150px}}
@media (prefers-reduced-motion:reduce){*,*::before,*::after{animation-duration:.01s!important;animation-delay:0s!important;
  animation-iteration-count:1!important;transition:none!important}}
"""

JS = r"""
(()=>{
const D=JSON.parse(document.getElementById('cvdata').textContent);
const order=D.order, views={};
document.querySelectorAll('.view').forEach(v=>views[v.dataset.id]=v);
const map=document.querySelector('#mapsrc svg'), paths=[...map.querySelectorAll('.dpath')];
const base={};paths.forEach(p=>base[p.dataset.d]=p.getAttribute('fill'));
const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
let cur=null, curMap=null;

function fmt(n){return n.toLocaleString('en-IN')}
function count(el,delay){const n=+el.dataset.n;el.textContent='0';
  if(reduce){el.textContent=fmt(n);return}
  setTimeout(()=>{const t0=performance.now(),dur=1500;
    (function f(t){const k=Math.min(1,(t-t0)/dur),e=1-Math.pow(1-k,4);
      el.textContent=fmt(Math.round(n*e));if(k<1)requestAnimationFrame(f)})(t0)},delay)}
function recolour(id){curMap=D.maps[id];
  paths.forEach((p,i)=>{const f=curMap.fills[p.dataset.d]||base[p.dataset.d];
    p.style.transitionDelay=reduce?'0s':(Math.random()*.6).toFixed(2)+'s';p.style.fill=f;
    if(!reduce){p.style.opacity=0;p.style.transform='scale(.9)';
      requestAnimationFrame(()=>requestAnimationFrame(()=>{p.style.opacity=1;p.style.transform='none'}))}})}
function runHead(v){const line=v.querySelector('.line'),head=v.querySelector('.head');if(!line||!head||reduce)return;
  const L=line.getTotalLength(),t0=performance.now()+900,dur=2900;head.style.opacity=0;
  (function f(t){const k=Math.max(0,Math.min(1,(t-t0)/dur)),e=k<.5?2*k*k:1-Math.pow(-2*k+2,2)/2;
    const p=line.getPointAtLength(L*e);head.setAttribute('cx',p.x);head.setAttribute('cy',p.y);
    head.style.opacity=k>0&&k<1?1:(k>=1?1:0);if(k<1&&v===cur)requestAnimationFrame(f)})(performance.now())}

const VE=document.getElementById('veil');let vlast=-1,vpend=null;
function labelFor(id){if(id==='summary')return ['Overview','All AI modalities'];
  if(id==='centre'){const c=D.centres[window.CV&&CV.cc];return ['Centre',c?c.n:'Centre']}
  if(id==='district')return ['District',(window.CV&&CV.dd)||'District'];
  return ['Modality',(D.mods[id]||{}).l||id]}
// The loading screen: one of the report's own duotone photographs, chosen at
// random (never the same twice running), with the screen being opened named on it.
function through(lab,fn){const lb=document.getElementById('lb');
  if(reduce||!cur||!VE||(lb&&!lb.hidden)){fn();return}
  if(vpend){clearTimeout(vpend.t);vpend.fn=fn}else{
    const ph=VE.querySelectorAll('.vph');let k=0;
    if(ph.length>1)do{k=Math.floor(Math.random()*ph.length)}while(k===vlast);vlast=k;
    ph.forEach((p,i)=>p.classList.toggle('sel',i===k));
    VE.querySelector('.vcred').textContent=ph[k]?ph[k].dataset.cap:'';
    VE.classList.remove('out','in');VE.hidden=false;void VE.offsetWidth;VE.classList.add('in');vpend={fn}}
  VE.querySelector('.vkick').textContent=lab[0];VE.querySelector('.vlab').textContent=lab[1];
  vpend.t=setTimeout(()=>{const f=vpend.fn;vpend=null;f();VE.classList.remove('in');VE.classList.add('out');
    setTimeout(()=>{if(!vpend){VE.hidden=true;VE.classList.remove('out')}},480)},780)}
function show(id,dir){const v=views[id];if(!v||v===cur)return;through(labelFor(id),()=>_show(id,dir))}
function _show(id,dir){const v=views[id];if(!v||v===cur)return;
  document.querySelectorAll('#rail [data-go]').forEach(b=>b.classList.toggle('sel',b.dataset.go===(id==='centre'||id==='district'?'':id)));
  const old=cur;cur=v;
  if(old){old.classList.remove('cur','enter','fwd','bk','on');old.classList.add('leave');if(dir)old.classList.add(dir);
    setTimeout(()=>old.classList.remove('leave','fwd','bk'),460)}
  v.classList.remove('on');void v.offsetWidth;
  v.classList.add('cur','enter','on');if(dir)v.classList.add(dir);
  const ms=v.querySelector('.mapslot');if(ms&&D.maps[id]){ms.appendChild(map);recolour(id)}
  v.querySelectorAll('[data-n]').forEach((el,i)=>count(el,250+i*60));
  runHead(v);
  const hs=id==='summary'?'':(id==='centre'?'C-'+(window.CV&&CV.cc||''):id==='district'?'D-'+encodeURIComponent(window.CV&&CV.dd||''):id);
  if(location.hash.slice(1)!==hs)history.replaceState(null,'',hs?'#'+hs:location.pathname);
}
function step(k){const i=order.indexOf(cur.dataset.id);if(i<0)return show(order[k>0?0:order.length-1],k>0?'fwd':'bk');
  show(order[(i+k+order.length)%order.length],k>0?'fwd':'bk')}

document.addEventListener('click',e=>{const g=e.target.closest('[data-go]');if(g)return show(g.dataset.go);
  const s=e.target.closest('[data-step]');if(s)step(+s.dataset.step)});
document.addEventListener('keydown',e=>{if(e.key==='Escape')show('summary');
  else if(e.key==='ArrowRight')step(1);else if(e.key==='ArrowLeft')step(-1)});

const tip=document.getElementById('tip');
function place(ev,h){tip.innerHTML=h;const w=tip.offsetWidth;
  tip.style.left=Math.min(ev.clientX+14,innerWidth-w-8)+'px';tip.style.top=(ev.clientY+14)+'px';tip.style.opacity=1}
document.addEventListener('mousemove',e=>{const p=e.target.closest('.pt,[data-tip]');
  if(p){const d=JSON.parse(p.dataset.tip);return place(e,`<b>${d.n}</b><br>${d.d}<br><span class="m">${d.a} alerts · ${d.m} · ${d.t}</span>`)}
  const q=e.target.closest('.dpath');
  if(q&&curMap){const n=curMap.counts[q.dataset.d]||0;return place(e,`<b>${q.dataset.d}</b><br><span class="m">${fmt(n)} alerts</span>`)}
  tip.style.opacity=0});

window.CV={show,through,count,runHead,recolour,D,views,get cur(){return cur},replay(v){v.classList.remove('on');void v.offsetWidth;v.classList.add('on');
  v.querySelectorAll('[data-n]').forEach((el,i)=>count(el,200+i*50));runHead(v)}};
const start=location.hash.slice(1);if(!start.startsWith('C-')&&!start.startsWith('D-'))show(views[start]?start:'summary');
})();
"""


# ---------------------------------------------------------------- centre view, evidence, paper
DISTRICT_VIEW = """
<section class="view district" id="v-district" data-id="district">
  <div class="top">
    <div class="ttl">
      <div class="crumbs"><button data-go="summary">All modalities</button><span>›</span><b id="db-d"></b></div>
      <div class="kick rv" id="d-kick"></div>
      <h1 class="rv" id="d-name"></h1>
      <div class="exam rv" id="d-sub"></div>
    </div>
    <div class="stats dstats" id="d-stats"></div>
  </div>
  <p class="lead rv" id="d-lead"></p>
  <div class="dtgrid">
    <div class="panel a rv"><div class="fig">Centres in this district · click one to open it</div><div class="fill top" id="d-centres"></div></div>
    <div class="panel b rv"><div class="fig">Alerts by modality · click one to open it</div><div class="fill top" id="d-mods"></div></div>
    <div class="panel c rv"><div class="fig">When its alerts fired · the exam day as a dial</div><div class="fill" id="d-dial"></div></div>
    <div class="panel m rv"><div class="fig">Where it sits</div><div class="mapslot"></div>
      <div class="cap">Click any other district to open it.</div></div>
  </div>
  <div class="nav"><button data-dstep="-1" title="Previous district (←)">‹</button><button data-dstep="1" title="Next district (→)">›</button></div>
</section>"""

JS3 = r"""
(()=>{
const D=CV.D,C=D.centres,M=D.mods,V=document.getElementById('v-district'),$=id=>document.getElementById(id);
const TC={r:'#B6403A',o:'#3B5877',y:'#7189A4',g:'#B8C0CA'},TN={r:'Critical',o:'High',y:'Elevated',g:'Normal'};
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=n=>(+n).toLocaleString('en-IN');
const DIS={};Object.entries(C).forEach(([cc,c])=>{if(!c.d)return;const d=DIS[c.d]||(DIS[c.d]={n:c.d,t:0,cs:[],m:{},crit:0,mins:[]});
  d.t+=c.t;d.cs.push(cc);Object.entries(c.m).forEach(([k,ms])=>{d.m[k]=(d.m[k]||0)+ms.length;d.mins.push(...ms)});
  d.crit+=Object.values(c.tr).filter(t=>t==='r').length});
const dorder=Object.keys(DIS).sort((a,b)=>DIS[b].t-DIS[a].t);
CV.districts=DIS;

function hbars(rows,W){ // rows: [label, value, colour, attr]
  const mx=Math.max(1,...rows.map(r=>r[1])),rh=34;
  return `<svg viewBox="0 0 ${W} ${rh*rows.length+4}" preserveAspectRatio="xMidYMin meet" style="width:100%;max-height:100%">`+
    rows.map(([l,v,col,at],i)=>{const y=i*rh,w=(W-70)*v/mx;
      return `<g class="sb" ${at} style="--d:${(.5+i*.06).toFixed(2)}s"><text x="0" y="${y+13}" class="sbn">${esc(l)}</text>
      <rect class="sbt" x="0" y="${y+19}" width="${W-70}" height="9" rx="4.5"/>
      <rect class="sbr" x="0" y="${y+19}" width="${Math.max(4,w).toFixed(1)}" height="9" rx="4.5" fill="${col}"/>
      <text x="${W}" y="${y+28}" class="sbv" text-anchor="end">${fmt(v)}</text></g>`}).join('')+'</svg>'}

function dial(mins){const lo=D.lo,hi=Math.max(D.lo+60,D.hi),n=Math.ceil((hi-lo)/15),b=new Array(n).fill(0);
  mins.forEach(m=>{const i=Math.floor((m-lo)/15);if(i>=0&&i<n)b[i]++});
  const mx=Math.max(1,...b),pk=b.indexOf(Math.max(...b)),cx=120,cy=120,r0=46,r1=108,gap=26,sp=360-gap;let s='';
  s+=`<circle cx="${cx}" cy="${cy}" r="${r0-4}" class="dhub"/><circle cx="${cx}" cy="${cy}" r="${r1}" class="dring"/>`;
  b.forEach((v,i)=>{const a=(gap/2+sp*(i+.5)/n-90)*Math.PI/180,rr=r0+(r1-r0)*v/mx;
    s+=`<line class="db${i===pk?' pk':v?'':' z'}" x1="${(cx+Math.cos(a)*r0).toFixed(1)}" y1="${(cy+Math.sin(a)*r0).toFixed(1)}" x2="${(cx+Math.cos(a)*Math.max(rr,r0+1)).toFixed(1)}" y2="${(cy+Math.sin(a)*Math.max(rr,r0+1)).toFixed(1)}" pathLength="1" style="--d:${(.5+.9*i/n).toFixed(2)}s;--i:0;stroke-width:5"><title>${String(Math.floor((lo+i*15)/60)).padStart(2,'0')}:${String((lo+i*15)%60).padStart(2,'0')} · ${v} alerts</title></line>`});
  for(let m=Math.ceil(lo/60)*60;m<=hi;m+=60){const a=(gap/2+sp*(m-lo)/(hi-lo)-90)*Math.PI/180;
    s+=`<text x="${(cx+Math.cos(a)*(r1+13)).toFixed(1)}" y="${(cy+Math.sin(a)*(r1+13)+4).toFixed(1)}" text-anchor="middle" class="dlab" style="font-size:10px">${String(m/60).padStart(2,'0')}</text>`}
  const ph=lo+pk*15;
  s+=`<text x="${cx}" y="${cy-2}" text-anchor="middle" class="dnum" style="font-size:22px" data-n="${mins.length}">0</text>
      <text x="${cx}" y="${cy+16}" text-anchor="middle" class="dcap" style="font-size:10px">peak ${String(Math.floor(ph/60)).padStart(2,'0')}:${String(ph%60).padStart(2,'0')}</text>`;
  return `<svg class="dial big" viewBox="-14 -14 268 268">${s}</svg>`}

function fill(name){const d=DIS[name];CV.dd=name;
  const rank=dorder.indexOf(name)+1,cs=d.cs.slice().sort((a,b)=>C[b].t-C[a].t),worst=cs[0];
  const tops=Object.keys(d.m).sort((a,b)=>d.m[b]-d.m[a]);
  $('db-d').textContent=name;$('d-kick').textContent=`District · rank ${rank} of ${dorder.length} by alerts`;
  $('d-name').textContent=name;$('d-sub').textContent=`${d.cs.length} centres · ${tops.length} AI modalities fired here`;
  $('d-stats').innerHTML=[
    ['Alerts',`<b data-n="${d.t}">0</b><small>${(100*d.t/D.exam_alerts).toFixed(0)}% of all</small>`,`of ${fmt(D.exam_alerts)} in the examination.`],
    ['Centres',`<b data-n="${d.cs.length}">0</b><small>of ${Object.keys(C).length}</small>`,`Rank ${rank} of ${dorder.length} districts by alerts.`],
    ['Critical findings',`<b class="${d.crit?'red':''}" data-n="${d.crit}">0</b>`,'centre and modality pairs at critical.'],
    ['Worst centre',`<b class="txt lk" data-c="${esc(worst)}">${esc(C[worst].n.slice(0,22))}</b>`,`${fmt(C[worst].t)} alerts, ${(100*C[worst].t/d.t).toFixed(0)}% of this district's.`]]
    .map(([l,v,x],i)=>`<div class="st" style="--i:${i}"><div class="stl">${l}</div><div class="stv">${v}</div><div class="stc">${x}</div></div>`).join('');
  $('d-lead').innerHTML=`<b class="lk" data-go="${esc(tops[0])}">${esc(M[tops[0]].l)}</b> leads here with ${fmt(d.m[tops[0]])} alerts. `+
    `<span class="ctx">${esc(name)} raised ${fmt(d.t)} alerts across ${d.cs.length} centres; the busiest centre is `+
    `<span class="lk" data-c="${esc(worst)}">${esc(C[worst].n)}</span>.</span>`;
  $('d-centres').innerHTML=hbars(cs.slice(0,12).map((cc,i)=>{const c=C[cc];
    return [c.n.slice(0,34),c.t,i===0?TC.r:TC.o,`data-c="${esc(cc)}"`]}),460);
  $('d-mods').innerHTML=hbars(tops.map(k=>[M[k].l,d.m[k],TC.y,`data-go="${esc(k)}"`]),420);
  $('d-dial').innerHTML=dial(d.mins);
  const fills={};Object.keys(DIS).forEach(n=>fills[n]=n===name?'#B6403A':'#B8C0CA');
  D.maps.district={fills,counts:Object.fromEntries(Object.entries(DIS).map(([n,x])=>[n,x.t]))};
}
function open(name){if(!DIS[name])return;
  if(CV.cur===V)CV.through(['District',name],()=>{fill(name);CV.recolour('district');CV.replay(V);history.replaceState(null,'','#D-'+encodeURIComponent(name))});
  else{fill(name);CV.show('district')}}
CV.openDistrict=open;
function dstep(k){const i=dorder.indexOf(CV.dd);open(dorder[(i+k+dorder.length)%dorder.length])}

document.addEventListener('click',e=>{let t;
  if(t=e.target.closest('[data-dist]')){e.stopPropagation();open(t.dataset.dist);return}
  if(t=e.target.closest('[data-dstep]')){e.stopPropagation();dstep(+t.dataset.dstep);return}
  if((t=e.target.closest('.dpath'))&&DIS[t.dataset.d]){e.stopPropagation();open(t.dataset.d);return}
},true);
window.addEventListener('keydown',e=>{const lb=document.getElementById('lb');if((lb&&!lb.hidden)||document.body.classList.contains('touring'))return;
  if(CV.cur===V){if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.stopImmediatePropagation();dstep(e.key==='ArrowRight'?1:-1)}
    else if(e.key==='Escape'){e.stopImmediatePropagation();CV.show('summary')}}},true);
const h=decodeURIComponent(location.hash.slice(1));if(h.startsWith('D-')){if(DIS[h.slice(2)])open(h.slice(2));else CV.show('summary')}
})();
"""


CENTRE_VIEW = """
<section class="view centre" id="v-centre" data-id="centre">
  <div class="top">
    <div class="ttl">
      <div class="crumbs"><button data-go="summary">All modalities</button><span>›</span>
        <button id="cb-mod" data-go="summary">Modality</button><span>›</span><b id="cb-c"></b></div>
      <div class="kick rv" id="c-kick"></div>
      <h1 class="rv" id="c-name"></h1>
      <div class="exam rv" id="c-sub"></div>
    </div>
    <div class="stats" id="c-kpis"></div>
  </div>
  <p class="lead rv" id="c-lead"></p>
  <div class="ctgrid">
    <div class="panel a rv"><div class="fig">Alerts by modality · click one to open it</div><div class="fill top" id="c-bars"></div></div>
    <div class="panel b rv"><div class="phead"><div class="fig">Evidence frames · in time order</div>
      <button class="playall" data-play>▶ Play in sequence</button></div><div class="film" id="c-film"></div></div>
    <div class="panel c rv"><div class="fig">Through the day · every alert at this centre</div><div class="fill" id="c-lanes"></div></div>
    <div class="panel d rv"><div class="fig">At a glance</div><div class="mrings" id="c-rings"></div></div>
  </div>
  <div class="nav"><button data-cstep="-1" title="Previous centre (←)">‹</button><button data-cstep="1" title="Next centre (→)">›</button></div>
</section>"""

LIGHTBOX = """
<div id="lb" hidden>
  <div class="lbin">
    <div class="lbtop"><div id="lbtitle"></div><button data-lb="x" title="Close (Esc)">✕</button></div>
    <div class="lbstage"><button class="lbarrow" data-lb="-1" title="Previous (←)">‹</button>
      <figure><div class="lbimgw"><img id="lbimg" alt=""><img id="lbimg2" alt=""></div><figcaption id="lbcap"></figcaption></figure>
      <button class="lbarrow" data-lb="1" title="Next (→)">›</button></div>
    <div class="lbbar"><button data-lb="play" id="lbplay">▶ Play</button><span id="lbcount"></span>
      <div class="lbdots" id="lbdots"></div><span class="lbhint">Space plays · arrows step · the sequence runs on into the next centre</span></div>
  </div>
</div>"""


def _rail(profs) -> str:
    """Every modality, one click away from any screen: a slim column of the
    modality icons down the left edge, Overview at the top. Hover names it."""
    home = ('<button data-go="summary" class="sel" title="Overview (Esc)"><svg class="ico" viewBox="0 0 24 24">'
            '<rect x="3" y="3" width="7.5" height="7.5" rx="1"/><rect x="13.5" y="3" width="7.5" height="7.5" rx="1"/>'
            '<rect x="3" y="13.5" width="7.5" height="7.5" rx="1"/><rect x="13.5" y="13.5" width="7.5" height="7.5" rx="1"/></svg>'
            '<span class="rt"><b>Overview</b>all modalities</span></button>')
    items = "".join(
        f'<button data-go="{esc(p["code"])}" class="{"hot" if p["crit"] else ""}">{_icon(p["label"])}'
        f'<span class="rt"><b>{esc(p["label"])}</b>{p["total"]:,} alerts · {p["crit"]} critical</span></button>'
        for p in profs)
    return f'<nav id="rail">{home}<i class="rsep"></i>{items}</nav>'


JS4 = r"""
(()=>{
const D=CV.D,C=D.centres,M=D.mods,$=id=>document.getElementById(id);
const hub=document.querySelector('#v-summary .hub');if(!hub)return;
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=n=>(+n).toLocaleString('en-IN');
const hm=m=>String(Math.floor(m/60)).padStart(2,'0')+':'+String(m%60).padStart(2,'0');
const NAVY='#3B5877',NAVY2='#7189A4',RED='#B6403A';
const mods=Object.keys(M).sort((a,b)=>M[b].n-M[a].n);
const lo=D.lo,hi=Math.max(D.lo+60,D.hi),NB=Math.max(1,Math.round((hi-lo)/15));
const dists=[...new Set(Object.values(C).map(c=>c.d).filter(Boolean))];
// every alert as (modality, bin, district, centre)
const grid=(dist)=>{const g={};mods.forEach(k=>g[k]=new Array(NB).fill(0));
  Object.values(C).forEach(c=>{if(dist&&c.d!==dist)return;Object.entries(c.m).forEach(([k,ms])=>{if(!g[k])return;
    ms.forEach(m=>{const i=Math.floor((m-lo)/15);if(i>=0&&i<NB)g[k][i]++})})});return g};
const ramp=t=>{const a=[238,241,244],b=[59,88,119],e=Math.sqrt(t);return `rgb(${a.map((v,i)=>Math.round(v+(b[i]-v)*e)).join(',')})`};

// ---------------------------------------------------------------- the exam-day rings
const cx=300,cy=300,R0=86,R1=270,GAP=44,ringW=(R1-R0)/mods.length;
const ang=i=>(GAP/2+(360-GAP)*i/NB)*Math.PI/180;
const pt=(r,a)=>[cx+r*Math.sin(a),cy-r*Math.cos(a)];
function sector(r0,r1,a0,a1){const [x0,y0]=pt(r1,a0),[x1,y1]=pt(r1,a1),[x2,y2]=pt(r0,a1),[x3,y3]=pt(r0,a0);
  return `M${x0.toFixed(1)},${y0.toFixed(1)}A${r1},${r1} 0 0 1 ${x1.toFixed(1)},${y1.toFixed(1)}L${x2.toFixed(1)},${y2.toFixed(1)}A${r0},${r0} 0 0 0 ${x3.toFixed(1)},${y3.toFixed(1)}Z`}
let s=`<defs><linearGradient id="swg" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="${NAVY}" stop-opacity="0"/><stop offset="1" stop-color="${NAVY}" stop-opacity=".22"/></linearGradient></defs>`;
for(let m=Math.ceil(lo/60)*60;m<=hi;m+=60){const a=ang((m-lo)/15),[x0,y0]=pt(R0-6,a),[x1,y1]=pt(R1+6,a),[tx,ty]=pt(R1+22,a);
  s+=`<line class="htl" x1="${x0.toFixed(1)}" y1="${y0.toFixed(1)}" x2="${x1.toFixed(1)}" y2="${y1.toFixed(1)}"/><text class="htk" x="${tx.toFixed(1)}" y="${(ty+4).toFixed(1)}" text-anchor="middle">${hm(m)}</text>`}
mods.forEach((k,ri)=>{const r1=R1-ri*ringW,r0=r1-ringW+1.6;
  for(let i=0;i<NB;i++)s+=`<path class="hc" data-k="${k}" data-i="${i}" data-go="${k}" d="${sector(r0,r1,ang(i)+.006,ang(i+1)-.006)}" style="--d:${(.3+ri*.06+.9*i/NB).toFixed(2)}s"/>`;
  const [lx,ly]=pt((r0+r1)/2,ang(0)-.02);
  s+=`<text class="hrl" data-k="${k}" x="${(lx-4).toFixed(1)}" y="${(ly+4).toFixed(1)}" text-anchor="end">${esc(M[k].l.split(' · ')[0].slice(0,Math.max(5,Math.floor(((r0+r1)/2)*GAP*Math.PI/180/6.4))))}</text>`});
const sw0=ang(0),[sx0,sy0]=pt(R1,0),[sx1,sy1]=pt(R1,.5);
s+=`<path class="sweep" d="M${cx},${cy}L${pt(R1,-.5).map(v=>v.toFixed(1)).join(',')}A${R1},${R1} 0 0 1 ${pt(R1,0).map(v=>v.toFixed(1)).join(',')}Z" fill="url(#swg)"/>`;
s+=`<line class="hcur" id="h-cur" x1="${cx}" y1="${cy-R0}" x2="${cx}" y2="${cy-R1-4}"/>`;
s+=`<circle class="hcen" cx="${cx}" cy="${cy}" r="${R0-8}"/><text class="hct" id="h-ct" x="${cx}" y="${cy-26}" text-anchor="middle">All modalities</text>
  <text class="hcn" id="h-cn" x="${cx}" y="${cy+12}" text-anchor="middle">0</text><text class="hcs" id="h-cs" x="${cx}" y="${cy+34}" text-anchor="middle">alerts · ${hm(lo)}–${hm(hi)}</text>`;
$('h-radial').innerHTML=`<svg viewBox="-10 -10 620 620" preserveAspectRatio="xMidYMid meet">${s}</svg>`;
const cells=[...document.querySelectorAll('#h-radial .hc')];

// ---------------------------------------------------------------- the flow
const FW=600,FH=760,LX=210,RX=FW-170,NWd=13;
const flows={};mods.forEach(k=>flows[k]={});const dTot={};
Object.values(C).forEach(c=>{if(!c.d)return;Object.entries(c.m).forEach(([k,ms])=>{if(!flows[k])return;flows[k][c.d]=(flows[k][c.d]||0)+ms.length;dTot[c.d]=(dTot[c.d]||0)+ms.length})});
const dorder=dists.sort((a,b)=>(dTot[b]||0)-(dTot[a]||0));
const T=mods.reduce((a,k)=>a+M[k].n,0)||1;
const lg=5,rg=18,lAvail=FH-lg*(mods.length-1),rAvail=FH-rg*(dorder.length-1);
const ln={},rn={};let y=0;
mods.forEach(k=>{const h=Math.max(5,lAvail*M[k].n/T);ln[k]={y,h};y+=h+lg});
const lScale=(FH)/(y-lg);Object.values(ln).forEach(o=>{o.y*=lScale;o.h*=lScale});
y=0;const DT=dorder.reduce((a,d)=>a+(dTot[d]||0),0)||1;
dorder.forEach(d=>{const h=Math.max(10,rAvail*(dTot[d]||0)/DT);rn[d]={y,h};y+=h+rg});
const rScale=FH/(y-rg);Object.values(rn).forEach(o=>{o.y*=rScale;o.h*=rScale});
let f='',ff='',ri=0;const lOff={},rOff={},CL={};
mods.forEach(k=>lOff[k]=ln[k].y);dorder.forEach(d=>rOff[d]=rn[d].y);
mods.forEach(k=>dorder.forEach(d=>{const v=flows[k][d]||0;if(!v)return;
  const t1=ln[k].h*v/Math.max(1,M[k].n),t2=rn[d].h*v/Math.max(1,dTot[d]);
  const y1=lOff[k],y2=rOff[d];lOff[k]+=t1;rOff[d]+=t2;CL[k+'|'+d]={y1,t1,y2,t2};const x1=LX+NWd,x2=RX,xm=(x1+x2)/2;
  const col=M[k].c?NAVY:NAVY2;
  f+=`<path class="fr" data-k="${k}" data-d="${esc(d)}" data-go="${k}" fill="${col}" style="--d:${(.4+ri*.035).toFixed(2)}s"
     d="M${x1},${y1.toFixed(1)}C${xm},${y1.toFixed(1)} ${xm},${y2.toFixed(1)} ${x2},${y2.toFixed(1)}L${x2},${(y2+t2).toFixed(1)}C${xm},${(y2+t2).toFixed(1)} ${xm},${(y1+t1).toFixed(1)} ${x1},${(y1+t1).toFixed(1)}Z"><title>${esc(M[k].l)} → ${esc(d)}: ${fmt(v)} alerts</title></path>`;
  if(v/T>.025)ff+=`<path class="fflow" data-k="${k}" data-d="${esc(d)}" d="M${x1},${(y1+t1/2).toFixed(1)}C${xm},${(y1+t1/2).toFixed(1)} ${xm},${(y2+t2/2).toFixed(1)} ${x2},${(y2+t2/2).toFixed(1)}"/>`;
  ri++}));
let nodes='';const LY={};let prev=-1e9;
mods.forEach(k=>{const o=ln[k];LY[k]=Math.max(o.y+o.h/2+5,prev+19);prev=LY[k]});
let over=prev-(FH+4);if(over>0)for(let i=mods.length-1;i>=0;i--){const k=mods[i];LY[k]-=over;
  const nxt=i>0?LY[mods[i-1]]:-1e9;over=Math.max(0,nxt-(LY[k]-19))}
mods.forEach((k,i)=>{const o=ln[k];nodes+=`<rect class="fn" data-k="${k}" data-go="${k}" x="${LX}" y="${o.y.toFixed(1)}" width="${NWd}" height="${Math.max(2,o.h).toFixed(1)}" rx="2" fill="${M[k].c?RED:NAVY2}" style="--d:${(.2+i*.04).toFixed(2)}s"/>
  <text class="flab" data-k="${k}" data-go="${k}" x="${LX-8}" y="${LY[k].toFixed(1)}" text-anchor="end" style="--d:${(.5+i*.04).toFixed(2)}s">${esc(M[k].l.split(' · ')[0].slice(0,22))} <tspan class="fv">${fmt(M[k].n)}</tspan></text>`});
dorder.forEach((d,i)=>{const o=rn[d];nodes+=`<rect class="fn" data-dist="${esc(d)}" data-dd="${esc(d)}" x="${RX}" y="${o.y.toFixed(1)}" width="${NWd}" height="${o.h.toFixed(1)}" rx="2" fill="${NAVY}" style="--d:${(.6+i*.08).toFixed(2)}s"/>
  <text class="flab" data-dist="${esc(d)}" data-dd="${esc(d)}" x="${RX+NWd+8}" y="${(o.y+o.h/2-4).toFixed(1)}" style="--d:${(.9+i*.08).toFixed(2)}s">${esc(d)}<tspan class="fv" x="${RX+NWd+8}" dy="18">${fmt(dTot[d]||0)} · ${Math.round(100*(dTot[d]||0)/DT)}%</tspan></text>`});
$('h-flow').innerHTML=`<svg viewBox="-8 -8 ${FW+16} ${FH+16}" preserveAspectRatio="xMidYMid meet">${f}${ff}${nodes}</svg>`;

// ---------------------------------------------------------------- alerts in flight
const SVGN='http://www.w3.org/2000/svg',fsvg=$('h-flow').querySelector('svg'),FP=document.createElementNS(SVGN,'g');
FP.setAttribute('class','fpart');fsvg.appendChild(FP);
const parts=[];let praf=null;const landAt={};
function emit(k,d){const g=CL[k+'|'+d];if(!g||parts.length>180)return;const u=.15+.7*Math.random();
  const c=document.createElementNS(SVGN,'circle');c.setAttribute('r',M[k].c?3.4:2.7);c.setAttribute('class','fp'+(M[k].c?' c':''));
  c.setAttribute('cx',LX+NWd);c.setAttribute('cy',(g.y1+g.t1*u).toFixed(1));FP.appendChild(c);
  parts.push({c,ya:g.y1+g.t1*u,yb:g.y2+g.t2*u,d,t0:performance.now(),dur:1700+Math.random()*1100});if(!praf)praf=requestAnimationFrame(pstep)}
function pstep(now){praf=null;const x1=LX+NWd,x2=RX,xm=(x1+x2)/2;
  for(let i=parts.length-1;i>=0;i--){const p=parts[i];
    const u=Math.max(0,Math.min(1,(now-p.t0)/p.dur)),e=u<.5?2*u*u:1-Math.pow(-2*u+2,2)/2,m=1-e;
    const x=m*m*m*x1+3*m*m*e*xm+3*m*e*e*xm+e*e*e*x2,y=(m*m*m+3*m*m*e)*p.ya+(3*m*e*e+e*e*e)*p.yb;
    p.c.setAttribute('cx',x.toFixed(1));p.c.setAttribute('cy',y.toFixed(1));p.c.style.opacity=u<.12?u/.12:u>.88?(1-u)/.12:1;
    if(u>=1){p.c.remove();parts.splice(i,1);land(p.d)}}
  if(parts.length)praf=requestAnimationFrame(pstep)}
function land(d){const now=performance.now();if(now-(landAt[d]||0)<260)return;landAt[d]=now;
  const n=fsvg.querySelector(`.fn[data-dd="${CSS.escape(d)}"]`);if(n){n.classList.remove('hit');void n.getBBox();n.classList.add('hit')}
  const mp=document.querySelector(`#v-summary .dpath[data-d="${CSS.escape(d)}"]`);if(!mp)return;
  const b=mp.getBBox(),r=document.createElementNS(SVGN,'circle');
  r.setAttribute('cx',(b.x+b.width/2).toFixed(1));r.setAttribute('cy',(b.y+b.height/2).toFixed(1));r.setAttribute('r',(Math.max(b.width,b.height)*.7).toFixed(1));
  r.setAttribute('class','ripple');mp.parentNode.appendChild(r);setTimeout(()=>r.remove(),1500)}
const hdrN=document.querySelector('#v-summary .ht .htn b');
function hdrBack(){if(hdrN)hdrN.textContent=fmt(+hdrN.dataset.n)}
let emT=null,lbAt=0;
function flowTo(T){if(emT==null||T<emT){emT=T;return}let n=0;
  for(const [m,k,cc,d] of evs){if(m<=emT)continue;if(m>T)break;if(d&&n<10){emit(k,d);n++}}emT=T}

// ---------------------------------------------------------------- the leaderboard
const RH=34,lb=$('h-lb');lb.style.setProperty('--rh',RH+'px');
const ccs=Object.keys(C);
lb.innerHTML=ccs.map(cc=>{const c=C[cc];return `<div class="lr" data-c="${esc(cc)}" data-cc="${esc(cc)}" style="transform:translateY(${RH*30}px);opacity:0">
  <span class="lrn"></span><span class="lrm"><span class="lrname">${esc(c.n)}</span><span class="lrd">${esc(c.d||'')}</span></span>
  <span class="lrc">${mods.map(k=>`<i data-k="${k}" class="${c.m[k]?(c.tr[k]==='r'?'r':'on'):''}"></i>`).join('')}</span><b class="lrv"></b></div>`}).join('');
const rows={};lb.querySelectorAll('.lr').forEach(r=>rows[r.dataset.cc]=r);
function board(fmod,fdist,live){const fit=Math.max(4,Math.floor(lb.clientHeight/RH)||9);
  const val=cc=>live?(live[cc]||0):fmod?(C[cc].m[fmod]||[]).length:C[cc].t;
  const crit=cc=>Object.values(C[cc].tr).filter(t=>t==='r').length;
  let list=ccs.filter(cc=>(!fdist||C[cc].d===fdist)&&(!(fmod||live)||val(cc)>0));
  list.sort((a,b)=>(fmod||live)?(val(b)-val(a)):(crit(b)-crit(a))||(val(b)-val(a)));
  const pos={};list.slice(0,fit).forEach((cc,i)=>pos[cc]=i);
  ccs.forEach(cc=>{const r=rows[cc],i=pos[cc];
    if(i===undefined){r.style.opacity=0;r.style.pointerEvents='none';r.style.transform=`translateY(${RH*fit}px)`;return}
    r.style.opacity=1;r.style.pointerEvents='';r.style.transform=`translateY(${i*RH}px)`;r.style.transitionDelay=live?'0s':(i*.03)+'s';
    r.querySelector('.lrn').textContent=i+1;r.querySelector('.lrv').textContent=fmt(val(cc));
    r.querySelectorAll('.lrc i').forEach(x=>x.classList.toggle('fm',x.dataset.k===fmod))});
  if(live){$('h-lbt').textContent='Centres as the day unfolds';$('h-lbk').textContent='alerts so far';return}
  $('h-lbt').textContent=fmod?`Top centres · ${M[fmod].l}`:fdist?`Centres in ${fdist}`:'Centres to look at first';
  $('h-lbk').textContent=fmod?`alerts in ${M[fmod].l.split(' · ')[0]}`:'critical modalities first · alerts'}

// ---------------------------------------------------------------- one focus, four views
const cn=$('h-cn'),ct=$('h-ct'),cs=$('h-cs'),cur=$('h-cur');
let focus={k:null,d:null},timer=null,rp=null;
function paint(){const g=grid(focus.d);let mx=1,pk=null;
  mods.forEach(k=>g[k].forEach((v,i)=>{if((!focus.k||k===focus.k)&&v>mx){mx=v;pk=k+':'+i}}));
  cells.forEach(el=>{const k=el.dataset.k,i=+el.dataset.i,v=g[k][i];
    el.style.fill=(k+':'+i)===pk?RED:(v?ramp(v/mx):'#F4F6F8');el.classList.toggle('pkc',(k+':'+i)===pk);
    el.classList.toggle('fm',focus.k===k);el.dataset.v=v});
  document.querySelectorAll('#h-radial .hrl').forEach(t=>t.classList.toggle('fm',t.dataset.k===focus.k));
  hub.classList.toggle('f-mod',!!focus.k);hub.classList.toggle('f-dist',!!focus.d);
  document.querySelectorAll('#h-chord .chr').forEach(r=>{const m=focus.k&&(r.dataset.k===focus.k||r.dataset.k2===focus.k);
    r.classList.toggle('lit',!!m);r.classList.toggle('dim',!!(focus.k&&!m))});
  document.querySelectorAll('#h-chord .cha,#h-chord .chl').forEach(a=>a.classList.toggle('dim',!!(focus.k&&a.dataset.k!==focus.k&&!((D.co||{}).m&&coOf(focus.k,a.dataset.k)))));
  const hb=document.querySelector('#v-summary .htn b');if(hb&&hb.dataset.n)hb.textContent=fmt(+hb.dataset.n);
  document.querySelectorAll('#h-flow .fr').forEach(r=>r.style.fillOpacity='');
  document.querySelectorAll('#h-flow .fr,#h-flow .fflow').forEach(r=>{const m=(!focus.k||r.dataset.k===focus.k)&&(!focus.d||r.dataset.d===focus.d);
    const any=focus.k||focus.d;r.classList.toggle('lit',!!(any&&m));r.classList.toggle('dim',!!(any&&!m))});
  document.querySelectorAll('#h-flow .fn,#h-flow .flab').forEach(n=>{const any=focus.k||focus.d;
    const m=n.dataset.k?(!focus.k||n.dataset.k===focus.k):(!focus.d||n.dataset.dd===focus.d);
    n.classList.toggle('dim',!!(any&&!m));n.classList.toggle('lit',!!(any&&m&&(n.dataset.k?focus.k:focus.d)))});
  const tot=mods.reduce((a,k)=>a+(focus.k&&k!==focus.k?0:g[k].reduce((x,y)=>x+y,0)),0);
  ct.textContent=focus.k?M[focus.k].l.split(' · ')[0]:(focus.d||'All modalities');cn.textContent=fmt(tot);
  cs.textContent=focus.k&&focus.d?`alerts in ${focus.d}`:`alerts · ${hm(lo)}–${hm(hi)}`;
  board(focus.k,focus.d);
  $('h-mapt').textContent=focus.k?`${M[focus.k].l} by district`:'All alerts by district';
  if(focus.k&&D.maps[focus.k])CV.recolour(focus.k);
  else if(focus.d){document.querySelectorAll('#v-summary .dpath').forEach(pth=>{pth.style.transitionDelay='0s';
    pth.style.fill=pth.dataset.d===focus.d?NAVY:(pth.dataset.d in (D.maps.summary.counts||{})?'#C9D1DA':'')})}
  else CV.recolour('summary')}
function set(k,d){clearTimeout(timer);if(focus.k===k&&focus.d===d)return;focus={k,d};paint()}
function clear(){clearTimeout(timer);timer=setTimeout(()=>{cur.style.opacity=0;if(focus.k||focus.d){focus={k:null,d:null};paint()}},140)}
hub.addEventListener('mouseover',e=>{const t=e.target;if(rp)return;
  const cell=t.closest('#h-radial .hc');
  if(cell){set(cell.dataset.k,null);
    const i=+cell.dataset.i,a=(ang(i)+ang(i+1))/2*180/Math.PI;cur.setAttribute('transform',`rotate(${a.toFixed(1)} ${cx} ${cy})`);cur.style.opacity=1;
    ct.textContent=M[cell.dataset.k].l.split(' · ')[0];cn.textContent=fmt(+cell.dataset.v||0);
    cs.textContent=`${hm(lo+i*15)}–${hm(lo+i*15+15)}`;return}
  const km=t.closest('[data-k]:not(.lrc i)'),dd=t.closest('[data-dd]'),fr=t.closest('#h-flow .fr');
  if(fr){set(fr.dataset.k,fr.dataset.d);return}
  if(dd){set(null,dd.dataset.dd);return}
  if(km&&km.closest('#h-flow,#h-radial,#h-chord')){set(km.dataset.k,null);return}
  const dp=t.closest('#v-summary .dpath');if(dp&&dp.dataset.d in (D.maps.summary.counts||{})){set(null,dp.dataset.d);return}
  const row=t.closest('.lr');if(row)return;
  clear()});
hub.addEventListener('mouseleave',clear);

// ---------------------------------------------------------------- fired together (chord)
const CO=D.co||{codes:[],m:[]},coIdx={};CO.codes.forEach((k,i)=>coIdx[k]=i);
function coOf(a,b){const i=coIdx[a],j=coIdx[b];return (i===undefined||j===undefined)?0:CO.m[i][j]}
(function chord(){const ks=mods.filter(k=>k in coIdx),N=ks.length;if(!N)return;
  const row=ks.map(a=>ks.reduce((t,b)=>t+(a===b?0:coOf(a,b)),0)),RT=row.reduce((a,b)=>a+b,0)||1;
  const CX=300,CY=300,RR=230,RW=14,PAD=.035,minA=.05,avail=2*Math.PI-PAD*N;
  let sizes=row.map(v=>Math.max(minA,avail*v/RT));const sc=avail/sizes.reduce((a,b)=>a+b,0);sizes=sizes.map(v=>v*sc);
  const st=[];let a=0;ks.forEach((k,i)=>{st.push(a);a+=sizes[i]+PAD});
  const P=(r,t)=>[CX+r*Math.sin(t),CY-r*Math.cos(t)];
  let o='',rib='',ri=0,lastTiny=false;
  ks.forEach((k,i)=>{const a0=st[i],a1=st[i]+sizes[i],[x0,y0]=P(RR+RW,a0),[x1,y1]=P(RR+RW,a1),[x2,y2]=P(RR,a1),[x3,y3]=P(RR,a0),lg=a1-a0>Math.PI?1:0;
    o+=`<path class="cha" data-k="${k}" data-go="${k}" fill="${NAVY}" style="--d:${(.2+i*.05).toFixed(2)}s" d="M${x0.toFixed(1)},${y0.toFixed(1)}A${RR+RW},${RR+RW} 0 ${lg} 1 ${x1.toFixed(1)},${y1.toFixed(1)}L${x2.toFixed(1)},${y2.toFixed(1)}A${RR},${RR} 0 ${lg} 0 ${x3.toFixed(1)},${y3.toFixed(1)}Z"><title>${esc(M[k].l)}: fired alongside another modality ${fmt(row[i])} times</title></path>`;
    const mid=(a0+a1)/2,tiny=(a1-a0)<.12;lastTiny=tiny?!lastTiny:false;const [lx,ly]=P(RR+RW+12+(tiny&&lastTiny?20:0),mid),right=Math.sin(mid)>=0;
    o+=`<text class="chl" data-k="${k}" data-go="${k}" x="${lx.toFixed(1)}" y="${(ly+4).toFixed(1)}" text-anchor="${right?'start':'end'}" style="--d:${(.6+i*.05).toFixed(2)}s">${esc(M[k].l.split(' · ')[0].slice(0,20))}</text>`});
  const pairs=[];ks.forEach((x,i)=>ks.forEach((y,j)=>{if(j>i){const v=coOf(x,y);if(v)pairs.push([i,j,v])}}));
  pairs.sort((p,q)=>q[2]-p[2]);
  const used=ks.map(()=>0);
  pairs.forEach(([i,j,v])=>{const wi=sizes[i]*v/Math.max(1,row[i]),wj=sizes[j]*v/Math.max(1,row[j]);
    const i0=st[i]+used[i],i1=i0+wi,j0=st[j]+used[j],j1=j0+wj;used[i]+=wi;used[j]+=wj;
    const [a0x,a0y]=P(RR,i0),[a1x,a1y]=P(RR,i1),[b0x,b0y]=P(RR,j0),[b1x,b1y]=P(RR,j1);
    rib+=`<path class="chr${ri===0?' top':''}" data-k="${ks[i]}" data-k2="${ks[j]}" data-go="${ks[i]}" fill="${ri===0?RED:NAVY2}" style="--d:${(.7+ri*.02).toFixed(2)}s"
      d="M${a0x.toFixed(1)},${a0y.toFixed(1)}A${RR},${RR} 0 0 1 ${a1x.toFixed(1)},${a1y.toFixed(1)}Q${CX},${CY} ${b0x.toFixed(1)},${b0y.toFixed(1)}A${RR},${RR} 0 0 1 ${b1x.toFixed(1)},${b1y.toFixed(1)}Q${CX},${CY} ${a0x.toFixed(1)},${a0y.toFixed(1)}Z"><title>${esc(M[ks[i]].l)} + ${esc(M[ks[j]].l)}: ${fmt(v)} times together</title></path>`;ri++});
  const top=pairs[0];
  const cap=top?`<text x="${CX}" y="${CY+RR+58}" text-anchor="middle" class="chc"><tspan class="chc n">${fmt(top[2])}×</tspan> <tspan>most often together:</tspan> <tspan class="chc b">${esc(M[ks[top[0]]].l.split(' · ')[0])} + ${esc(M[ks[top[1]]].l.split(' · ')[0])}</tspan></text>`:'';
  $('h-chord').innerHTML=`<svg viewBox="-70 -40 740 700" preserveAspectRatio="xMidYMid meet">${rib}${o}${cap}</svg>`})();

// ---------------------------------------------------------------- replay the day
const evs=[];Object.entries(C).forEach(([cc,c])=>Object.entries(c.m).forEach(([k,ms])=>ms.forEach(m=>evs.push([m,k,cc,c.d]))));
evs.sort((a,b)=>a[0]-b[0]);
const finalG=grid(null);let FMX=1;mods.forEach(k=>finalG[k].forEach(v=>{if(v>FMX)FMX=v}));
const dMax=Math.max(1,...Object.values(dTot));
const rpPlay=$('rp-play'),rpFill=$('rp-fill'),rpKnob=$('rp-knob'),rpT=$('rp-t'),rpTrack=$('rp-track');
rpT.textContent=`${hm(lo)}–${hm(hi)}`;
function frameAt(T){const g={};mods.forEach(k=>g[k]=new Array(NB).fill(0));const cnt={},dc={},fc={};let tot=0;
  for(const [m,k,cc,d] of evs){if(m>T)break;const i=Math.floor((m-lo)/15);if(g[k]&&i>=0&&i<NB)g[k][i]++;
    cnt[cc]=(cnt[cc]||0)+1;if(d){dc[d]=(dc[d]||0)+1;fc[k+'|'+d]=(fc[k+'|'+d]||0)+1}tot++}
  const bi=Math.floor((T-lo)/15);
  cells.forEach(el=>{const k=el.dataset.k,i=+el.dataset.i,v=g[k][i];el.classList.remove('pkc','fm');
    el.style.fill=v?(i===bi?RED:ramp(v/FMX)):'#F4F6F8'});
  hub.classList.remove('f-mod','f-dist');
  const a=ang(Math.max(0,Math.min(NB,(T-lo)/15)))*180/Math.PI;cur.setAttribute('transform',`rotate(${a.toFixed(1)} ${cx} ${cy})`);cur.style.opacity=1;
  ct.textContent=hm(Math.floor(T));cn.textContent=fmt(tot);cs.textContent='alerts so far';
  document.querySelectorAll('#h-flow .fr').forEach(r=>{r.classList.remove('lit','dim');const v=fc[r.dataset.k+'|'+r.dataset.d]||0,full=flows[r.dataset.k][r.dataset.d]||1;r.style.fillOpacity=(.12+.88*v/full).toFixed(2)});
  document.querySelectorAll('#v-summary .dpath').forEach(pth=>{if(pth.dataset.d in dTot){pth.style.transitionDelay='0s';pth.style.fill=ramp((dc[pth.dataset.d]||0)/dMax)}});
  if(!rp||performance.now()-lbAt>520){lbAt=performance.now();board(null,null,cnt)}
  const f=100*(T-lo)/(hi-lo);rpFill.style.width=f+'%';rpKnob.style.left=f+'%';rpT.textContent=hm(Math.floor(T));if(rp){flowTo(T);if(hdrN)hdrN.textContent=fmt(tot)}else emT=null;CV.reel&&CV.reel.follow(T);
  const hb=document.querySelector('#v-summary .htn b');if(hb)hb.textContent=fmt(tot);
  $('h-mapt').textContent=`All alerts by district · ${hm(Math.floor(T))}`}
function rpStop(done){if(!rp)return;cancelAnimationFrame(rp.raf);rpAt=done?null:rp.t;rpDur=rp.dur;rp=null;rpPlay.textContent=done?'↻ Replay again':'▶ Resume';
  hub.classList.remove('replaying');emT=null;if(done)setTimeout(()=>{if(!rp){hdrBack();if(!document.body.classList.contains('touring'))CV.reel&&CV.reel.hide();cur.style.opacity=0;paint();rpT.textContent=`${hm(lo)}–${hm(hi)}`;rpFill.style.width='0';rpKnob.style.left='0'}},1600)}
function rpStart(from,dur){if(rp)return rpStop(false);hub.classList.add('replaying');focus={k:null,d:null};
  const T0=from!=null?from:(rp&&rp.t)||lo,D0=dur||24000,t0=performance.now()-((T0-lo)/(hi-lo))*D0;
  rp={t:T0,dur:D0};rpPlay.textContent='❚❚ Pause';
  (function tick(now){const k=Math.min(1,(now-t0)/D0),T=lo+(hi-lo)*k;rp.t=T;frameAt(T);
    if(k<1)rp.raf=requestAnimationFrame(tick);else rpStop(true)})(performance.now())}
let rpAt=null,rpDur=24000;
rpPlay.addEventListener('click',e=>{e.stopPropagation();if(rp)rpStop(false);else rpStart(rpAt&&rpAt<hi-1?rpAt:lo)});
function scrub(e){const b=rpTrack.getBoundingClientRect(),k=Math.max(0,Math.min(1,(e.clientX-b.left)/b.width));
  if(rp)rpStop(false);rpAt=lo+(hi-lo)*k;hub.classList.add('replaying');frameAt(rpAt);rpPlay.textContent='▶ Resume'}
rpTrack.addEventListener('pointerdown',e=>{scrub(e);rpTrack.setPointerCapture(e.pointerId);
  const mv=ev=>scrub(ev),up=()=>{rpTrack.removeEventListener('pointermove',mv);rpTrack.removeEventListener('pointerup',up)};
  rpTrack.addEventListener('pointermove',mv);rpTrack.addEventListener('pointerup',up)});
// presentation keys on the overview, outside the tour
window.addEventListener('keydown',e=>{const tour=document.getElementById('tour'),lbx=document.getElementById('lb');
  if((tour&&!tour.hidden)||(lbx&&!lbx.hidden))return;
  const v=document.getElementById('v-summary');if(!v.classList.contains('cur'))return;
  if(e.key===' '){e.preventDefault();e.stopImmediatePropagation();if(rp)rpStop(false);else rpStart(rpAt!=null&&rpAt<hi-1?rpAt:lo,rpDur);return}
  if((e.key==='ArrowRight'||e.key==='ArrowLeft')&&(rp||hub.classList.contains('replaying'))){e.preventDefault();e.stopImmediatePropagation();
    const T=(rp?rp.t:rpAt!=null?rpAt:lo)+(e.key==='ArrowRight'?15:-15);if(rp)rpStop(false);
    rpAt=Math.max(lo,Math.min(hi,T));hub.classList.add('replaying');frameAt(rpAt);rpPlay.textContent='▶ Resume'}},true);
hub.addEventListener('mouseenter',()=>{if(!rp&&rpAt!=null&&hub.classList.contains('replaying')){rpAt=null;hub.classList.remove('replaying');cur.style.opacity=0;paint();rpT.textContent=`${hm(lo)}–${hm(hi)}`;rpFill.style.width='0';rpKnob.style.left='0';rpPlay.textContent='▶ Replay the day'}});
CV.hub={focus:(k,d)=>{if(rp)rpStop(false);hdrBack();focus={k:k||null,d:d||null};paint()},replay:(d)=>{rpStop(false);rpStart(lo,d)},
  playing:()=>!!rp,pause:()=>{if(rp)rpStop(false)},resume:()=>{if(!rp&&rpAt!=null)rpStart(rpAt,rpDur)},
  stop:()=>{rpStop(false);hdrBack()},peak:()=>{let b=0,best=0;const tot=new Array(NB).fill(0),byk={};mods.forEach(k=>finalG[k].forEach((v,i)=>{tot[i]+=v}));
    tot.forEach((v,i)=>{if(v>best){best=v;b=i}});let km=mods[0];mods.forEach(k=>{if(finalG[k][b]>finalG[km][b])km=k});
    return {bin:b,n:best,mod:km,at:hm(lo+b*15)}},
  pointAt:(b)=>{const a=(ang(b)+ang(b+1))/2*180/Math.PI;cur.setAttribute('transform',`rotate(${a.toFixed(1)} ${cx} ${cy})`);cur.style.opacity=1},
  dTot,mods};
paint();cn.dataset.n=Object.values(M).reduce((a,m)=>a+m.n,0);CV.count(cn,900);
// redraw the board when the view opens again (its height is only known once visible)
new MutationObserver(()=>{const v=document.getElementById('v-summary');if(v.classList.contains('cur'))board(focus.k,focus.d)})
  .observe(document.getElementById('v-summary'),{attributes:true,attributeFilter:['class']});
})();
"""


JS5 = r"""
(()=>{
const D=CV.D,C=D.centres,M=D.mods,$=id=>document.getElementById(id);
const fmt=n=>(+n).toLocaleString('en-IN');
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const reduce=matchMedia('(prefers-reduced-motion: reduce)').matches;
// ---------------------------------------------------------------- intro
(function intro(){const VE=$('veil');if(reduce||!VE||location.hash)return;
  const ph=VE.querySelectorAll('.vph');const k=Math.floor(Math.random()*ph.length);ph.forEach((p,i)=>p.classList.toggle('sel',i===k));
  VE.querySelector('.vkick').textContent='CamView · live report';VE.querySelector('.vlab').textContent=D.exam||'';
  VE.querySelector('.vcred').textContent=ph[k]?ph[k].dataset.cap:'';VE.classList.add('intro');
  VE.hidden=false;void VE.offsetWidth;VE.classList.add('in');
  setTimeout(()=>{VE.classList.remove('in');VE.classList.add('out');const v=$('v-summary');CV.replay(v);
    setTimeout(()=>{VE.hidden=true;VE.classList.remove('out','intro');setTimeout(()=>{if(!document.body.classList.contains('touring'))CV.tour&&CV.tour()},900)},520)},1900)})();

// ---------------------------------------------------------------- evidence reel
const F=D.frames||[],fcc=[];Object.entries(C).forEach(([cc,c])=>(c.f||[]).forEach(i=>fcc[i]=cc));
const tm=s=>{const a=String(s||'0:0').split(':');return (+a[0])*60+(+a[1]||0)};
const byT=F.map((f,i)=>i).sort((a,b)=>tm(F[a].t)-tm(F[b].t));
const reel=document.createElement('div');reel.id='reel';reel.hidden=true;
reel.innerHTML='<div class="rlh"><span class="rlrec"></span><span id="rl-k">Evidence</span><span id="rl-n"></span></div><div class="rlst" id="rl-st"></div>';
document.body.appendChild(reel);
const RS=$('rl-st');let rq=[],rqi=0,rtimer=null,rpaused=false,rmode='',fp=0,fT=-1,pend=-1,lastShow=0,rlast=-1;
function rlCard(i){const f=F[i],cc=fcc[i],c=C[cc]||{},el=document.createElement('figure');el.className='rlc';
  el.style.setProperty('--r',(Math.random()*6-3).toFixed(1)+'deg');
  el.innerHTML=`<div class="rli"><img src="${f.u}" alt=""><i class="rlfl"></i><span class="rlt">${esc(f.t)}${f.cam?' · '+esc(f.cam):''}</span></div>`+
    `<figcaption><b>${esc((M[f.m]||{}).l||f.m)}</b><span>${esc(c.n||'')}${c.d?' · '+esc(c.d):''}</span></figcaption>`;
  el.addEventListener('click',()=>{if(cc)CV.openCentre(cc,f.m)});return el}
function rlDock(){const v=CV.cur,slot=v&&v.querySelector('.mapslot'),pan=slot&&slot.closest('.panel');
  document.querySelectorAll('.panel.reeled').forEach(q=>{if(q!==pan)q.classList.remove('reeled','rtall')});
  if(!pan){reel.classList.remove('dock');if(reel.parentNode!==document.body)document.body.appendChild(reel);return}
  const b=pan.getBoundingClientRect();pan.classList.add('reeled');pan.classList.toggle('rtall',b.height>b.width*1.15);
  reel.classList.add('dock');if(reel.parentNode!==pan)pan.appendChild(reel)}
function rlPut(i){rlDock();reel.hidden=false;void reel.offsetWidth;reel.classList.add('on');RS.appendChild(rlCard(i));
  const cs=[...RS.children];cs.forEach((c,j)=>{const z=cs.length-1-j;c.style.setProperty('--z',z);if(z>2&&!c.classList.contains('gone')){c.classList.add('gone');setTimeout(()=>c.remove(),800)}})}
function rlStop(){clearInterval(rtimer);rtimer=null}
function rlRun(){rlStop();if(rpaused||rq.length<2)return;rtimer=setInterval(()=>{rlPut(rq[rqi%rq.length]);rqi++},3400)}
function rlCycle(list,label){rlStop();rmode='c';rq=list.slice(0,24);rqi=1;if(!rq.length)return rlHide();
  $('rl-k').textContent=label;$('rl-n').textContent=`${rq.length} frame${rq.length>1?'s':''}`;rlPut(rq[0]);rlRun()}
function rlFollow(T){if(!CV.cur||CV.cur.id!=='v-summary'||rmode==='c')return;if(rmode!=='f'){rlStop();rmode='f';RS.innerHTML='';fp=0;fT=-1;pend=-1;rlast=-1;$('rl-k').textContent='Live';$('rl-n').textContent=''}
  if(T<fT){fp=0;pend=-1}fT=T;
  while(fp<byT.length&&tm(F[byT[fp]].t)<=T){pend=byT[fp];fp++}
  const now=performance.now();if(pend>=0&&pend!==rlast&&now-lastShow>1500){rlast=pend;lastShow=now;rlPut(pend);pend=-1}
  $('rl-n').textContent=fp?`${fp} / ${byT.length}`:''}
function rlHide(){rlStop();rmode='';reel.classList.remove('on');setTimeout(()=>{if(!reel.classList.contains('on')){reel.hidden=true;RS.innerHTML='';document.querySelectorAll('.panel.reeled').forEach(q=>q.classList.remove('reeled','rtall'))}},700)}
const near=(list,at)=>list.sort((a,b)=>Math.abs(tm(F[a].t)-at)-Math.abs(tm(F[b].t)-at));
const ofMod=k=>F.map((f,i)=>i).filter(i=>F[i].m===k);
CV.reel={follow:rlFollow,cycle:rlCycle,hide:rlHide,reset:()=>{rmode='';RS.innerHTML=''},
  pause:()=>{rpaused=true;rlStop();document.body.classList.add('tpaused')},
  resume:()=>{rpaused=false;document.body.classList.remove('tpaused');if(rmode==='c')rlRun()}};

// ---------------------------------------------------------------- tour
const card=document.createElement('div');card.id='tour';card.hidden=true;
card.innerHTML='<div class="tbar"><i id="tour-p"></i></div><div class="tin"><span class="tstep" id="tour-n"></span><p id="tour-t"></p>'+
  '<span class="tkeys"><kbd>Space</kbd> pause · <kbd>←</kbd><kbd>→</kbd> slides · <kbd>Esc</kbd> exit</span>'+
  '<div class="tctl"><button data-tt="-1" title="Back">‹</button><button data-tt="pause" id="tour-pp" title="Pause">❚❚</button><button data-tt="1" title="Next">›</button><button data-tt="x" title="End tour (Esc)">✕</button></div></div>';
document.body.appendChild(card);
function facts(){const ccs=Object.keys(C),mods=Object.keys(M);
  const tot=mods.reduce((a,k)=>a+M[k].n,0);
  const crit=mods.slice().sort((a,b)=>(M[b].c-M[a].c)||(M[b].n-M[a].n))[0];
  const dT={};ccs.forEach(cc=>{const d=C[cc].d;if(d)dT[d]=(dT[d]||0)+C[cc].t});
  const hot=Object.keys(dT).sort((a,b)=>dT[b]-dT[a])[0];
  const nc=cc=>Object.values(C[cc].tr).filter(t=>t==='r').length;
  const worst=ccs.filter(cc=>C[cc].f.length).sort((a,b)=>(nc(b)-nc(a))||(C[b].t-C[a].t))[0]||ccs[0];
  return {tot,crit,hot,hotPct:hot?Math.round(100*dT[hot]/tot):0,worst,wc:nc(worst),ccs:ccs.length,mods:mods.length,
    peak:CV.hub?CV.hub.peak():null}}
let steps=[],si=0,tt=null,paused=false,t0=0,left=0;
function build(){const f=facts(),pk=f.peak,lab=k=>M[k].l;
  steps=[
   {t:`One examination day: <b>${fmt(f.tot)}</b> alerts from <b>${f.mods}</b> AI modalities across <b>${f.ccs}</b> centres. Watch it happen.`,
    go:()=>{CV.show('summary');CV.reel.reset();setTimeout(()=>{if(si===0&&!paused&&!card.hidden)CV.hub&&CV.hub.replay(24000)},1200)},ms:28000},
   pk&&{t:`The busiest moment was <b>${pk.at}</b>: <b>${fmt(pk.n)}</b> alerts in fifteen minutes, most of them <b>${esc(lab(pk.mod))}</b>.`,
    go:()=>{CV.show('summary');CV.hub&&CV.hub.stop();setTimeout(()=>{CV.hub.focus(pk.mod,null);CV.hub.pointAt(pk.bin)},300);
      CV.reel.cycle(near(ofMod(pk.mod),tm(pk.at)),'Around '+pk.at+' · '+lab(pk.mod))},ms:14000},
   {t:`<b>${esc(lab(f.crit))}</b> left <b>${M[f.crit].c}</b> of ${M[f.crit].k} centres critical, more than any other modality.`,
    go:()=>{CV.hub&&CV.hub.focus(null,null);CV.show(f.crit);
      CV.reel.cycle(ofMod(f.crit).sort((a,b)=>((C[fcc[b]]||{tr:{}}).tr[f.crit]==='r')-((C[fcc[a]]||{tr:{}}).tr[f.crit]==='r')),lab(f.crit)+' · critical centres first')},ms:15000},
   f.hot&&{t:`<b>${esc(f.hot)}</b> carried <b>${f.hotPct}%</b> of all alerts.`,go:()=>{CV.openDistrict(f.hot);CV.reel.cycle(byT.filter(i=>(C[fcc[i]]||{}).d===f.hot).sort(()=>Math.random()-.5),'Seen in '+f.hot)},ms:14000},
   {t:`Start with <b>${esc(C[f.worst].n)}</b>: ${f.wc} modalities at critical and ${fmt(C[f.worst].t)} alerts.`,
    go:()=>{CV.lb.close();CV.openCentre(f.worst,null);CV.reel.hide()},ms:13000},
   C[f.worst].f.length&&{t:`What the cameras saw there, in time order.`,go:()=>{CV.reel.hide();CV.lb.open(0);CV.lb.play()},ms:22000},
   {t:`That is the day. Click any ring, ribbon, district or centre to explore it yourself.`,
    go:()=>{CV.reel.hide();CV.lb.close();CV.show('summary')},ms:9000},
  ].filter(Boolean)}
function step(i){clearTimeout(tt);if(i<0)i=0;if(i>=steps.length)return end();si=i;const st=steps[i];
  $('tour-n').textContent=`${i+1} / ${steps.length}`;$('tour-t').innerHTML=st.t;
  card.classList.remove('show');void card.offsetWidth;card.classList.add('show');
  const pb=$('tour-p');pb.style.transition='none';pb.style.width='0';void pb.offsetWidth;
  left=st.ms;t0=performance.now();
  try{st.go()}catch(e){console.error(e)}
  if(paused){setTimeout(()=>{CV.hub&&CV.hub.pause();CV.lb&&CV.lb.stop()},1200);return}
  pb.style.transition=`width ${st.ms}ms linear`;pb.style.width='100%';
  tt=setTimeout(()=>step(si+1),st.ms)}
function start(){build();paused=false;$('tour-pp').textContent='❚❚';card.hidden=false;document.body.classList.add('touring');step(0)}
function end(){clearTimeout(tt);card.hidden=true;document.body.classList.remove('touring');CV.lb&&CV.lb.stop();CV.reel.resume();CV.reel.hide()}
function togglePause(){paused=!paused;$('tour-pp').textContent=paused?'▶':'❚❚';card.classList.toggle('paused',paused);const pb=$('tour-p');
  if(paused){clearTimeout(tt);left=Math.max(800,left-(performance.now()-t0));const w=getComputedStyle(pb).width;pb.style.transition='none';pb.style.width=w;
    CV.hub&&CV.hub.pause();CV.lb&&CV.lb.stop();CV.reel.pause()}
  else{CV.reel.resume();t0=performance.now();void pb.offsetWidth;pb.style.transition=`width ${left}ms linear`;pb.style.width='100%';
    CV.hub&&CV.hub.resume();const lbx=document.getElementById('lb');if(lbx&&!lbx.hidden)CV.lb.play();
    tt=setTimeout(()=>step(si+1),left)}}
CV.tour=()=>start();
document.addEventListener('click',e=>{const b=e.target.closest('[data-tour]');if(b){e.stopPropagation();start();return}
  const t=e.target.closest('[data-tt]');if(!t)return;e.stopPropagation();const a=t.dataset.tt;
  if(a==='x')end();else if(a==='pause')togglePause();else{paused=false;$('tour-pp').textContent='❚❚';step(si+(+a))}},true);
window.addEventListener('keydown',e=>{if(card.hidden)return;
  if(e.key==='Escape'){e.stopImmediatePropagation();CV.lb&&CV.lb.close();end()}
  else if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.stopImmediatePropagation();e.preventDefault();
    if(paused){paused=false;$('tour-pp').textContent='❚❚';card.classList.remove('paused');CV.reel.resume()}step(si+(e.key==='ArrowRight'?1:-1))}
  else if(e.key===' '){e.stopImmediatePropagation();e.preventDefault();togglePause()}},true);
})();
"""


def _veil() -> str:
    """The loading screen between screens: the PDF's own photographs, pre-baked
    as navy duotones (assets/photos/baked), one shown at random per switch, with
    its Commons credit as the licences require."""
    from .iv_paper import _photo_uri, photo_credits
    cr = photo_credits()
    ph = []
    for k in ("cover", "hall", "cameras", "monitoring", "evidence", "invigilation"):
        uri = _photo_uri(k)
        if not uri:
            continue
        c = cr.get(k, {})
        cap = f'Photograph: {c.get("caption", "")} · {c.get("artist", "")}, {c.get("lic", "")}, Wikimedia Commons'
        ph.append(f'<div class="vph" style="background-image:url({uri})" data-cap="{esc(cap)}"></div>')
    return ('<div id="veil" hidden>' + "".join(ph) +
            '<div class="vtxt"><div class="vkick"></div><div class="vlab"></div><div class="vbar"><i></i></div></div>'
            '<div class="vcred"></div><div class="vband"></div></div>')


def _paper_css() -> str:
    """The portal PDF's own stock (iv_paper's baked paper.jpg) under every screen,
    with the PDF's red-then-navy band along the foot."""
    from .iv_paper import _paper_uri
    uri = _paper_uri()
    bg = f'background:#FBFBFC url("{uri}") center/cover no-repeat fixed;' if uri else ""
    return ("body{" + bg + "}"
            ".view{inset:0 0 6px 0!important}"
            ".band{inset:auto 0 0 0!important;height:6px!important}"
            ".panel,.tile{background:rgba(255,255,255,.58)!important;border-color:rgba(30,42,61,.10)!important}"
            ".tile:hover{background:rgba(255,255,255,.85)!important}")


CSS2 = """
#veil{position:fixed;inset:0;z-index:15;background:#1E2A3D;opacity:0;pointer-events:none;overflow:hidden}
#veil[hidden]{display:none}
#veil.in{opacity:1;pointer-events:auto;transition:opacity .22s ease}
#veil.out{opacity:0;transition:opacity .48s ease}
.vph{position:absolute;inset:-2%;background-size:cover;background-position:center;opacity:0}
.vph.sel{opacity:1}
#veil.in .vph.sel{animation:kb2 1.3s cubic-bezier(.2,.7,.2,1) both}
@keyframes kb2{from{transform:scale(1.09)}to{transform:scale(1.01)}}
#veil::after{content:"";position:absolute;inset:0;background:linear-gradient(90deg,rgba(20,28,40,.72) 0%,rgba(20,28,40,.15) 60%,transparent)}
.vtxt{position:absolute;left:5vw;bottom:12vh;z-index:2;color:#fff}
.vkick{font-size:13px;font-weight:600;letter-spacing:.2em;text-transform:uppercase;color:#E8EDF2;opacity:0}
.vlab{font-size:clamp(30px,6vh,64px);font-weight:700;line-height:1.05;margin-top:1vh;max-width:70vw;opacity:0}
#veil.in .vkick{animation:rise .5s cubic-bezier(.2,.8,.2,1) .08s both}
#veil.in .vlab{animation:rise .55s cubic-bezier(.2,.8,.2,1) .14s both}
.vbar{width:min(360px,40vw);height:3px;background:rgba(255,255,255,.22);margin-top:2.4vh;overflow:hidden;border-radius:2px}
.vbar i{display:block;height:100%;width:0;background:var(--red)}
#veil.in .vbar i{animation:vload .78s cubic-bezier(.4,0,.2,1) forwards}
@keyframes vload{to{width:100%}}
.vcred{position:absolute;right:2.4vw;bottom:2.4vh;z-index:2;font-size:11px;color:rgba(255,255,255,.62);max-width:60vw;text-align:right}
.vband{position:absolute;left:0;right:0;bottom:0;height:6px;z-index:2;background:linear-gradient(90deg,var(--red) 0 22%,var(--navy) 22% 100%)}
.phead{display:flex;justify-content:space-between;align-items:center;gap:8px;margin-bottom:.6vh}
.phead .fig{margin:0}
.seg{display:inline-flex;border:1px solid var(--g3);border-radius:999px;padding:2px;background:rgba(255,255,255,.6)}
.seg button{font-size:12px;font-weight:600;color:var(--mut);padding:3px 12px;border-radius:999px;transition:.2s}
.seg button.sel{background:var(--navy);color:#fff}
.seg button:not(.sel):hover{color:var(--navy)}
.vtabs{align-self:flex-start;align-items:center;gap:2px}
.vtabs.big button{font-size:13px;padding:5px 16px}
.vtabs .hint{font-size:12px;color:var(--g1);padding:0 12px 0 14px}
.pane{min-height:0}.pane[hidden]{display:none!important}
.mapcol .pane{flex:1;display:flex;flex-direction:column}
.cgrid{flex:1;display:grid;grid-template-columns:1.7fr 1fr;gap:1vw}
.clockrow{flex:1;min-height:0;display:flex;gap:1.6vw;justify-content:center;align-items:stretch}
.clockrow.v{flex-direction:column;gap:1vh}
.ck{flex:1;min-width:0;min-height:0;display:flex;flex-direction:column;align-items:center}
.ckh{font-size:13px;font-weight:600;display:flex;align-items:center;gap:7px}
.ckh i{width:10px;height:10px;border-radius:2px}
.ckf{flex:1;min-height:0;width:100%;display:flex;justify-content:center}
.ckf svg{height:100%;max-width:100%;overflow:visible}
.ckn{font-size:12px;color:var(--mut)}
.clockrow.v .ck{flex-direction:row;gap:10px}.clockrow.v .ckh{writing-mode:vertical-rl;transform:rotate(180deg)}
.clockrow.v .ckn{max-width:30%}
.cl{stroke-dasharray:1;stroke-dashoffset:1}
.on .cl{animation:draw .7s cubic-bezier(.2,.8,.2,1) calc(.6s + var(--i) * .07s) forwards}
.wedge{transform-box:view-box;transform-origin:150px 150px;opacity:0}
.on .wedge{animation:wedge 1s cubic-bezier(.2,.8,.2,1) .3s forwards}
@keyframes wedge{from{opacity:0;transform:rotate(-30deg) scale(.8)}to{opacity:1;transform:none}}
.cl:hover{stroke-width:12}
.mrings{flex:1;display:grid;grid-template-columns:1fr;gap:1vh;align-content:start;overflow:hidden}
.mr{border:1px solid rgba(30,42,61,.10);border-radius:10px;padding:1vh .9vw;background:rgba(255,255,255,.5);opacity:0}
.on .mr{animation:rise .6s cubic-bezier(.2,.8,.2,1) calc(.5s + var(--i) * .12s) both}
.mr small{font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:uppercase;color:var(--mut);display:flex;align-items:center;gap:6px}
.mr small i{width:8px;height:8px;border-radius:50%}
.mrw{display:flex;align-items:center;gap:12px;margin-top:4px}
.mrw svg{width:clamp(44px,6.4vh,64px);height:clamp(44px,6.4vh,64px);flex:none}
.mrt{fill:none;stroke:#eef0f3;stroke-width:8}
.mra{fill:none;stroke-width:8;stroke-dasharray:0 100}
.on .mra{animation:mra 1.2s cubic-bezier(.45,.05,.3,1) calc(.7s + var(--i) * .12s) forwards}
@keyframes mra{to{stroke-dasharray:var(--p) 100}}
.mrn{font-family:IBMPlexMono,monospace;font-size:16px;font-weight:600;fill:var(--ink)}
.mrw b{font-family:IBMPlexMono,monospace;font-size:clamp(14px,2vh,20px);color:var(--ink)}.mrw b span{font-size:.7em;color:var(--mut);font-weight:400}
.mrw p{font-size:12px;color:var(--mut);line-height:1.3}
.pt,.lol{cursor:pointer}
/* centre view */
.crumbs{display:flex;align-items:center;gap:8px;font-size:13px;margin-bottom:1vh;color:var(--g1)}
.crumbs button{font-weight:600;color:var(--navy);border-bottom:1.5px solid transparent}.crumbs button:hover{border-color:var(--navy)}
.crumbs b{color:var(--ink);font-weight:600}
.ctgrid{flex:1;min-height:0;display:grid;grid-template-columns:1fr 1.35fr .75fr;grid-template-rows:1fr 1fr;gap:1vw}
.ctgrid .a{grid-column:1;grid-row:1}.ctgrid .b{grid-column:2;grid-row:1 / 3}.ctgrid .c{grid-column:1;grid-row:2}
.ctgrid .d{grid-column:3;grid-row:1 / 3}
.sb[data-go]{cursor:pointer}.sb[data-go]:hover .sbn{fill:var(--navy);font-weight:600}
.film{flex:1;min-height:0;display:grid;grid-template-columns:repeat(2,1fr);grid-auto-rows:1fr;gap:.8vw;overflow:hidden}
.fc{position:relative;border-radius:6px;overflow:hidden;cursor:pointer;background:#1E2A3D;opacity:0;min-height:0}
.on .fc{animation:tilein .6s cubic-bezier(.2,.9,.25,1.15) calc(.5s + var(--i) * .09s) both}
.fc img{width:100%;height:100%;object-fit:cover;display:block;transition:transform .5s ease,filter .4s}
.fc:hover img{transform:scale(1.06);filter:brightness(1.08)}
.fc .ft{position:absolute;left:0;right:0;bottom:0;padding:16px 10px 6px;color:#fff;font-size:12px;
  background:linear-gradient(transparent,rgba(20,28,40,.85))}
.fc .ft b{font-family:IBMPlexMono,monospace;font-weight:500}
.fc .fn{position:absolute;top:6px;left:6px;width:22px;height:22px;border-radius:50%;background:rgba(255,255,255,.9);
  color:var(--navy);font:600 11px IBMPlexMono,monospace;display:grid;place-items:center}
.fc .fm{position:absolute;top:6px;right:6px;font-size:11px;font-weight:600;padding:2px 8px;border-radius:999px;color:#fff;background:var(--c)}
.fc::after{content:"▶";position:absolute;inset:0;display:grid;place-items:center;color:#fff;font-size:28px;opacity:0;transition:.25s;
  background:rgba(30,42,61,.25)}.fc:hover::after{opacity:1}
.playall{font-size:12px;font-weight:600;color:#fff;background:var(--navy);padding:4px 12px;border-radius:999px;transition:.2s}
.playall:hover{background:var(--red)}
.ld{opacity:0;transform-box:fill-box;transform-origin:center}
.on .ld{animation:pop .4s cubic-bezier(.3,1.7,.5,1) var(--d) forwards}
.lane{font-size:15px;fill:var(--ink)}.lane.hl{font-weight:700;fill:var(--red)}
.lanebg{fill:var(--g4);fill-opacity:.5}.lanebg.hl{fill:var(--red);fill-opacity:.07}
.stats{display:grid;grid-template-columns:repeat(5,minmax(0,1fr));flex:0 1 60vw;border-top:1.5px solid var(--ink);align-self:flex-end}
.st{padding:1.1vh 1vw 0;border-left:1px solid rgba(30,42,61,.14);min-width:0;opacity:0}
.st:first-child{border-left:0;padding-left:0}
.on .st{animation:rise .6s cubic-bezier(.2,.8,.2,1) calc(.15s + var(--i) * .08s) both}
.stl{font-size:12.5px;font-weight:500;color:var(--mut)}
.stv{margin-top:.4vh;display:flex;align-items:baseline;gap:5px;font-variant-numeric:tabular-nums}
.stv b{font-family:IBMPlexMono,monospace;font-weight:500;font-size:clamp(19px,3vh,30px);color:var(--ink);line-height:1}
.stv b.red{color:var(--red)}.stv small{font-size:12.5px;color:var(--mut)}
.stc{font-family:SourceSerif,serif;font-size:12.5px;color:var(--mut);line-height:1.35;margin-top:.5vh}
.sstrip{width:100%;height:22px;margin-top:.5vh;display:block;overflow:visible}
.ssl{stroke:var(--g3);stroke-width:1}.sst{stroke:var(--g1);stroke-width:1;stroke-opacity:.55}
.ssm{stroke:var(--ink);stroke-width:1;stroke-dasharray:2 2}
.ssd{fill:var(--navy);stroke:#fff;stroke-width:1.5}.ssd.r{fill:var(--red)}
.ssd{transform:translateX(var(--dx));opacity:0}.on .ssd{animation:ride .9s cubic-bezier(.2,.8,.2,1) .6s forwards}
.cells{display:flex;gap:2px;margin:.3vh 0 .2vh}.cells i{flex:1;height:9px;background:var(--g4);border-radius:1px}
.cells i.on{background:var(--navy)}.cells i.r{background:var(--red)}
.on .cells i{animation:fade .3s ease both}
/* summary: dials, side column */
.side{display:grid;grid-template-rows:1fr 1fr;gap:1vw;min-height:0}
.side .panel{min-height:0}
.clockcol .clockrow{gap:.8vw}.clockcol .ckh{font-size:11.5px}.clockcol .ckn{font-size:11px;text-align:center}
.tbody{flex:1;min-height:0;display:flex;align-items:center;gap:.8vw;margin-top:.6vh}
.dial{width:62%;height:auto;max-height:100%;aspect-ratio:1;flex:none;overflow:visible}
.tfig{flex:1;min-width:0;display:flex;flex-direction:column;gap:.4vh}
.tfig .tbar{margin-top:.8vh}
.tkey{border-style:dashed!important;cursor:default;background:rgba(255,255,255,.35)!important}
.tkey:hover{transform:none;box-shadow:none}
.tkey p{font-family:SourceSerif,serif;font-size:clamp(10.5px,1.25vh,12.5px);color:var(--mut);line-height:1.35}
.tkey .dial{width:42%}
.tkey p b{color:var(--ink);font-family:Jost,sans-serif;font-weight:600}
.tcrit{font-size:clamp(11px,1.4vh,14px);color:var(--mut)}.tcrit b{font-family:IBMPlexMono,monospace;font-size:clamp(18px,2.8vh,28px);font-weight:500;color:var(--navy);margin-right:3px}
.tcrit.red b{color:var(--red)}
.dhub{fill:rgba(255,255,255,.7);stroke:var(--g4)}
.dring{fill:none;stroke:var(--g4);stroke-dasharray:1 2.2}
.db{stroke:var(--navy2);stroke-width:2.6;stroke-linecap:round;stroke-dasharray:1;stroke-dashoffset:1}
.tile.hot .db{stroke:var(--navy)}
.db.z{stroke:var(--g3);stroke-width:1.2}
.db.pk{stroke:var(--red);stroke-width:3.4}
.on .db{animation:draw .55s cubic-bezier(.2,.8,.2,1) calc(var(--d) + var(--i) * .06s) forwards}
.dtk{stroke:var(--g1);stroke-width:.8}
.dlab{font-family:IBMPlexMono,monospace;font-size:7px;fill:var(--g1)}
.dnum{font-family:IBMPlexMono,monospace;font-size:13px;font-weight:600;fill:var(--navy)}.dnum.red{fill:var(--red)}
.dcap{font-size:6.5px;fill:var(--mut);letter-spacing:.06em}
.tile:hover .dial{transform:rotate(4deg) scale(1.04);transition:transform .4s cubic-bezier(.2,.8,.2,1)}
.dial{transition:transform .4s cubic-bezier(.2,.8,.2,1)}
.stats{flex:0 1 54vw}
/* the modality rail */
#rail{position:fixed;left:0;top:0;bottom:6px;width:52px;z-index:12;display:flex;flex-direction:column;align-items:center;
  justify-content:center;gap:4px;background:rgba(255,255,255,.55);border-right:1px solid rgba(30,42,61,.10)}
.view{left:52px!important}
#rail button{position:relative;width:38px;height:38px;border-radius:9px;display:grid;place-items:center;transition:background .2s}
#rail button:hover{background:rgba(59,88,119,.10)}
#rail button.sel{background:var(--navy)}
#rail button.sel .ico{stroke:#fff}
#rail .ico{width:20px;height:20px;stroke:var(--navy)}
#rail .ico *{stroke-dashoffset:0!important;animation:none!important;fill:none;stroke-width:1.7;stroke-linecap:round;stroke-linejoin:round}
#rail button.hot::after{content:"";position:absolute;top:6px;right:6px;width:7px;height:7px;border-radius:50%;background:var(--red);
  box-shadow:0 0 0 2px #fff}
#rail .rt{position:absolute;left:48px;top:50%;transform:translate(-6px,-50%);white-space:nowrap;background:var(--ink);color:#D5DAE0;
  font-size:12px;padding:6px 10px;border-radius:6px;opacity:0;pointer-events:none;transition:.15s;text-align:left;line-height:1.35}
#rail .rt b{display:block;color:#fff;font-weight:600;font-size:13px}
#rail button:hover .rt{opacity:1;transform:translate(0,-50%)}
.rsep{width:22px;height:1px;background:var(--g3);margin:4px 0}
.lk{cursor:pointer;text-decoration:underline;text-decoration-color:rgba(182,64,58,.35);text-underline-offset:3px;
  text-decoration-thickness:1.5px;transition:text-decoration-color .2s}
.lk:hover{text-decoration-color:currentColor}
text.lk{text-decoration:none}text.lk:hover{fill:var(--red);font-weight:600}
.fm{cursor:pointer;transition:transform .15s}.fm:hover{transform:scale(1.06);box-shadow:0 0 0 2px #fff}
.cells i[data-go]{cursor:pointer}.cells i[data-go]:hover{outline:1.5px solid var(--ink);outline-offset:1px}
#lbcap .lk{color:#fff;text-decoration-color:rgba(255,255,255,.4)}
@media (max-width:900px){#rail{top:auto;bottom:0;left:0;right:0;width:auto;height:48px;flex-direction:row;overflow-x:auto;justify-content:flex-start;padding:0 8px}
  .view{left:0!important;bottom:48px!important}#rail .rt{display:none}.rsep{width:1px;height:22px}}
/* header statistics: summary and modality */
.stats.sum{grid-template-columns:repeat(3,minmax(0,1fr));flex:0 1 54vw}
.sumbar{margin-top:-.4vh}.sumbar .stl{font-size:12px;color:var(--mut)}
.sumbar .compbar{height:clamp(18px,2.8vh,28px)}
.stats.mods{grid-template-columns:1.3fr 1fr 1fr 1fr;flex:0 1 62vw}
.st.wide{grid-column:1 / -1;border-left:0;padding-left:0;border-top:1px solid rgba(30,42,61,.12);margin-top:.9vh;padding-top:.8vh}
.compbar{width:100%;height:24px;display:block;margin-top:.5vh;overflow:visible}
.compbar.mini{height:16px;margin-top:.6vh}.compbar.mini text{display:none}
.cseg{cursor:pointer}
.cbr{transform-box:fill-box;transform-origin:left;transform:scaleX(0);transition:filter .2s}
.on .cbr{animation:barx .7s cubic-bezier(.2,.8,.2,1) var(--d) forwards}
.cseg:hover .cbr{filter:brightness(1.18)}
.cbc{opacity:0}.on .cbc{animation:fade .4s ease calc(var(--d) + .6s) forwards}
.cbw{position:relative}.cblabs{position:relative;height:30px}
.cbl{position:absolute;top:2px;padding-left:4px;font-size:12px;font-weight:600;color:var(--ink);cursor:pointer;white-space:nowrap;line-height:1.25}
.cbl i{display:block;font-style:normal;font-family:IBMPlexMono,monospace;font-size:10.5px;font-weight:400;color:var(--g1)}
.cbl:hover{color:var(--red)}
.cbl{opacity:0}.on .cbl{animation:fade .4s ease .9s forwards}
.units{width:100%;height:auto;max-height:26px;display:block;margin-top:.6vh}
.units rect{opacity:0}.on .units rect{animation:fade .25s ease var(--d) forwards}
.ur{fill:var(--red)}.un{fill:var(--navy)}.ug{fill:var(--g3)}
.wbar{fill:var(--navy2)}.wpk{stroke:var(--red);stroke-width:2.2}
.stv b.txt{font-size:clamp(15px,2.3vh,22px)}
/* district screen */
.dtgrid{flex:1;min-height:0;display:grid;grid-template-columns:1.15fr 1fr 1fr;grid-template-rows:1fr 1fr;gap:1vw}
.dtgrid .a{grid-column:1;grid-row:1 / 3}.dtgrid .b{grid-column:2;grid-row:1}.dtgrid .c{grid-column:2;grid-row:2}
.dtgrid .m{grid-column:3;grid-row:1 / 3}
.dial.big{width:auto;height:100%;max-width:100%;margin:auto}
.stats.dstats{grid-template-columns:repeat(4,minmax(0,1fr));flex:0 1 58vw}
.dstats .stv b.txt.lk{font-family:Jost,sans-serif;font-weight:600;font-size:clamp(14px,2vh,19px);line-height:1.2}
.sb[data-c]{cursor:pointer}.sb[data-c]:hover .sbn{fill:var(--red);font-weight:600}
.dpath{cursor:pointer}
[data-dist]{cursor:pointer}
@media (max-width:900px){.dtgrid{grid-template-columns:1fr;grid-template-rows:auto}.dtgrid>.panel{grid-row:auto!important;grid-column:auto!important;min-height:300px}}
/* the overview command board */
.hub{flex:1;min-height:0;display:grid;grid-template-columns:1.08fr 1.02fr .9fr;gap:1vw}
.hub .panel{min-height:0}
.hub .seg button{white-space:nowrap}.hub .phead .fig{line-height:1.3}
.hcol{display:grid;grid-template-rows:.9fr 1.1fr;gap:1vw;min-height:0}
.hr .pane{flex:1;display:flex;flex-direction:column;min-height:0}
#h-radial svg,#h-flow svg{width:100%;height:100%;display:block;overflow:visible}
.hc{transition:fill .45s ease,opacity .35s ease;cursor:pointer;opacity:0;transform-box:fill-box;transform-origin:center}
.on .hc{animation:hcin .5s cubic-bezier(.2,.8,.2,1) var(--d) forwards}
@keyframes hcin{from{opacity:0;transform:scale(.6)}to{opacity:1;transform:none}}
.hub.f-mod .hc:not(.fm),.hub.f-mod .hrl:not(.fm){opacity:.16!important}
.hc.pkc{stroke:#fff;stroke-width:1.4}
.on .hc.pkc{animation:hcin .5s cubic-bezier(.2,.8,.2,1) var(--d) forwards,pkpulse 2.2s ease-in-out calc(var(--d) + .8s) infinite}
@keyframes pkpulse{50%{filter:drop-shadow(0 0 6px rgba(182,64,58,.85))}}
.htk{font-family:IBMPlexMono,monospace;font-size:12px;fill:var(--g1)}
.htl{stroke:var(--g3);stroke-width:1}
.hrl{font-size:11px;font-weight:600;fill:var(--mut);transition:opacity .3s}
.hcen{fill:rgba(255,255,255,.92);stroke:var(--g4)}
.hcn{font-family:IBMPlexMono,monospace;font-size:34px;font-weight:600;fill:var(--navy)}
.hcs{font-size:13px;fill:var(--mut)}.hct{font-size:14px;font-weight:700;fill:var(--ink)}
.hcur{stroke:var(--red);stroke-width:2;opacity:0;transition:opacity .2s;pointer-events:none}
.sweep{transform-box:view-box;transform-origin:300px 300px;opacity:0;pointer-events:none}
.on .sweep{animation:fade 1s ease 2.4s forwards,spin 9s linear 2.4s infinite}
@keyframes spin{to{transform:rotate(360deg)}}
.hub.f-mod .sweep,.hub.f-dist .sweep{visibility:hidden}
/* flow */
.fr{transition:opacity .35s ease;opacity:0;cursor:pointer}
.on .fr{animation:frin .9s cubic-bezier(.2,.8,.2,1) var(--d) forwards}
@keyframes frin{from{opacity:0;transform:translateX(-14px)}to{opacity:.42;transform:none}}
.fr.lit{opacity:.85!important}.fr.dim{opacity:.05!important}
.fflow{fill:none;stroke:#fff;stroke-opacity:.55;stroke-width:1.4;stroke-dasharray:2 14;pointer-events:none;opacity:0}
.on .fflow{animation:fade .6s ease 1.8s forwards,flowmove 2.4s linear 1.8s infinite}
@keyframes flowmove{to{stroke-dashoffset:-32}}
.hub.f-mod .fflow:not(.lit),.hub.f-dist .fflow:not(.lit){visibility:hidden}
.fn{cursor:pointer;transform-box:fill-box;transform-origin:center;transform:scaleY(0);transition:opacity .3s}
.on .fn{animation:fnin .6s cubic-bezier(.2,.8,.2,1) var(--d) forwards}
@keyframes fnin{to{transform:none}}
.fn.dim,.flab.dim{opacity:.25}
.flab{font-size:16px;fill:var(--ink);cursor:pointer;transition:opacity .3s}.flab .fv{font-family:IBMPlexMono,monospace;font-size:13px;fill:var(--g1)}
.flab:hover,.flab.lit{fill:var(--red);font-weight:600}
.flab{opacity:0}.on .flab{animation:fade .5s ease var(--d) forwards}
/* leaderboard */
.lb{flex:1;min-height:0;position:relative;overflow:hidden}
.lbk{font-size:11px;color:var(--g1)}
.lr{position:absolute;left:0;right:0;height:var(--rh);display:grid;grid-template-columns:22px 1fr auto 44px;align-items:center;gap:8px;
  padding:0 4px;border-bottom:1px solid rgba(30,42,61,.07);cursor:pointer;
  transition:transform .55s cubic-bezier(.2,.8,.2,1),opacity .4s ease,background .2s}
.lr:hover{background:rgba(59,88,119,.07)}
.lrn{font-family:IBMPlexMono,monospace;font-size:11px;color:var(--g1);text-align:right}
.lrm{min-width:0;display:flex;flex-direction:column;justify-content:center;line-height:1.15}.lrname{font-size:12.5px;font-weight:600;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;display:block}
.lrd{font-size:10.5px;color:var(--mut);display:block}
.lrc{display:flex;gap:2px}.lrc i{width:7px;height:12px;border-radius:1px;background:var(--g4)}
.lrc i.on{background:var(--navy2)}.lrc i.r{background:var(--red)}.lrc i.fm{outline:1.5px solid var(--ink);outline-offset:1px}
.lrv{font-family:IBMPlexMono,monospace;font-size:13px;font-weight:600;color:var(--navy);text-align:right}
@media (max-width:900px){.hub{grid-template-columns:1fr}.hub>.panel,.hcol>.panel{min-height:380px}}
/* the overview header: figures that draw themselves */
.summary .top{align-items:stretch}
.hstats{display:grid;grid-template-columns:1.15fr 1fr 1.05fr;gap:0;flex:0 1 60vw;border-top:1.5px solid var(--ink)}
.ht{padding:1vh 1.2vw .4vh;border-left:1px solid rgba(30,42,61,.14);min-width:0;opacity:0;display:flex;flex-direction:column;gap:.3vh}
.ht:first-child{border-left:0;padding-left:0}
.on .ht{animation:rise .6s cubic-bezier(.2,.8,.2,1) calc(.15s + var(--i) * .1s) both}
.htl2{font-size:12.5px;font-weight:500;color:var(--mut)}
.htr{display:flex;align-items:center;gap:1vw;min-height:44px}
.htn b{font-family:IBMPlexMono,monospace;font-weight:500;font-size:clamp(24px,4vh,40px);color:var(--ink);line-height:1;font-variant-numeric:tabular-nums}
.htn b.red{color:var(--red)}
.htc{font-family:SourceSerif,serif;font-size:13px;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.htc b{font-family:IBMPlexMono,monospace;font-weight:600;color:var(--ink)}
.hsp{flex:1;min-width:80px;height:44px;overflow:visible}
.hspa{fill:var(--navy);fill-opacity:.1;opacity:0}.on .hspa{animation:fade .8s ease 1.4s forwards}
.hspl{fill:none;stroke:var(--navy);stroke-width:1.8;stroke-dasharray:1;stroke-dashoffset:1}
.on .hspl{animation:draw 1.6s cubic-bezier(.45,.05,.3,1) .4s forwards}
.hspd{fill:var(--red);stroke:#fff;stroke-width:1.5;opacity:0;transform-box:fill-box;transform-origin:center}
.on .hspd{animation:pop .5s cubic-bezier(.3,1.7,.5,1) 1.9s forwards,pkpulse 2.2s ease-in-out 2.6s infinite}
.hdb{flex:1;min-width:80px;height:30px}
.hds{cursor:pointer}.hds rect{transform-box:fill-box;transform-origin:left;transform:scaleX(0);transition:filter .2s}
.on .hds rect{animation:barx .7s cubic-bezier(.2,.8,.2,1) var(--d) forwards}
.hds:hover rect{filter:brightness(1.2)}
.hrg{width:44px;height:44px;flex:none}
.hrgt{fill:none;stroke:#eef0f3;stroke-width:6}
.hrga{fill:none;stroke:var(--red);stroke-width:6;stroke-dasharray:0 100}
.on .hrga{animation:mra 1.3s cubic-bezier(.45,.05,.3,1) .7s forwards}
.hrgn{font-family:IBMPlexMono,monospace;font-size:10px;font-weight:600;fill:var(--ink)}
.summary .lead{white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
/* overview: tour button, replay strip, chord */
.tourbtn{margin-top:1vh;display:inline-flex;align-items:center;gap:8px;font-size:13px;font-weight:600;color:#fff;background:var(--ink);
  padding:7px 16px 7px 12px;border-radius:999px;box-shadow:0 6px 18px -8px rgba(30,42,61,.6);transition:transform .2s,background .2s}
.tourbtn:hover{background:var(--red);transform:translateY(-1px)}
.tdot{width:9px;height:9px;border-radius:50%;background:var(--red);box-shadow:0 0 0 0 rgba(182,64,58,.7);animation:tdot 1.8s ease-out infinite}
.tourbtn:hover .tdot{background:#fff}
@keyframes tdot{0%{box-shadow:0 0 0 0 rgba(182,64,58,.7)}100%{box-shadow:0 0 0 10px rgba(182,64,58,0)}}
.leadrow{display:flex;align-items:center;gap:2vw}
.leadrow .lead{flex:1;min-width:0}
.replay{flex:0 0 34vw;display:flex;align-items:center;gap:10px}
.rpb{font-size:12.5px;font-weight:600;color:var(--navy);border:1.5px solid var(--navy);border-radius:999px;padding:4px 14px;white-space:nowrap;transition:.2s}
.rpb:hover,.replaying .rpb{background:var(--navy);color:#fff}
.rptrack{flex:1;height:22px;position:relative;cursor:pointer;touch-action:none}
.rptrack::before{content:"";position:absolute;left:0;right:0;top:10px;height:3px;border-radius:2px;background:var(--g3)}
.rpfill{position:absolute;left:0;top:10px;height:3px;border-radius:2px;background:var(--red);width:0}
.rpknob{position:absolute;top:5px;left:0;width:13px;height:13px;margin-left:-6.5px;border-radius:50%;background:#fff;border:2.5px solid var(--red);
  box-shadow:0 2px 6px rgba(30,42,61,.3)}
.rpt{font-family:IBMPlexMono,monospace;font-size:13px;font-weight:600;color:var(--ink);min-width:92px;text-align:right}
.hub.replaying .sweep{visibility:hidden}
.hub.replaying .hc{transition:fill .12s linear}
.hub.replaying .hcur{opacity:1}
.hf .pane{flex:1;display:flex;flex-direction:column;min-height:0}
#h-chord svg{width:100%;height:100%;display:block;overflow:visible}
.cha{cursor:pointer;opacity:0;transform-box:view-box;transform-origin:300px 300px;transition:opacity .3s}
.on .cha{animation:chin .7s cubic-bezier(.2,.8,.2,1) var(--d) forwards}
@keyframes chin{from{opacity:0;transform:rotate(-12deg) scale(.92)}to{opacity:1;transform:none}}
.chr.top{fill-opacity:.7}.chr{fill-opacity:.38;cursor:pointer;opacity:0;transition:fill-opacity .3s,opacity .3s}
.on .chr{animation:fade .8s ease var(--d) forwards}
.chr:hover,.chr.lit{fill-opacity:.85}.chr.dim{fill-opacity:.05}
.cha.dim,.chl.dim{opacity:.25!important}
.chl{font-size:15px;fill:var(--ink);cursor:pointer;opacity:0}.on .chl{animation:fade .5s ease var(--d) forwards}
.chl:hover{fill:var(--red);font-weight:600}
.chc{font-size:13px;fill:var(--mut);letter-spacing:.04em}.chc.b{font-size:17px;font-weight:700;fill:var(--ink)}
.chc.n{font-family:IBMPlexMono,monospace;font-size:20px;font-weight:600;fill:var(--red)}
/* tour card */
#tour{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);z-index:30;width:min(760px,86vw);background:var(--ink);color:#E8EDF2;
  border-radius:12px;box-shadow:0 20px 50px -18px rgba(10,16,26,.7);overflow:hidden}
#tour[hidden]{display:none}
#tour.show .tin{animation:rise .45s cubic-bezier(.2,.8,.2,1) both}
.tbar{height:3px;background:rgba(255,255,255,.12)}.tbar i{display:block;height:100%;width:0;background:var(--red)}
.tin{display:flex;align-items:center;gap:16px;padding:14px 16px 14px 20px}
.tstep{font-family:IBMPlexMono,monospace;font-size:12px;color:#8A97A6;white-space:nowrap}
#tour-t{flex:1;font-family:SourceSerif,serif;font-size:17px;line-height:1.4;margin:0}
#tour-t b{font-family:Jost,sans-serif;font-weight:700;color:#fff}
.tctl{display:flex;gap:6px}
.tctl button{width:34px;height:34px;border-radius:50%;color:#fff;background:rgba(255,255,255,.08);font-size:16px;transition:.2s}
.tctl button:hover{background:rgba(255,255,255,.22)}
body.touring #lb .lbbar{padding-bottom:84px}
#veil.intro .vlab{font-size:clamp(40px,8vh,88px)}
#veil.intro .vbar i{animation-duration:1.8s!important}
.tin{flex-wrap:wrap;row-gap:6px}
.tkeys{order:9;flex-basis:100%;font-size:11px;color:#8A97A6;white-space:nowrap;padding-left:52px}
.tkeys kbd{font-family:IBMPlexMono,monospace;font-size:10.5px;color:#D5DAE0;border:1px solid rgba(255,255,255,.25);border-radius:4px;padding:1px 5px;margin:0 2px}
#tour.paused .tbar i{background:#8A97A6}
#tour.paused #tour-n::after{content:" · paused";color:#E3B6B3}
/* alerts in flight */
.fpart{pointer-events:none}
.fp{fill:#fff;stroke:var(--navy);stroke-width:.9;filter:drop-shadow(0 0 2.5px rgba(255,255,255,.95))}
.fp.c{fill:var(--red);stroke:#fff;stroke-width:1.1;filter:drop-shadow(0 0 3px rgba(182,64,58,.8))}
.fn.hit{animation:fnhit .45s ease-out}
@keyframes fnhit{0%{filter:brightness(1.9) drop-shadow(0 0 7px rgba(182,64,58,.9))}100%{filter:none}}
.ripple{fill:none;stroke:var(--red);stroke-width:1.6;vector-effect:non-scaling-stroke;transform-box:fill-box;transform-origin:center;
  animation:rlrip 1.4s cubic-bezier(.2,.7,.3,1) forwards;pointer-events:none}
@keyframes rlrip{from{transform:scale(.12);opacity:.95}to{transform:scale(1.5);opacity:0}}
/* evidence reel */
#reel{position:fixed;right:26px;bottom:26px;z-index:29;width:min(310px,20vw);opacity:0;transform:translateY(16px);
  transition:opacity .7s ease,transform .7s cubic-bezier(.2,.8,.2,1)}
#reel.on{opacity:1;transform:none}#reel[hidden]{display:none}
.rlh{display:flex;align-items:center;gap:8px;font:600 11px Jost,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:var(--ink);
  margin:0 0 12px auto;background:rgba(255,255,255,.92);padding:6px 10px;border-radius:6px;width:max-content;max-width:100%;
  box-shadow:0 4px 14px -6px rgba(16,24,36,.3)}
#rl-k{white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:13vw}
#rl-n{font-family:IBMPlexMono,monospace;color:var(--mut);letter-spacing:0;text-transform:none;font-weight:500;white-space:nowrap}
.rlrec{flex:none;width:8px;height:8px;border-radius:50%;background:var(--red);animation:rlrec 1.4s ease-in-out infinite}
@keyframes rlrec{50%{opacity:.2}}
.rlst{position:relative;aspect-ratio:4/3.7}
.rlc{position:absolute;inset:0;margin:0;background:#fff;padding:7px 7px 0;border-radius:3px;cursor:pointer;
  box-shadow:0 22px 44px -18px rgba(16,24,36,.6),0 2px 6px rgba(16,24,36,.14);
  transform:translate(calc(var(--z,0) * var(--ox,-16px)),calc(var(--z,0) * var(--oy,-12px))) rotate(calc(var(--r) + var(--z,0) * -3deg)) scale(calc(1 - var(--z,0) * .05));
  filter:brightness(calc(1 - var(--z,0) * .1)) saturate(calc(1 - var(--z,0) * .3));
  transition:transform 1.1s cubic-bezier(.2,.8,.2,1),filter 1.1s ease,opacity .8s ease;animation:rlin 1.2s cubic-bezier(.2,.8,.2,1) backwards}
@keyframes rlin{from{transform:translate(90px,40px) rotate(14deg) scale(1.1);opacity:0}}
.rlc.gone{opacity:0}
.rli{position:relative;overflow:hidden;aspect-ratio:4/3;background:#1E2A3D}
.rli img{width:100%;height:100%;object-fit:cover;display:block;animation:rlkb 14s linear both}
@keyframes rlkb{from{transform:scale(1.03)}to{transform:scale(1.2) translate(-3%,-2%)}}
.rlfl{position:absolute;inset:0;background:#fff;opacity:0;animation:rlfl .8s ease-out .3s both;pointer-events:none}
@keyframes rlfl{0%{opacity:0}12%{opacity:.9}100%{opacity:0}}
.rlt{position:absolute;left:8px;bottom:8px;font:500 11px IBMPlexMono,monospace;color:#fff;background:rgba(16,22,32,.62);padding:2px 6px;border-radius:3px}
.rlc figcaption{padding:7px 3px 9px;display:flex;flex-direction:column;gap:1px;min-width:0}
.rlc figcaption b{font:700 13px Jost,sans-serif;color:var(--red);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rlc figcaption span{font:13px SourceSerif,serif;color:var(--mut);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.rlc:hover{transform:translateY(-4px) rotate(0deg) scale(1.02)}
body.tpaused .rli img,body.tpaused .rlrec,body.tpaused .rlc{animation-play-state:paused}
@media (max-width:900px){#reel{display:none}}
/* the reel, docked inside the map panel */
.panel.reeled{position:relative;overflow:hidden}
.panel.reeled:not(.rtall) .mapslot{margin-right:47%}
.panel.reeled.rtall .mapslot{flex:0 0 38%}
.panel.reeled .dleg,.panel.reeled .cap{display:none}
#reel.dock{position:absolute;z-index:3;right:1vw;bottom:1.4vh;width:45%;height:calc(100% - 5.6vh);display:flex;flex-direction:column;transform:none}
#reel.dock:not(.on){opacity:0}
.panel.rtall #reel.dock{left:1vw;width:auto;height:58%}
#reel.dock .rlh{margin:0 0 10px auto;box-shadow:none;background:transparent;padding:0}
#reel.dock .rlst{flex:1;min-height:0;aspect-ratio:auto;--ox:-7px;--oy:-6px;margin:8px 0 0 10px}
#reel.dock .rlc{display:flex;flex-direction:column}
#reel.dock .rli{flex:1;min-height:0;aspect-ratio:auto}
.lr{background:var(--panel)}.lr:hover{background:#F3F5F8}
/* modality: capsule bars */
.bars{display:flex;flex-direction:column;justify-content:space-evenly;height:100%;overflow:hidden}
.mgrid .panel{overflow:hidden}
.br{display:grid;grid-template-columns:20px minmax(0,1.15fr) minmax(0,1fr) 66px;align-items:center;gap:10px;cursor:pointer;padding:2px 4px;border-radius:6px;
  opacity:0;transition:background .2s}
.on .br{animation:rise .55s cubic-bezier(.2,.8,.2,1) var(--d) both}
.br:hover{background:#F3F5F8}
.brk{font:500 12px IBMPlexMono,monospace;color:var(--g1);text-align:right}
.brn{min-width:0;display:flex;align-items:baseline;gap:6px;line-height:1.2;white-space:nowrap;overflow:hidden}
.brn b{font:600 13.5px Jost,sans-serif;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis;min-width:0}
.brn small{flex:none;font:12px SourceSerif,serif;color:var(--g1)}
.brb{height:12px;border-radius:6px;background:#EEF1F4;overflow:hidden}
.brb i{display:block;height:100%;width:var(--w);border-radius:6px;background:linear-gradient(90deg,color-mix(in srgb,var(--c) 55%,#fff),var(--c));
  transform:scaleX(0);transform-origin:left}
.on .brb i{animation:barx .9s cubic-bezier(.2,.8,.2,1) calc(var(--d) + .15s) forwards}
.brv{font:600 14px IBMPlexMono,monospace;color:var(--c);text-align:right;white-space:nowrap}
.brv small{font:500 10.5px Jost,sans-serif;color:var(--g1);margin-left:3px}
.br.tg .brv{color:var(--ink)}
/* modality: one hexagon per centre */
.hexes .hx{stroke:#fff;stroke-width:1.5;cursor:pointer;opacity:0;transform-box:fill-box;transform-origin:center;transition:filter .2s}
.on .hexes .hx{animation:hxin .6s cubic-bezier(.3,1.5,.5,1) var(--d) forwards}
@keyframes hxin{from{opacity:0;transform:scale(.2)}to{opacity:1;transform:scale(1)}}
.hexes .hx:hover{filter:brightness(1.2) drop-shadow(0 2px 4px rgba(16,24,36,.35))}
.hexes .hx.sil{fill:none;stroke:var(--g3);stroke-width:1.2;cursor:default}
.hexes .hx.tr{filter:drop-shadow(0 1px 2px rgba(182,64,58,.35))}
.legend .sil::before{background:transparent!important;border:1.2px solid var(--g3)}
/* modality: the day as dots */
.dots .dd{fill:var(--navy);opacity:0;transform-box:fill-box;transform-origin:center}
.dots .dd.pk{fill:var(--red)}
.on .dots .dd{animation:ddin .45s cubic-bezier(.3,1.4,.5,1) var(--d) forwards}
@keyframes ddin{from{opacity:0;transform:translateY(-26px) scale(.4)}to{opacity:1;transform:none}}
.dots .dgrid{stroke:var(--g4);stroke-width:1}
.dots .dbase{stroke:var(--g3);stroke-width:1.2}
.dots .dhit{fill:transparent}.dots .dhit:hover{fill:rgba(59,88,119,.07)}
.dots .dpk{font:600 22px Jost,sans-serif;fill:var(--red);opacity:0}
.dots .tick.sm{font-size:19px}
.on .dots .dpk{animation:fade .6s ease 1.6s forwards}
.dots .dkey circle{fill:var(--navy)}.dots .dkey text{font:19px SourceSerif,serif;fill:var(--mut)}
/* modality: severity tiles + camera locations */
.tiers{flex:1;min-height:0;display:flex;flex-direction:column;gap:1vh;margin-top:.6vh}
.tts{display:grid;grid-template-columns:repeat(4,1fr);gap:.6vw}
.tt{border-radius:8px;background:#F6F7F9;padding:1vh .7vw .9vh;display:flex;flex-direction:column;gap:2px;position:relative;overflow:hidden;opacity:0}
.on .tt{animation:rise .55s cubic-bezier(.2,.8,.2,1) var(--d) both}
.tt b{font:600 clamp(20px,3.4vh,32px) IBMPlexMono,monospace;color:var(--c);line-height:1}
.tt.z b{color:var(--g3)}
.tt span{font:600 11px Jost,sans-serif;letter-spacing:.07em;text-transform:uppercase;color:var(--mut)}
.tt i{position:absolute;left:0;bottom:0;height:4px;width:var(--w);background:var(--c);transform:scaleX(0);transform-origin:left}
.on .tt i{animation:barx .8s ease calc(var(--d) + .3s) forwards}
.slh{font:600 11px Jost,sans-serif;letter-spacing:.08em;text-transform:uppercase;color:var(--g1);margin-top:.4vh}
.sls{display:flex;flex-direction:column;gap:.8vh}
.sl{display:grid;grid-template-columns:minmax(0,.9fr) minmax(0,1.3fr) 44px;align-items:center;gap:10px;opacity:0}
.on .sl{animation:fade .5s ease var(--d) forwards}
.sl span{font:13px SourceSerif,serif;color:var(--ink);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.sl i{height:10px;border-radius:5px;background:linear-gradient(90deg,var(--c,var(--navy)) var(--w),#EEF1F4 var(--w))}
.sl b{font:600 13px IBMPlexMono,monospace;color:var(--ink);text-align:right}
.rlc:not(:last-child) figcaption,.rlc:not(:last-child) .rlt{opacity:0;transition:opacity .5s ease}
.mgrid .b .dleg{margin-bottom:40px}
/* modality: districts under the map */
.dleg{display:flex;flex-direction:column;gap:.7vh;margin-top:.8vh}
.dl{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.2fr) 52px;align-items:center;gap:10px;cursor:pointer;opacity:0}
.on .dl{animation:fade .5s ease var(--d) forwards}
.dl span{font:600 13px Jost,sans-serif;color:var(--ink)}
.dl:hover span{color:var(--red)}
.dl i{height:8px;border-radius:4px;background:linear-gradient(90deg,var(--navy) var(--w),#EEF1F4 var(--w))}
.dl b{font:600 13px IBMPlexMono,monospace;color:var(--ink);text-align:right}
/* lightbox */
#lb{position:fixed;inset:0;z-index:20;background:rgba(16,22,32,.96);display:grid;place-items:center;animation:fade .25s ease}
#lb[hidden]{display:none}
.lbin{width:min(1200px,94vw);height:92vh;display:flex;flex-direction:column;gap:1.2vh;color:#fff}
.lbtop{display:flex;justify-content:space-between;align-items:center;font-size:15px}
.lbtop b{font-weight:600}.lbtop span{color:#B8C0CA}
.lbtop button,.lbarrow{color:#fff;font-size:22px;width:44px;height:44px;border-radius:50%;background:rgba(255,255,255,.08);transition:.2s;flex:none}
.lbtop button:hover,.lbarrow:hover{background:rgba(255,255,255,.22)}
.lbarrow{font-size:32px}
.lbstage{flex:1;min-height:0;display:flex;align-items:center;gap:1.2vw}
figure{flex:1;height:100%;min-width:0;display:flex;flex-direction:column;gap:1vh;margin:0}
.lbimgw{flex:1;min-height:0;position:relative;overflow:hidden;border-radius:8px;background:#0c1018}
.lbimgw img{position:absolute;inset:0;width:100%;height:100%;object-fit:contain;transition:opacity .6s ease}
.lbimgw img.kb{animation:kb 6s ease-out forwards}
@keyframes kb{from{transform:scale(1)}to{transform:scale(1.07)}}
figcaption{display:flex;gap:2vw;flex-wrap:wrap;font-size:14px;color:#D5DAE0}
figcaption b{color:#fff;font-weight:600}figcaption .m{font-family:IBMPlexMono,monospace}
.lbbar{display:flex;align-items:center;gap:16px;font-size:13px;color:#B8C0CA}
#lbplay{color:#fff;background:var(--red);padding:6px 16px;border-radius:999px;font-weight:600}
.lbdots{display:flex;gap:6px;flex-wrap:wrap}
.lbdots button{width:10px;height:10px;border-radius:50%;background:rgba(255,255,255,.3);transition:.2s}
.lbdots button.sel{background:#fff;transform:scale(1.3)}
.lbhint{margin-left:auto;color:#8A97A6;font-size:12px}
.lbprog{height:3px;background:rgba(255,255,255,.15);border-radius:2px;overflow:hidden}
.lbprog i{display:block;height:100%;background:var(--red);width:0}
@media (max-width:900px),(max-height:520px){.cgrid,.ctgrid{grid-template-columns:1fr;grid-template-rows:auto}
  .ctgrid>.panel{grid-row:auto!important;grid-column:auto!important;min-height:300px}.film{grid-template-columns:repeat(2,1fr);grid-auto-rows:150px}}
"""

JS2 = r"""
(()=>{
const D=CV.D,C=D.centres,F=D.frames,M=D.mods;
const corder=Object.keys(C).sort((a,b)=>C[b].t-C[a].t);
const TC={r:'#B6403A',o:'#3B5877',y:'#7189A4',g:'#B8C0CA'},TN={r:'Critical',o:'High',y:'Elevated',g:'Normal'};
const RANK={r:3,o:2,y:1,g:0};
const V=document.getElementById('v-centre');
const $=id=>document.getElementById(id);
const esc=s=>String(s==null?'':s).replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]));
const fmt=n=>(+n).toLocaleString('en-IN');
const hm=m=>String(Math.floor(m/60)).padStart(2,'0')+':'+String(m%60).padStart(2,'0');
let from=null;

function ring(c,n,col,t,x,i){const p=n?100*c/n:0;
  return `<div class="mr" style="--i:${i}"><small><i style="background:${col}"></i>${esc(t)}</small><div class="mrw">
  <svg viewBox="0 0 64 64"><circle cx="32" cy="32" r="24" class="mrt"/><circle cx="32" cy="32" r="24" class="mra" stroke="${col}"
  pathLength="100" style="--p:${p.toFixed(1)}" transform="rotate(-90 32 32)"/><text x="32" y="38" text-anchor="middle" class="mrn">${c>=1000?(c/1000).toFixed(1).replace('.0','')+'k':c}</text></svg>
  <div><b>${fmt(c)} <span>of ${fmt(n)}</span></b><p>${esc(x)}</p></div></div></div>`}

function bars(c){const ks=Object.keys(c.m).sort((a,b)=>c.m[b].length-c.m[a].length);
  const mx=Math.max(1,...ks.map(k=>c.m[k].length)),W=420,rh=34;
  return `<svg viewBox="0 0 ${W} ${rh*ks.length+4}" preserveAspectRatio="xMidYMin meet" style="width:100%;max-height:100%">`+
   ks.map((k,i)=>{const n=c.m[k].length,t=c.tr[k]||'g',w=(W-70)*n/mx,y=i*rh,hl=k===from;
    return `<g class="sb" data-go="${esc(k)}" style="--d:${(.55+i*.08).toFixed(2)}s"><title>Open ${esc(M[k].l)}</title>
    <text x="0" y="${y+13}" class="sbn"${hl?' style="font-weight:700;fill:#B6403A"':''}>${esc(M[k].l)} · ${TN[t]}</text>
    <rect class="sbt" x="0" y="${y+19}" width="${W-70}" height="9" rx="4.5"/>
    <rect class="sbr" x="0" y="${y+19}" width="${Math.max(4,w).toFixed(1)}" height="9" rx="4.5" fill="${TC[t]}"/>
    <text x="${W}" y="${y+28}" class="sbv" text-anchor="end">${fmt(n)}</text></g>`}).join('')+'</svg>'}

function lanes(c){const ks=Object.keys(c.m).sort((a,b)=>c.m[b].length-c.m[a].length);
  const lo=D.lo,hi=Math.max(D.lo+60,D.hi),W=640,L=170,R=12,T=6,rh=Math.min(44,Math.max(24,300/ks.length)),H=T+rh*ks.length+30;
  const X=m=>L+(m-lo)/(hi-lo)*(W-L-R);let s='';
  const stp=hi-lo>360?120:60;for(let m=Math.ceil(lo/stp)*stp;m<=hi;m+=stp)s+=`<line class="grid v" x1="${X(m)}" y1="${T}" x2="${X(m)}" y2="${H-30}"/><text class="tick sm" x="${X(m)}" y="${H-8}" text-anchor="middle">${hm(m)}</text>`;
  ks.forEach((k,i)=>{const y=T+rh*i,hl=k===from,t=c.tr[k]||'g';
    s+=`<rect class="lanebg${hl?' hl':''}" x="${L}" y="${y+3}" width="${W-L-R}" height="${rh-6}" rx="4"/>`+
       `<text class="lane lk${hl?' hl':''}" data-go="${esc(k)}" x="${L-12}" y="${y+rh/2+5}" text-anchor="end"><title>Open ${esc(M[k].l)}</title>${esc(M[k].l.slice(0,24))}</text>`;
    c.m[k].forEach(m=>{const x=X(m);s+=`<circle class="ld" cx="${x.toFixed(1)}" cy="${(y+rh/2).toFixed(1)}" r="${Math.min(6,rh/4)}" fill="${TC[t]}" fill-opacity=".55" style="--d:${(.6+1.6*(x-L)/(W-L)).toFixed(2)}s"><title>${esc(M[k].l)} · ${hm(m)}</title></circle>`})});
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">${s}</svg>`}

const med=a=>{const b=a.slice().sort((x,y)=>x-y),n=b.length;return n?(n%2?b[(n-1)/2]:(b[n/2-1]+b[n/2])/2):0};
const ALL_T=corder.map(k=>C[k].t),MED_T=med(ALL_T),MAX_T=Math.max(1,...ALL_T);
const MED_PC=med(corder.filter(k=>C[k].cam).map(k=>C[k].t/C[k].cam));
function strip(t,hot){const X=v=>5+150*v/MAX_T;let s='<line x1="5" y1="13" x2="155" y2="13" class="ssl"/>';
  ALL_T.forEach(v=>s+=`<line x1="${X(v).toFixed(1)}" y1="9" x2="${X(v).toFixed(1)}" y2="17" class="sst"/>`);
  s+=`<line x1="${X(MED_T).toFixed(1)}" y1="5" x2="${X(MED_T).toFixed(1)}" y2="21" class="ssm"/>`;
  s+=`<circle cx="${X(t).toFixed(1)}" cy="13" r="4.5" class="ssd${hot?' r':''}" style="--dx:${(5-X(t)).toFixed(1)}px"/>`;
  return `<svg class="sstrip" viewBox="0 0 160 24" preserveAspectRatio="none">${s}</svg>`}
function stats(c,ks,crit,rank){
  const nm=Object.keys(M).length,ppc=c.cam?c.t/c.cam:0,critN=ks.filter(k=>c.tr[k]==='r').map(k=>M[k].l);
  const cells='<span class="cells">'+Object.keys(M).map(k=>`<i data-go="${esc(k)}" class="${c.m[k]?(c.tr[k]==='r'?'r':'on'):''}" title="${esc(M[k].l)}${c.m[k]?' · '+TN[c.tr[k]||'g']:' · none'}"></i>`).join('')+'</span>';
  const vs=(a,b)=>a>b*1.15?'above':a<b*.85?'below':'close to';
  const rows=[
    ['Alerts',`<b data-n="${c.t}">0</b>`,`Rank ${rank} of ${corder.length}; the median centre raised ${fmt(Math.round(MED_T))}.`,strip(c.t,crit>0)],
    ['Modalities',`<b data-n="${ks.length}">0</b><small>of ${nm}</small>`,cells,''],
    ['Cameras alerting',`<b data-n="${c.cam}">0</b>`,`${ppc.toFixed(1)} alerts per camera, ${vs(ppc,MED_PC)} the median of ${MED_PC.toFixed(1)}.`,''],
    ['Critical modalities',`<b class="${crit?'red':''}" data-n="${crit}">0</b>`,critN.length?ks.filter(k=>c.tr[k]==='r').map(k=>`<span class="lk" data-go="${esc(k)}">${esc(M[k].l)}</span>`).join(', '):'None reached critical.',''],
    ['Evidence frames',`<b data-n="${c.f.length}">0</b><small>of ${fmt(c.im)}</small>`,'Shown here in time order; the rest stay on file.',''],
  ];
  return rows.map(([l,v,x,vis],i)=>`<div class="st" style="--i:${i}"><div class="stl">${l}</div><div class="stv">${v}</div>${vis}<div class="stc">${x}</div></div>`).join('')}
function film(c){if(!c.f.length)return '<p class="empty">No evidence frames for this centre.</p>';
  return c.f.map((fi,i)=>{const f=F[fi];return `<div class="fc" data-f="${i}" style="--i:${i}"><img src="${f.u}" alt="">
   <span class="fn">${i+1}</span><span class="fm" data-go="${esc(f.m)}" title="Open ${esc(M[f.m].l)}" style="--c:${TC[c.tr[f.m]||'g']}">${esc(M[f.m].l)}</span>
   <div class="ft"><b>${esc(f.t)}</b> · ${esc(f.cam||f.z||'')}</div></div>`}).join('')}

function open(cc,mod){if(!C[cc])return;
  if(CV.cur===V)CV.through(['Centre',C[cc].n],()=>{fill(cc,mod);CV.replay(V);history.replaceState(null,'','#C-'+cc)});
  else{fill(cc,mod);CV.show('centre')}}
function fill(cc,mod){const c=C[cc];CV.cc=cc;if(mod!==undefined)from=mod;
  if(from&&!c.m[from])from=null;
  const ks=Object.keys(c.m),crit=ks.filter(k=>c.tr[k]==='r').length,rank=corder.indexOf(cc)+1;
  const top=ks.slice().sort((a,b)=>(RANK[c.tr[b]]-RANK[c.tr[a]])||(c.m[b].length-c.m[a].length))[0];
  const mb=$('cb-mod');if(from){mb.textContent=M[from].l;mb.dataset.go=from;mb.hidden=false;mb.nextElementSibling.hidden=false}
  else{mb.hidden=true;mb.nextElementSibling.hidden=true}
  $('cb-c').textContent=c.n;$('c-kick').textContent=`Centre ${cc} · rank ${rank} of ${corder.length} by alerts`;
  $('c-name').textContent=c.n;$('c-sub').innerHTML=(c.d?`<span class="lk" data-dist="${esc(c.d)}">${esc(c.d)}</span> · `:'')+`${c.cam} cameras alerting`;
  $('c-kpis').innerHTML=stats(c,ks,crit,rank);
  $('c-lead').innerHTML=`<b class="lk" data-go="${esc(top)}">${esc(M[top].l)}</b> is the heaviest here: ${fmt(c.m[top].length)} alerts, ${TN[c.tr[top]||'g'].toLowerCase()}. `+
    `<span class="ctx">This centre raised ${fmt(c.t)} alerts, ${(100*c.t/D.exam_alerts).toFixed(1)}% of the examination's.</span>`;
  $('c-bars').innerHTML=bars(c);$('c-lanes').innerHTML=lanes(c);$('c-film').innerHTML=film(c);
  $('c-rings').innerHTML=[ring(c.t,D.exam_alerts,'#3B5877','Share of all alerts','of every alert in the examination',0),
    ring(ks.length,Object.keys(M).length,'#7189A4','Modalities triggered','AI modalities that fired here',1),
    ring(crit,ks.length,'#B6403A','Critical modalities','modalities where this centre is critical',2),
    ring(c.f.length,c.im,'#8A97A6','Frames shown','evidence images, of those on file',3)].join('');
}
function cstep(k){const i=corder.indexOf(CV.cc);open(corder[(i+k+corder.length)%corder.length])}

// ---- lightbox: frames in time order, running on into the next centre
const LB=$('lb');let li=0,timer=null,flip=false;
function seq(){return C[CV.cc].f}
function lbShow(i){const fs=seq();if(!fs.length)return;li=(i+fs.length)%fs.length;const f=F[fs[li]],c=C[CV.cc];
  const a=$(flip?'lbimg2':'lbimg'),b=$(flip?'lbimg':'lbimg2');flip=!flip;
  a.src=f.u;a.classList.remove('kb');void a.offsetWidth;a.classList.add('kb');a.style.opacity=1;b.style.opacity=0;
  $('lbtitle').innerHTML=`<b>${esc(c.n)}</b> <span>· ${esc(c.d||'')} · centre ${esc(CV.cc)}</span>`;
  $('lbcap').innerHTML=`<span><b class="lk" data-go="${esc(f.m)}" title="Open ${esc(M[f.m].l)}">${esc(M[f.m].l)}</b> · ${TN[c.tr[f.m]||'g']}</span><span class="m">${esc(f.t)}</span><span>${esc(f.cam||'')}</span><span>${esc(f.z||'')}</span>`;
  $('lbcount').textContent=`Frame ${li+1} of ${fs.length}`;
  $('lbdots').innerHTML=fs.map((_,j)=>`<button data-lbi="${j}" class="${j===li?'sel':''}"></button>`).join('')}
function lbOpen(i){LB.hidden=false;lbShow(i)}
function lbClose(){LB.hidden=true;lbStop()}
CV.openCentre=(cc,mod)=>open(cc,mod);CV.lb={open:i=>lbOpen(i||0),close:()=>lbClose(),play:()=>{if(!timer)lbPlay()},stop:()=>lbStop()};
function lbStep(k){const fs=seq();
  if(k>0&&li===fs.length-1||k<0&&li===0){ // run on into the neighbouring centre that has frames
    let i=corder.indexOf(CV.cc);for(let n=0;n<corder.length;n++){i=(i+k+corder.length)%corder.length;if(C[corder[i]].f.length)break}
    open(corder[i]);lbShow(k>0?0:C[corder[i]].f.length-1);return}
  lbShow(li+k)}
function lbPlay(){if(timer)return lbStop();$('lbplay').textContent='❚❚ Pause';timer=setInterval(()=>lbStep(1),3800)}
function lbStop(){clearInterval(timer);timer=null;$('lbplay').textContent='▶ Play'}

// ---- tabs (Dashboard / Clock, Map / Clock)
function tab(btn){const t=btn.dataset.tab,holder=btn.closest('[data-tabs]');
  btn.parentElement.querySelectorAll('[data-tab]').forEach(b=>b.classList.toggle('sel',b===btn));
  const panes=holder?[...holder.querySelectorAll('[data-pane]')]
    :[...document.getElementById(btn.closest('[data-tabs-for]').dataset.tabsFor).children].filter(p=>p.dataset.pane);
  panes.forEach(p=>p.hidden=p.dataset.pane!==t);
  CV.replay(btn.closest('.view'))}

document.addEventListener('click',e=>{let t;
  if((t=e.target.closest('[data-go]'))&&(t.closest('.fc')||t.closest('#lb'))){e.stopPropagation();lbClose();CV.show(t.dataset.go);return}
  if(t=e.target.closest('[data-lb]')){e.stopPropagation();const a=t.dataset.lb;a==='x'?lbClose():a==='play'?lbPlay():(lbStop(),lbStep(+a));return}
  if(t=e.target.closest('[data-lbi]')){e.stopPropagation();lbStop();lbShow(+t.dataset.lbi);return}
  if(e.target===LB){lbClose();return}
  if(t=e.target.closest('[data-tab]')){e.stopPropagation();tab(t);return}
  if(t=e.target.closest('[data-f]')){e.stopPropagation();lbOpen(+t.dataset.f);return}
  if(t=e.target.closest('[data-play]')){e.stopPropagation();lbOpen(0);lbPlay();return}
  if(t=e.target.closest('[data-cstep]')){e.stopPropagation();cstep(+t.dataset.cstep);return}
  if(t=e.target.closest('[data-c]')){e.stopPropagation();const v=CV.cur;open(t.dataset.c,v&&v.classList.contains('mod')?v.dataset.id:null);return}
},true);
window.addEventListener('keydown',e=>{
  if(document.body.classList.contains('touring'))return;
  if(!LB.hidden){e.stopImmediatePropagation();e.preventDefault();
    if(e.key==='Escape')lbClose();else if(e.key==='ArrowRight'){lbStop();lbStep(1)}else if(e.key==='ArrowLeft'){lbStop();lbStep(-1)}else if(e.key===' ')lbPlay();return}
  if(CV.cur===V){if(e.key==='ArrowRight'||e.key==='ArrowLeft'){e.stopImmediatePropagation();cstep(e.key==='ArrowRight'?1:-1)}
    else if(e.key==='Escape'){e.stopImmediatePropagation();CV.show(from||'summary')}}
},true);
const h=location.hash.slice(1);if(h.startsWith('C-')){if(C[h.slice(2)])open(h.slice(2),null);else CV.show('summary')}
})();
"""


def _frame_uri(path: str) -> str | None:
    """An evidence frame as a small JPEG data URI (4:3, 480 px), so the file
    carries its own pictures and still opens offline."""
    from PIL import Image, ImageOps
    from . import storage
    p = storage.local_copy(path)
    if not p:
        return None
    try:
        im = ImageOps.fit(Image.open(p).convert("RGB"), (480, 360), Image.LANCZOS)
        buf = __import__("io").BytesIO()
        im.save(buf, "JPEG", quality=56, optimize=True)
        return "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001
        return None


def build_live(exam, dt: str, profs: list[dict], totals: dict) -> str:
    """Assemble the single-screen report. `profs` are report_render._profile
    dicts, each with "geo" set; `totals` are exam-wide alerts/centres/districts."""
    all_geo: dict = {}
    for p in profs:
        for k, n in p.get("geo", {}).items():
            all_geo[k] = all_geo.get(k, 0) + n
    base_svg, all_fills = _map_parts(all_geo)
    # the shared map carries no glow, labels or per-view state
    base_svg = re.sub(r'<g pointer-events="none">.*?</g>', "", base_svg, count=1, flags=re.S)
    maps = {"summary": {"fills": all_fills, "counts": _counts(all_geo)}}
    for p in profs:
        maps[p["code"]] = {"fills": _map_parts(p.get("geo", {}))[1], "counts": _counts(p.get("geo", {}))}
    comp = sorted(({"code": p["code"], "l": p["label"], "n": p["total"], "crit": p["crit"], "centres": p["centres"]}
                   for p in profs), key=lambda c: -c["n"])
    for p in profs:
        p["comp"], p["day_lo"], p["day_hi"] = comp, totals.get("lo", 0), totals.get("hi", 0)
    views = [_summary_view(exam, dt, profs, totals)]
    views += [_mod_view(exam, dt, p, i + 1, len(profs)) for i, p in enumerate(profs)]
    views.append(CENTRE_VIEW)
    views.append(DISTRICT_VIEW)
    data = json.dumps({"order": [p["code"] for p in profs], "maps": maps,
                       "mods": {p["code"]: {"l": p["label"], "n": p["total"], "c": p["crit"], "k": p["centres"]} for p in profs},
                       "centres": totals.get("centre_data", {}), "frames": totals.get("frames", []),
                       "lo": totals.get("lo", 0), "hi": totals.get("hi", 0),
                       "exam_alerts": totals["alerts"], "co": totals.get("co"), "exam": exam.name}, separators=(",", ":")).replace("</", "<\\/")
    css = CSS % {"navy": NAVY, "navy2": TIER["y"], "red": RED, "ink": INK, "mut": MUT, "grey": TIER["g"]}
    return (f'<!doctype html><html lang="en"><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width=device-width,initial-scale=1">'
            f'<title>{esc(exam.name)} · CamView</title><style>{_fonts()}{css}{_paper_css()}{CSS2}</style></head><body>'
            f'<div class="band"></div>{_rail(profs)}{"".join(views)}{LIGHTBOX}{_veil()}'
            f'<div id="mapsrc" hidden>{base_svg}</div><div id="tip"></div>'
            f'<script type="application/json" id="cvdata">{data}</script><script>{JS}</script><script>{JS2}</script><script>{JS3}</script><script>{JS4}</script><script>{JS5}</script></body></html>')


def _label(code: str, stored: str | None) -> str:
    """The registry's display name, else the stored one with any double-encoded
    UTF-8 (\"Â·\" for \"·\") repaired."""
    from .registry import get_registry
    m = get_registry().by_code(code)
    lab = (m.display_label if m and m.display_label else stored) or code
    if "Â" in lab or "â" in lab:          # UTF-8 read as cp1252 somewhere upstream
        try:
            return lab.encode("cp1252").decode("utf-8")
        except (UnicodeEncodeError, UnicodeDecodeError):
            pass
    return lab


def generate_live_report(session, exam_id: int, codes: list[str] | None = None, days=None,
                         frames_per_centre: int = 6) -> str:
    """Every modality of an exam (or the listed codes), as the live report HTML."""
    from . import reporting as R
    from .models import Alert
    from .report_render import _clock, _geo_values, _profile, _subloc_values
    base = (Alert.exam_id == exam_id, *R.days_cond(days))
    rows = session.execute(
        select(Alert.modality_code, func.max(Alert.display_label), func.count(Alert.id))
        .where(*base).group_by(Alert.modality_code).order_by(func.count(Alert.id).desc())).all()
    if codes:
        rows = [r for r in rows if r[0] in codes]
    profs, exam = [], None
    for code, label, _n in rows:
        d = R.gather(session, exam_id, code, _label(code, label), days=days)
        exam = d.exam
        P = _profile(d)
        P["geo"] = _geo_values(session, exam_id, code, days)
        P["subloc"] = _subloc_values(session, exam_id, code, days)
        profs.append(P)
    # most critical first, then by volume: the summary reads worst-first
    profs.sort(key=lambda p: (-p["crit"], -p["total"]))
    codes_used = [p["code"] for p in profs]
    totals = {
        "alerts": sum(p["total"] for p in profs),
        "centres": session.scalar(select(func.count(func.distinct(Alert.centre_code))).where(*base)) or 0,
        "districts": session.scalar(select(func.count(func.distinct(Alert.district))).where(*base, Alert.district != "")) or 0,
        "clock": _clock(session, exam, codes_used, days),
    }
    for p in profs:
        p["clock"] = _clock(session, exam, [p["code"]], days)
        p["all_centres"] = totals["centres"]
    totals.update(_centres_and_frames(session, base, profs, frames_per_centre))
    for p in profs:
        p["framed"] = totals["framed"].get(p["code"], 0)
    dt = f"{exam.exam_date:%d %B %Y}" if exam and exam.exam_date else ""
    return build_live(exam, dt, profs, totals)


def _centres_and_frames(session, base, profs, per_centre: int) -> dict:
    """Every centre's alerts by modality (minute of day, for the day lanes), its
    tier in each modality, and up to `per_centre` evidence frames chosen across
    its modalities — worst modality first, spread through the day — then put in
    time order so they play as a sequence."""
    from concurrent.futures import ThreadPoolExecutor
    from .models import Alert
    codes = [p["code"] for p in profs]
    tiers = {(p["code"], pt[1]): pt[4] for p in profs for pt in p.get("points") or []}
    rank = {"r": 3, "o": 2, "y": 1, "g": 0}
    rows = session.execute(
        select(Alert.centre_code, Alert.centre_name, Alert.district, Alert.modality_code, Alert.occurred_at,
               Alert.camera_name, Alert.zone, Alert.evidence_image)
        .where(*base, Alert.modality_code.in_(codes)).order_by(Alert.occurred_at)).all()
    cen: dict = {}
    slots: dict = {}          # (centre, 15-minute slot) -> modalities that fired there
    imgs: dict = {}
    framed: dict = {}
    lo, hi = 24 * 60, 0
    for cc, name, dist, code, at, cam, zone, img in rows:
        if not cc:
            continue
        c = cen.setdefault(cc, {"n": name or cc, "d": dist or "", "t": 0, "m": {}, "tr": {}, "cams": set(), "im": 0, "f": []})
        m = at.hour * 60 + at.minute if at else None
        c["t"] += 1
        c["m"].setdefault(code, [])
        if m is not None:
            c["m"][code].append(m)
            lo, hi = min(lo, m), max(hi, m)
            slots.setdefault((cc, m // 15), set()).add(code)
        if cam:
            c["cams"].add(cam)
        c["tr"][code] = tiers.get((code, cc), "g")
        if img:
            c["im"] += 1
            framed[code] = framed.get(code, 0) + 1
            imgs.setdefault(cc, {}).setdefault(code, []).append((m or 0, img, cam or "", zone or ""))
    # choose the frames: round-robin over the centre's modalities, worst first,
    # each modality's picks spread evenly through its day
    picks = []
    for cc, by in imgs.items():
        c = cen[cc]
        order = sorted(by, key=lambda k: (-rank[c["tr"].get(k, "g")], -len(by[k])))
        chosen, rnd = [], 0
        while len(chosen) < per_centre and any(len(by[k]) > rnd for k in order):
            for k in order:
                lst = by[k]
                need = min(len(lst), max(1, per_centre // len(order) + 1))
                if rnd < need:
                    j = round(rnd * (len(lst) - 1) / max(1, need - 1)) if need > 1 else len(lst) // 2
                    chosen.append((k, lst[j]))
                if len(chosen) >= per_centre:
                    break
            rnd += 1
            if rnd > per_centre:
                break
        for k, (m, img, cam, zone) in sorted(chosen, key=lambda x: x[1][0]):
            picks.append((cc, k, m, img, cam, zone))
    with ThreadPoolExecutor(max_workers=4) as ex:
        uris = list(ex.map(lambda r: _frame_uri(r[3]), picks))
    frames = []
    for (cc, k, m, _img, cam, zone), u in zip(picks, uris):
        if not u:
            continue
        cen[cc]["f"].append(len(frames))
        frames.append({"u": u, "m": k, "t": f"{m // 60:02d}:{m % 60:02d}", "cam": cam, "z": zone})
    for c in cen.values():
        c["cam"] = len(c.pop("cams"))
    # how often each pair of modalities fired at the same centre in the same 15 minutes
    idx = {k: i for i, k in enumerate(codes)}
    co = [[0] * len(codes) for _ in codes]
    for ks in slots.values():
        ks = sorted(ks, key=lambda k: idx[k])
        for i, a in enumerate(ks):
            for b in ks[i + 1:]:
                co[idx[a]][idx[b]] += 1
                co[idx[b]][idx[a]] += 1
    return {"centre_data": cen, "frames": frames, "framed": framed, "co": {"codes": codes, "m": co},
            "lo": (lo // 60) * 60 if hi else 0, "hi": ((hi // 60) + 1) * 60 if hi else 0}
