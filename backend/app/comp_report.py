"""Secure-box compliance report — the shipped 6-page landscape standard.

Ports the exact layout of the NEET / UPESSC trunk reports onto live portal data:
  1  Compliance summary   — KPI strip, authorised windows, arrival & opening donuts
  2  Arrival compliance    — ranked bars by state/district, minutes-late histogram,
                             which states/districts ran late (stacked, shaded by lateness)
  3  Opening compliance    — same, for openings
  4  Arrival & opening curves — detections per 15 min, authorised window shaded
  5  Investigation queue   — every off-window box, worst first, with deviation
  6  The evidence          — the actual alert frames behind the worst violations

Breakdown dimension follows the data: STATE when the exam spans many states,
else DISTRICT. Pure facts — counts and times measured against authorised windows.
"""
from __future__ import annotations

import html as _html
import math

from .geo import choropleth

V, RV, RED, AMBER = "#1A7F37", "#8A6D00", "#B42318", "#B45309"
INK, MUT, LN, LN2 = "#16202b", "#6a737d", "#d0d7de", "#e5e9ee"
BLUE = "#0a5ad6"
REDS = ["#EC9A86", "#DE6038", "#B42318", "#6E150E"]
AMBERS = ["#F3C98A", "#E29A3A", "#B45309", "#7A3606"]

esc = lambda s: _html.escape(str(s))

from .settings import get_settings
LOGO = (get_settings().assets_dir / "camview_logo_transparent.png").resolve()
_LOGO_IMG = f'<img src="file://{LOGO}" style="height:7mm;display:block" alt="CamView AI">'


def _m(hhmm: str) -> int:
    h, mn = hhmm.split(":")
    return int(h) * 60 + int(mn)


def hm(x: int) -> str:
    x = int(round(x))
    return f"{x // 60:02d}:{x % 60:02d}"


def _band(p: int) -> str:
    return RED if p < 60 else (AMBER if p < 80 else V)


def _bucket(v: int, edges: list[tuple[int, int]]) -> int:
    for i, (lo, hi) in enumerate(edges):
        if lo <= v <= hi:
            return i
    return len(edges) - 1


# ---------- SVG primitives (geometry copied from the shipped report) ----------
def donut(segs: list[tuple[int, str]], size: int = 148, thick: int = 0,
          center: str = "", sub: str = "") -> str:
    tot = sum(v for v, _ in segs) or 1
    thick = thick or size * 0.19   # ring thickness scales with size (visible hole at any size)
    cx = cy = size / 2
    r = size / 2 - 3
    ir = r - thick
    a = -math.pi / 2
    s = []
    nz = [(v, c) for v, c in segs if v > 0]
    if len(nz) == 1:
        # a single 100% segment is a full circle — an arc back to its own start
        # point renders nothing, so draw it as a stroked ring instead
        c = nz[0][1]
        s.append(f'<circle cx="{cx}" cy="{cy}" r="{(r + ir) / 2:.1f}" fill="none" '
                 f'stroke="{c}" stroke-width="{r - ir:.1f}"/>')
        nz = []
    for v, c in nz:
        if v <= 0:
            continue
        ang = 2 * math.pi * v / tot
        a2 = a + ang
        lg = 1 if ang > math.pi else 0
        x1, y1 = cx + r * math.cos(a), cy + r * math.sin(a)
        x2, y2 = cx + r * math.cos(a2), cy + r * math.sin(a2)
        xi2, yi2 = cx + ir * math.cos(a2), cy + ir * math.sin(a2)
        xi1, yi1 = cx + ir * math.cos(a), cy + ir * math.sin(a)
        s.append(f'<path d="M{x1:.1f} {y1:.1f} A{r} {r} 0 {lg} 1 {x2:.1f} {y2:.1f} '
                 f'L{xi2:.1f} {yi2:.1f} A{ir} {ir} 0 {lg} 0 {xi1:.1f} {yi1:.1f} Z" fill="{c}"/>')
        a = a2
    if center:
        s.append(f'<text x="{cx}" y="{cy - size*0.02:.1f}" text-anchor="middle" font-size="{size*0.2:.1f}" '
                 f'font-weight="800" font-family="Georgia,serif" fill="{INK}">{center}</text>')
    if sub:
        s.append(f'<text x="{cx}" y="{cy + size*0.11:.1f}" text-anchor="middle" font-size="{size*0.064:.1f}" fill="{MUT}">{sub}</text>')
    return (f'<svg viewBox="0 0 {size} {size}" width="{size}" height="{size}" '
            f'style="display:block;margin:0 auto;max-width:100%">{"".join(s)}</svg>')


def hbar_pct(items: list[tuple[str, int]]) -> str:
    """items = [(label, pct)] -> ranked compliance bars, shaded by band."""
    rowh, step, x0, w = 13, 18, 130, 256
    h = len(items) * step
    s = []
    for i, (lab, pct) in enumerate(items):
        y = i * step
        fill = w * pct / 100
        s.append(f'<text x="125" y="{y + 10}" text-anchor="end" font-size="8.5" fill="#33404d">{esc(lab)}</text>'
                 f'<rect x="{x0}" y="{y}" width="{w}" height="{rowh}" fill="#f0f2f5"/>'
                 f'<rect x="{x0}" y="{y}" width="{fill:.1f}" height="{rowh}" fill="{_band(pct)}"/>'
                 f'<text x="390" y="{y + 10}" font-size="8.5" font-family="ui-monospace" fill="{INK}">{pct}%</text>')
    return (f'<svg viewBox="0 0 420 {h}" width="100%" preserveAspectRatio="xMidYMid meet" '
            f'style="display:block">{"".join(s)}</svg>')


def vbars(items: list[tuple[str, int]], colors: list[str]) -> str:
    """items = [(label, count)] -> minutes-late distribution."""
    w, h, base = 430, 150, 124
    maxv = max((v for _, v in items), default=1) or 1
    n = len(items) or 1
    plot = w - 39
    step = plot / n
    bw = min(52, step * 0.55)
    s = [f'<line x1="26" y1="{base}" x2="{w - 13:.1f}" y2="{base}" stroke="{LN}"/>']
    for i, (lab, val) in enumerate(items):
        x = 26 + i * step + (step - bw) / 2
        bh = (val / maxv) * (base - 16)
        y = base - bh
        c = colors[min(i, len(colors) - 1)]
        s.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" fill="{c}"/>'
                 f'<text x="{x + bw / 2:.1f}" y="{y - 3:.1f}" text-anchor="middle" font-size="9" '
                 f'font-family="ui-monospace" fill="{INK}">{val}</text>'
                 f'<text x="{x + bw / 2:.1f}" y="{base + 11}" text-anchor="middle" font-size="7.6" fill="{MUT}">{esc(lab)}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="xMidYMid meet" '
            f'style="display:block">{"".join(s)}</svg>')


def stacked(rows: list[tuple[str, list[int]]], colors: list[str], unit_label: str = "late") -> str:
    """rows = [(name, [count per severity bucket])] -> who ran late, shaded."""
    rows = [r for r in rows if sum(r[1]) > 0]
    rows.sort(key=lambda r: sum(r[1]), reverse=True)
    rows = rows[:10]
    if not rows:
        return ""
    maxtot = max(sum(c for c in cs) for _, cs in rows) or 1
    x0, plot, step = 150, 840, 18
    unit = plot / maxtot
    h = len(rows) * step
    s = []
    for i, (name, cs) in enumerate(rows):
        y = i * step
        s.append(f'<text x="143" y="{y + 9}" text-anchor="end" font-size="9.5" fill="#33404d">{esc(name)}</text>')
        cur = x0
        for bi, cnt in enumerate(cs):
            if cnt <= 0:
                continue
            bwid = cnt * unit
            s.append(f'<rect x="{cur:.1f}" y="{y}" width="{bwid:.1f}" height="13" fill="{colors[bi]}"/>'
                     f'<text x="{cur + bwid / 2:.1f}" y="{y + 9}" text-anchor="middle" font-size="8.5" '
                     f'fill="#fff" font-family="ui-monospace">{cnt}</text>')
            cur += bwid
        s.append(f'<text x="{cur + 6:.1f}" y="{y + 10}" font-size="9.5" font-family="ui-monospace" '
                 f'fill="{INK}">{sum(cs)} {unit_label}</text>')
    return (f'<svg viewBox="0 0 1060 {h}" width="100%" preserveAspectRatio="xMidYMid meet" '
            f'style="display:block">{"".join(s)}</svg>')


def wave(hist: dict[int, int], win: tuple[int, int], caption: str, mark=None) -> str:
    w, h, pad = 1040, 215, 22
    if not hist:
        return f'<svg viewBox="0 0 {w} {h}" width="100%"></svg>'
    bins = {int(k): v for k, v in hist.items()}
    mn, mx = min(bins), max(bins)
    # anchor a 0 at every 15-min step so the line sits flat on zero between shifts
    # (no boxes open in the gap) — but KEEP every real data point, even when its
    # minute isn't on the 15-min grid, so no detection is silently dropped
    grid = sorted(set(range(mn, mx + 1, 15)) | set(bins))
    bins = {b: bins.get(b, 0) for b in grid}
    x0, x1 = mn, mx + 15
    span = (x1 - x0) or 1
    maxv = max(bins.values()) or 1
    X = lambda mm: pad + (mm - x0) / span * (w - 2 * pad)
    Y = lambda c: (h - pad) - (c / maxv) * (h - pad - 18)
    s = []
    wins = ((win if isinstance(win[0], (list, tuple)) else [win]) if win else [])   # one, many, or none
    multi = len(wins) > 1
    for ws, we in wins:
        if x1 >= ws and x0 <= we:
            rx0, rx1 = X(max(ws, x0)), X(min(we, x1))
            lbl = f"{hm(ws)}–{hm(we)}" if multi else caption   # each window labelled with its own range
            s.append(f'<rect x="{rx0:.1f}" y="15" width="{rx1 - rx0:.1f}" height="{h - pad - 15}" fill="{V}" opacity="0.18"/>')
            s.append(f'<text x="{(rx0 + rx1) / 2:.1f}" y="21" text-anchor="middle" font-size="7.5" fill="{V}">{lbl}</text>')
    s.append(f'<line x1="{pad}" y1="{h - pad}" x2="{w - pad}" y2="{h - pad}" stroke="{LN}"/>')
    nonzero = [(b, c) for b, c in sorted(bins.items()) if c > 0]
    if sum(c for _, c in nonzero) <= 3 or len(nonzero) <= 2:
        # too few points for a meaningful trend — draw discrete bars, not a filled
        # polygon that fakes a smooth distribution out of one or two detections
        bw = 7
        for b, c in nonzero:
            bx = X(b + 7.5)
            bh = (c / maxv) * (h - pad - 18)
            by = (h - pad) - bh
            s.append(f'<rect x="{bx - bw / 2:.1f}" y="{by:.1f}" width="{bw}" height="{bh:.1f}" fill="{BLUE}"/>'
                     f'<text x="{bx:.1f}" y="{by - 3:.1f}" text-anchor="middle" font-size="8.5" '
                     f'font-family="ui-monospace" fill="{INK}">{c}</text>')
    else:
        pts = [(X(b + 7.5), Y(c)) for b, c in sorted(bins.items())]
        poly = " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)
        s.append(f'<polygon points="{X(x0):.1f},{h - pad} {poly} {X(x1):.1f},{h - pad}" fill="{BLUE}" opacity="0.13"/>'
                 f'<polyline points="{poly}" fill="none" stroke="{BLUE}" stroke-width="1.8"/>')
    t = ((x0 // 60) + (1 if x0 % 60 else 0)) * 60
    while t <= x1:
        s.append(f'<text x="{X(t):.1f}" y="{h - pad + 11}" text-anchor="middle" font-size="7.5" fill="{MUT}">{hm(t)}</text>')
        t += 30
    if mark and x0 <= mark[0] <= x1:                # annotate an anomalous spike on the line
        mm, label, col = mark
        mx = X(mm)
        anchor = "start" if mx < w * 0.62 else "end"
        dx = 5 if anchor == "start" else -5
        s.append(f'<line x1="{mx:.1f}" y1="26" x2="{mx:.1f}" y2="{h - pad}" stroke="{col}" stroke-width="1" stroke-dasharray="2 2"/>'
                 f'<circle cx="{mx:.1f}" cy="26" r="3" fill="{col}"/>'
                 f'<text x="{mx + dx:.1f}" y="22" font-size="8.5" font-weight="700" fill="{col}" text-anchor="{anchor}">{esc(label)}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" width="100%" preserveAspectRatio="xMidYMid meet" '
            f'style="display:block">{"".join(s)}</svg>')


def legend(items: list[tuple[str, str]]) -> str:
    return '<div class="legend">' + "".join(
        f'<span><i style="background:{c}"></i>{esc(l)}</span>' for l, c in items) + "</div>"


# ---------- page assembly ----------
CSS = """*{margin:0;padding:0;box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact}
@page{size:297mm 210mm;margin:0}
html,body{background:#fff;color:#1f2328;font-family:system-ui,'Segoe UI',Roboto,Helvetica,Arial,sans-serif}
.mono{font-family:ui-monospace,'SF Mono',Menlo,Consolas,monospace}
.page{width:297mm;height:210mm;background:#fff;display:flex;flex-direction:column;overflow:hidden;page-break-after:always;position:relative}
.page:last-child{page-break-after:auto}
.ph{padding:6.5mm 9mm 3.5mm;border-top:3px solid #1A7F37;border-bottom:1px solid #d0d7de;display:flex;justify-content:space-between;align-items:flex-end}
.ph .kick{font-size:8.5px;letter-spacing:1.3px;text-transform:uppercase;color:#8a929b;margin-bottom:1.6mm}
.ph .pt{font-family:Georgia,'Times New Roman',serif;font-size:19px;font-weight:700;color:#16202b;letter-spacing:.2px}
.ph .pn{font-size:9.5px;color:#8a929b;font-family:ui-monospace,monospace;letter-spacing:.5px;white-space:nowrap}
.pbody{flex:1;padding:6mm 9mm;overflow:hidden}
.pf{display:flex;justify-content:space-between;align-items:center;font-size:7.5px;color:#8a929b;border-top:1px solid #d0d7de;padding:2.4mm 9mm}
.cover{margin-bottom:4mm}
.cover h1{font-family:Georgia,serif;font-size:25px;color:#16202b;font-weight:700;line-height:1.12}
.csub{font-size:12px;color:#6a737d;margin-top:2mm}
.bstrip{display:grid;grid-template-columns:repeat(6,1fr);border:1px solid #d0d7de;margin-bottom:6mm}
.bstat{padding:3.5mm 4mm;border-right:1px solid #e5e9ee}
.bstrip .bstat:last-child{border-right:0}
.bn{font-size:16px;font-weight:800;font-family:ui-monospace,monospace;color:#16202b}
.bn .bsub{font-size:11px;font-weight:600;color:#8a929b;margin-left:1px}
.bl{font-size:8px;color:#6a737d;text-transform:uppercase;letter-spacing:.4px;margin-top:1.4mm;line-height:1.3}
.fact{font-size:11px;line-height:1.55;color:#33404d;margin-bottom:5mm}
.rgap{display:flex;gap:3mm;align-items:flex-start;background:#fff7ed;border:1px solid #fed7aa;border-left:3px solid #EA580C;border-radius:3px;padding:3mm 4mm;margin-bottom:5mm;font-size:10.5px;line-height:1.5;color:#7c2d12}
.rgap .rgi{flex:none;width:5mm;height:5mm;border-radius:50%;background:#EA580C;color:#fff;font-weight:800;font-size:10px;display:flex;align-items:center;justify-content:center;margin-top:.3mm}
.rgap b{color:#9a3412}
.rgap .rgn{display:block;margin-top:1.2mm;font-family:ui-monospace,monospace;font-size:9px;color:#9a3412}
.fact b{color:#16202b}
.p1grid{display:grid;grid-template-columns:1.05fr 1fr 1fr;gap:7mm;align-items:stretch}
.h5{font-size:9px;letter-spacing:1.4px;text-transform:uppercase;color:#6a737d;font-weight:700;border-bottom:1px solid #d0d7de;padding-bottom:1.6mm;margin-bottom:3.5mm}
.schbox,.dnbox{border:1px solid #d0d7de;padding:4mm 4.5mm}
.dnbox{text-align:center;display:flex;flex-direction:column}
.dncap{font-size:10px;color:#33404d;margin-top:3mm;line-height:1.45}
.noassess{flex:1;display:flex;flex-direction:column;justify-content:center;align-items:center;gap:1.5mm;padding:6mm 0}
.na-mark{width:14mm;height:14mm;border-radius:50%;border:2px dashed #c4ccd4;color:#aab2bb;font-size:20px;font-weight:700;display:flex;align-items:center;justify-content:center}
.na-t{font-size:11px;font-weight:700;color:#57606a;margin-top:1mm}
.na-s{font-size:9px;color:#8a929b}
.barmore{font-size:8.5px;color:#8a929b;margin-top:2mm;font-style:italic}
.sched{width:100%;border-collapse:collapse;font-size:11.5px;margin-top:2mm}
.sched th{background:#eef1f4;color:#33404d;text-align:left;padding:2.6mm 3mm;border:1px solid #d0d7de;font-size:9px;text-transform:uppercase;letter-spacing:.5px}
.sched td{padding:2.8mm 3mm;border:1px solid #e5e9ee;font-family:ui-monospace,monospace}
.sched td:first-child{font-family:system-ui;font-weight:600}
.red{color:#B42318}.amber{color:#B45309}
.legend{display:flex;gap:5mm;flex-wrap:wrap;font-size:9px;color:#33404d;margin-top:2.5mm}
.legend span{white-space:nowrap}.legend i{display:inline-block;width:10px;height:10px;margin-right:3px;vertical-align:-1px}
.chgrid2{display:grid;grid-template-columns:1fr 1fr;gap:8mm;align-items:start}
.chbox h4,.chbox .h5{font-size:9px}
.qtbl{width:100%;border-collapse:collapse;font-size:9.5px}
.qtbl th{background:#eef1f4;color:#33404d;text-align:left;padding:1.8mm 2.5mm;border:1px solid #d0d7de;font-size:8px;text-transform:uppercase;letter-spacing:.4px}
.qtbl td{padding:1.5mm 2.5mm;border:1px solid #e5e9ee}
.qtbl tr.la td:first-child{border-left:3px solid #B45309}
.qtbl tr.eo td:first-child{border-left:3px solid #0a5ad6}
.qt{font-size:7.5px;font-weight:700;padding:.5mm 1.6mm;border-radius:2px;white-space:nowrap}
.qt.la{background:#FBE7D2;color:#B45309}.qt.eo{background:#E6F1FB;color:#185FA5}
.egrid2{display:grid;grid-template-columns:repeat(3,1fr);gap:5mm}
.ecard{border:1px solid #d0d7de}
.eimg{position:relative;height:62mm;background:#0b0e12;overflow:hidden}
.eimg img{width:100%;height:100%;object-fit:cover}
.etag{position:absolute;left:0;top:0;font-size:8px;font-weight:700;padding:1.2mm 2mm;color:#fff;letter-spacing:.4px;background:#1A7F37}
.eday{position:absolute;right:0;top:0;background:rgba(16,32,46,.85);color:#fff;font-size:8px;font-weight:700;padding:1.2mm 2mm}
.emeta{padding:2.6mm 3mm}
.ec{font-size:10px;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.ed{display:flex;justify-content:space-between;font-size:9px;color:#6a737d;margin-top:1.4mm}
.empty{color:#8a929b;font-size:11px;padding:24mm 0;text-align:center}
.shiftrow{display:grid;gap:6mm;margin-bottom:1mm}
.shiftrow .dnbox{padding:3.5mm 4mm}
.vcenter{height:100%;display:flex;flex-direction:column;justify-content:center}
.cov{font-size:8px;color:#6a737d;margin-top:auto;padding-top:2.6mm;border-top:1px dashed #d7dde3;line-height:1.5}
.cov b{color:#16202b}
.covnote{font-size:9px;color:#6a737d;background:#f6f8fa;border:1px solid #e5e9ee;border-left:3px solid #B45309;padding:2.4mm 3mm;margin-top:3mm;line-height:1.5}
.covnote b{color:#16202b}
.geobox{border:1px solid #d0d7de;padding:3.5mm 4mm;margin-top:5mm}
.hmapwrap{height:74mm;background:#fafbfc;border:1px solid #e7eaee;border-radius:2px;overflow:hidden;display:flex;align-items:center;justify-content:center;padding:2mm;margin-top:2.5mm}
.hmapwrap svg{width:100%;height:100%}
.geocap{font-size:8.5px;color:#8a929b;margin-top:2mm}
"""

ARR_EDGES = [(1, 5), (6, 10), (11, 20), (21, 9999)]
ARR_LBL = ["1–5m", "6–10m", "11–20m", ">20m"]
OPN_LATE_EDGES = [(1, 3), (4, 6), (7, 10), (11, 9999)]
OPN_LATE_LBL = ["1–3m", "4–6m", "7–10m", ">10m"]
OPN_EARLY_EDGES = [(1, 15), (16, 30), (31, 60), (61, 9999)]
OPN_EARLY_LBL = ["1–15m", "16–30m", "31–60m", ">60m"]


def _foot(meta: str) -> str:
    return f'<div class="pf"><span>{_LOGO_IMG}</span><span>{meta["dates"]}</span>' \
           f'<span>{meta["centres"]} centres · {meta["districts"]} districts · {meta["states"]} states</span></div>'


def _page(kick: str, title: str, n: int, total: int, body: str, foot: str) -> str:
    return (f'<section class="page"><div class="ph"><div><div class="kick">{esc(kick)}</div>'
            f'<div class="pt">{esc(title)}</div></div><div class="pn">Page {n} of {total}</div></div>'
            f'<div class="pbody">{body}</div>{foot}</section>')


def _compliance_bars_page(n: int, total: int, kind: str, agg: dict, data: dict, foot: str) -> str:
    dim = data["dim"]
    dimlbl = "state" if dim == "state" else "district"
    win = data["arr_win"] if kind == "arr" else data["opn_win"]
    by_shift = agg.get("by_shift", [])
    nshift = len(by_shift)
    word = "arrival" if kind == "arr" else "opening"
    Word = "Arrival" if kind == "arr" else "Opening"
    title = f"{Word} compliance"
    off_col = RED if kind == "arr" else AMBER

    if kind == "arr":
        kick = f"Box arrival across {nshift} authorised windows" if nshift > 1 else f"Box arrival vs the {win} window"
        lead = (f"Each shift's boxes measured against its authorised arrival window. "
                f'<b>{agg["inw"]} of {agg["n"]}</b> arrived on time; {agg["late"]} late, '
                f'{"none" if not agg["early"] else agg["early"]} early.')
        edges, labels, colors = ARR_EDGES, ARR_LBL, REDS
        hcap = f"Late arrivals — how many minutes late ({agg['late']})"
        vios = [v for v in agg["vios"] if v["cls"] == "late"]
        devs = [v["dev"] for v in vios]
        unit = "late"
        stack_title = f"Which {dimlbl}s ran late — late centres, shaded by how late"
        stack_lbls = ["1–5 min late", "6–10 min", "11–20 min", "over 20 min"]
    else:
        late_mode = agg["late"] >= agg["early"]
        kick = f"Box opening across {nshift} authorised windows" if nshift > 1 else f"Box opening vs the {win} window"
        lead = (f"Each detected opening is checked against its authorised opening window. "
                f"Of the <b>{agg['captured']}</b> openings detected: <b>{agg['inw']}</b> in window, "
                f"{agg['late']} late, {agg['early']} early. Percentages below are of detected openings.")
        if late_mode:
            edges, labels, colors = OPN_LATE_EDGES, OPN_LATE_LBL, AMBERS
            hcap = f"Late openings — how many minutes late ({agg['late']})"
            vios = [v for v in agg["vios"] if v["cls"] == "late"]
            devs = [v["dev"] for v in vios]
            unit = "late"
            stack_title = f"Which {dimlbl}s opened late — late centres, shaded by how late"
            stack_lbls = ["1–3 min late", "4–6 min", "7–10 min", "over 10 min"]
        else:
            edges, labels, colors = OPN_EARLY_EDGES, OPN_EARLY_LBL, AMBERS
            hcap = f"Early openings — how many minutes early ({agg['early']})"
            vios = [v for v in agg["vios"] if v["cls"] == "early"]
            devs = [-v["dev"] for v in vios]
            unit = "early"
            stack_title = f"Which {dimlbl}s opened early — early centres, shaded by how early"
            stack_lbls = ["1–15 min early", "16–30 min", "31–60 min", "over 60 min"]

    has_vio = (agg["late"] + agg["early"]) > 0

    # --- per-shift donut cards (both shifts shown individually). At full
    # compliance the shifts are the whole story, so the donuts get larger. ---
    dsize = 100 if has_vio else 134
    cards = ""
    for sh in by_shift:
        segs = [(sh["inw"], V), (sh["late"], off_col), (sh["early"], AMBER)]
        unc = sh.get("uncaptured", 0) if kind == "opn" else 0
        noun = "in window" if kind == "opn" else "on time"
        cap = f'<b>{sh["inw"]}</b> of {sh["n"]} {noun}'
        if sh["late"]:
            cap += f' · <b class="amber">{sh["late"]} late</b>'
        if sh["early"]:
            cap += f' · <b class="amber">{sh["early"]} early</b>'
        sub = "of detected" if (kind == "opn" and unc) else "in window"
        dn = donut(segs, size=dsize, center=f'{sh["pct"]}%', sub=sub)
        cards += (f'<div class="dnbox"><div class="h5">{esc(sh["name"])} · {sh["win"]}</div>'
                  f'{dn}<div class="dncap">{cap}</div></div>')
    blockttl = "By shift · in-window compliance of detected openings" if kind == "opn" else "By shift · in-window compliance"
    shift_block = (f'<div class="h5">{blockttl}</div>'
                   f'<div class="shiftrow" style="grid-template-columns:repeat({max(nshift,1)},1fr)">{cards}</div>') if by_shift else ""

    cnt = len(agg["by_dim"])
    barcap = f"{Word} compliance by {dimlbl} · {cnt} {dimlbl}{'s' if cnt != 1 else ''}"
    # the list is sorted worst-first; cap to what fits the page and disclose the
    # rest (the hidden ones are the highest-compliance, so naming the floor is honest)
    MAXBARS = 12 if has_vio else 16   # the violation page also carries a histogram + stacked block
    shown = agg["by_dim"][:MAXBARS]
    bydim_shown = [(d["name"].title() if dim == "state" else d["name"], d["pct"]) for d in shown]
    more = ""
    if cnt > len(shown):
        minpct = min(d["pct"] for d in agg["by_dim"][len(shown):])
        more = (f'<div class="barmore">+{cnt - len(shown)} more {dimlbl}s not shown — '
                f'all ≥ {minpct}% · the {len(shown)} lowest are listed</div>')
    bars_chbox = (f'<div class="chbox"><div class="h5">{esc(barcap)}</div>{hbar_pct(bydim_shown)}{more}'
                  f'{legend([("Below 60%", RED), ("60–79%", AMBER), ("80% and above", V)])}</div>')

    covnote = ""
    if kind == "opn":
        _u = agg.get("uncaptured", 0); _o = agg.get("orphans", 0)
        lines = []
        if _u:
            lines.append(f'<b>{_u}</b> arrival{"s" if _u != 1 else ""} detected but {"their openings were" if _u != 1 else "its opening was"} not detected')
        if _o:
            lines.append(f'<b>{_o}</b> opening{"s" if _o != 1 else ""} detected but {"their arrivals were" if _o != 1 else "its arrival was"} not detected')
        if lines:
            covnote = (f'<div class="covnote"><b>Detection coverage:</b> {agg["expected"]} arrivals and '
                       f'{agg["captured"]} openings were detected. Arrival and opening are logged independently, so the '
                       f'two counts need not match — ' + "; ".join(lines) + '. Compliance above is over the detected openings.</div>')

    if has_vio:
        hist = [0, 0, 0, 0]
        for d in devs:
            hist[_bucket(abs(d), edges)] += 1
        grp: dict[str, list[int]] = {}
        for v in vios:
            key = (v["state"] if dim == "state" else v["district"]).title() or "—"
            g = grp.setdefault(key, [0, 0, 0, 0])
            dv = v["dev"] if unit == "late" else -v["dev"]
            g[_bucket(abs(dv), edges)] += 1
        body = (f'<p class="fact">{lead}</p>{covnote}{shift_block}'
                f'<div class="chgrid2" style="margin-top:5mm">{bars_chbox}'
                f'<div class="chbox"><div class="h5">{esc(hcap)}</div>{vbars(list(zip(labels, hist)), colors)}</div></div>'
                f'<div class="chbox" style="margin-top:4mm"><div class="h5">{esc(stack_title)}</div>'
                f'{stacked(list(grp.items()), colors, unit)}{legend(list(zip(stack_lbls, colors)))}</div>')
    else:
        # full compliance — no empty violation charts; centre the shift donuts +
        # district ranking so the spare space reads as balanced, not dumped below
        body = (f'<div class="vcenter"><p class="fact">{lead}</p>{covnote}{shift_block}'
                f'<div style="margin-top:6mm">{bars_chbox}</div></div>')
    return _page(kick, title, n, total, body, foot)


def _geo_page(n: int, total: int, geo: dict, foot: str) -> str:
    """Dedicated geographic heat-map page. Renders for any district count — a
    single-district exam simply zooms to and shades that one district."""
    hmap = choropleth(geo["values"], light=True, label_top=10, pulse=3, fit_full=True)
    hot = max(geo["values"].items(), key=lambda kv: kv[1]) if geo["values"] else None
    hotname = (hot[0][1] if isinstance(hot[0], tuple) else hot[0]) if hot else ""
    lead = geo.get("cap", "")
    if hot:
        lead += f' Hottest: <b>{esc(hotname)}</b> — {hot[1]:,}.'
    body = (f'<p class="fact">{lead}</p>'
            f'<div class="hmapwrap" style="height:150mm">{hmap}</div>')
    return _page("Geographic concentration", geo.get("title", "Where box events concentrated"), n, total, body, foot)


def _day_page(n: int, total: int, date_label: str, dd: dict, foot: str) -> str:
    """One page for a single exam day: that day's box arrival and opening
    compliance, each broken out by shift (S1, S2, …)."""
    arr, opn = dd["arrival"], dd["opening"]

    def cards(agg, kind):
        if not agg["by_shift"]:
            return '<div class="empty" style="padding:10mm 0">No box events for this checkpoint on this day.</div>'
        off = RED if kind == "arr" else AMBER
        out = ""
        for sh in agg["by_shift"]:
            segs = [(sh["inw"], V), (sh["late"], off), (sh["early"], AMBER)]
            noun = "in window" if kind == "opn" else "on time"
            cap = f'<b>{sh["inw"]}</b> of {sh["n"]} {noun}'
            if sh["late"]:
                cap += f' · <b class="amber">{sh["late"]} late</b>'
            if sh["early"]:
                cap += f' · <b class="amber">{sh["early"]} early</b>'
            pct = f'{sh["pct"]}%'
            sub = "of detected" if kind == "opn" else "in window"
            out += (f'<div class="dnbox"><div class="h5">{esc(sh["name"])} · {sh["win"]}</div>'
                    f'{donut(segs, size=124, center=pct, sub=sub)}'
                    f'<div class="dncap">{cap}</div></div>')
        return out

    def block(title, agg, kind):
        ncol = max(len(agg["by_shift"]), 1)
        return (f'<div class="h5">{title}</div>'
                f'<div class="shiftrow" style="grid-template-columns:repeat({ncol},1fr)">{cards(agg, kind)}</div>')

    _u, _o = opn.get("uncaptured", 0), opn.get("orphans", 0)
    parts = []
    if _u:
        parts.append(f'{_u} arrival{"s" if _u != 1 else ""} with no opening detected')
    if _o:
        parts.append(f'{_o} opening{"s" if _o != 1 else ""} with no arrival detected')
    cov = (f'<div class="covnote"><b>Detection coverage:</b> {arr["n"]} arrivals and '
           f'{opn["captured"]} openings detected on this day'
           + (' — ' + "; ".join(parts) if parts else "") + '.</div>') if (arr["n"] or opn["captured"]) else ""

    lead = (f'Box arrival and opening on <b>{esc(date_label)}</b>, each checked against its authorised window. '
            f'Arrival: <b>{arr["inw"]} of {arr["n"]}</b> in window · Opening: '
            f'<b>{opn["inw"]} of {opn["captured"]}</b> detected in window.')
    body = (f'<p class="fact">{lead}</p>'
            f'<div style="margin-top:5mm">{block("Box arrival · by shift", arr, "arr")}</div>'
            f'<div style="margin-top:7mm">{block("Box opening · by shift", opn, "opn")}</div>{cov}')
    return _page(f"Secure question-paper box · {date_label}", f"Compliance · {date_label}", n, total, body, foot)


def build_body(exam, data, evidence: list[dict], per_day=None, total_days=None, geo=None) -> str:
    shifts = data["shifts"]
    arr, opn = data["arrival"], data["opening"]
    ndays = len(data["dates"])
    dt = data["dates"][0].strftime("%d %B %Y") if data["dates"] else ""
    if ndays > 1:
        dt = f"{data['dates'][0].strftime('%d %b')} – {data['dates'][-1].strftime('%d %b %Y')}"
    _rost0 = data.get("roster")
    _centres_lbl = f'{_rost0["reported"]} of {_rost0["total"]}' if _rost0 else data["centres"]
    meta = {"dates": dt, "centres": _centres_lbl, "districts": data["districts_n"], "states": data["states_n"]}
    foot = _foot(meta)
    data["arr_win"] = f"{shifts[0]['arrival'][0]}–{shifts[0]['arrival'][1]}"
    data["opn_win"] = f"{shifts[0]['opening'][0]}–{shifts[0]['opening'][1]}"

    # roster coverage: official centres whose box was never seen on camera
    rost = data.get("roster")
    if rost:
        centres_cell = (f'<div class="bstat"><div class="bn">{rost["reported"]}<span class="bsub">/{rost["total"]}</span></div>'
                        f'<div class="bl">Centres reported</div></div>')
    else:
        centres_cell = f'<div class="bstat"><div class="bn">{data["centres"]}</div><div class="bl">Centres</div></div>'
    # exam-days KPI: show "2/3" when the report covers a subset of the exam's days
    if total_days and total_days > ndays:
        days_cell = (f'<div class="bstat"><div class="bn">{ndays}<span class="bsub">/{total_days}</span></div>'
                     f'<div class="bl">Exam days covered</div></div>')
    else:
        days_cell = (f'<div class="bstat"><div class="bn">{ndays}</div>'
                     f'<div class="bl">Exam day{"s" if ndays != 1 else ""}</div></div>')
    roster_note = ""
    if rost and rost["silentN"]:
        base = (f'<b>{rost["silentN"]} of {rost["total"]} centres produced no secure-box alert at all.</b> '
                f'No Trunk-Placed or Trunk-Opened alert was raised — the box was never seen on camera, a monitoring '
                f'gap separate from and outside the compliance figures below.')
        if rost["silent"]:
            names = ", ".join(f'{esc(s["code"])} {esc(s["name"])}' for s in rost["silent"][:6])
            more = f' +{rost["silentN"] - 6} more' if rost["silentN"] > 6 else ""
            tail = f'<span class="rgn">{names}{more}</span>'
        else:
            tail = '<span class="rgn">Upload the official centre list to identify which centres.</span>'
        roster_note = f'<div class="rgap"><span class="rgi">!</span><div>{base} {tail}</div></div>'

    # ---- Page 1 ----
    srow = "".join(f"<th>{esc(s['name'])}</th>" for s in shifts)
    arow = "".join(f"<td>{s['arrival'][0]}–{s['arrival'][1]}</td>" for s in shifts)
    orow = "".join(f"<td>{s['opening'][0]}–{s['opening'][1]}</td>" for s in shifts)
    sched = (f'<table class="sched"><tr><th></th>{srow}</tr>'
             f'<tr><td>Box arrival</td>{arow}</tr><tr><td>Box opening</td>{orow}</tr></table>')

    no_early = "No box opened before its window. " if not opn["early"] else ""
    arr_seg = [(arr["inw"], V), (arr["late"], RED)] if arr["late"] >= arr["early"] else [(arr["inw"], V), (arr["early"], AMBER)]
    arr_cap = (f'<b>{arr["inw"]}</b> of {arr["n"]} on time'
               + (f' · <b class="red">{arr["late"]} late</b>' if arr["late"] else "")
               + (f' · <b class="amber">{arr["early"]} early</b>' if arr["early"] else ""))
    if opn["late"] >= opn["early"]:
        opn_seg, opn_off = [(opn["inw"], V), (opn["late"], AMBER)], f' · <b class="amber">{opn["late"]} late</b>' if opn["late"] else ""
    else:
        opn_seg, opn_off = [(opn["inw"], V), (opn["early"], AMBER)], f' · <b class="amber">{opn["early"]} early</b>' if opn["early"] else ""
    has_opening = opn["captured"] > 0
    if has_opening:
        _u = opn.get("uncaptured", 0); _o = opn.get("orphans", 0)
        opn_cap = f'<b>{opn["inw"]}</b> of {opn["captured"]} detected in window{opn_off}'
        opn_cov = f'<div class="cov"><b>{opn["expected"]}</b> arrivals · <b>{opn["captured"]}</b> openings detected</div>'
        opn_dn_sub = "of detected" if opn.get("uncaptured") else "in window"
        opn_box = (f'<div class="dnbox"><div class="h5">Box opening</div>'
                   f'{donut(opn_seg, center=f"{opn["pct"]}%", sub=opn_dn_sub)}'
                   f'<div class="dncap">{opn_cap}</div>{opn_cov}</div>')
        _mis = []
        if _u:
            _mis.append(f'{_u} arrival{"s" if _u != 1 else ""} had no opening detected')
        if _o:
            _mis.append(f'{_o} opening{"s" if _o != 1 else ""} had no arrival detected')
        cov_txt = (f' Arrival and opening are checked independently against their windows; opening compliance is over '
                   f'the <b>{opn["captured"]}</b> detected openings'
                   + (f' ({"; ".join(_mis)})' if _mis else '') + '.')
    else:
        # no Trunk-Open detections at all — opening is not assessable. Show a clean
        # "not assessed" panel instead of an empty 0% ring, and an arrival-only note.
        opn_box = ('<div class="dnbox"><div class="h5">Box opening</div>'
                   '<div class="noassess"><div class="na-mark">—</div>'
                   '<div class="na-t">No opening captured</div>'
                   '<div class="na-s">No Trunk-Open events in this export</div></div></div>')
        cov_txt = (' No <b>Trunk-Open</b> (box opening) detections are present in this export, so opening '
                   'compliance is not assessed — this report covers box <b>arrival</b> only.')

    sub = "Secure Question-Paper Box (Trunk) — Centre Compliance"
    body1 = (f'<div class="cover"><h1>{esc(exam.name)}</h1>'
             f'<div class="csub">{esc(sub)} · {esc(dt)}</div></div>'
             f'<div class="bstrip">'
             f'{days_cell}'
             f'<div class="bstat"><div class="bn">{len(shifts)}</div><div class="bl">Shift{"s" if len(shifts) != 1 else ""}</div></div>'
             f'{centres_cell}'
             f'<div class="bstat"><div class="bn">{data["districts_n"]}</div><div class="bl">Districts</div></div>'
             f'<div class="bstat"><div class="bn">{data["states_n"]}</div><div class="bl">States</div></div>'
             f'<div class="bstat"><div class="bn">{esc(data["cctv"])}</div><div class="bl">CCTV window</div></div></div>'
             f'<p class="fact">The secure question-paper box was measured at two points — its <b>arrival</b> in the '
             f'control room and its <b>opening</b> — against the authorised windows below. Arrival was the earliest '
             f'<b>Trunk&nbsp;Placed</b> sighting per centre; opening the earliest <b>Trunk&nbsp;Opened</b> at or after '
             f'the box was due. Repeat camera alerts for the same box were collapsed to the first.{cov_txt} {no_early}</p>'
             f'{roster_note}'
             f'<div class="p1grid">'
             f'<div class="schbox"><div class="h5">Authorised windows</div>{sched}</div>'
             f'<div class="dnbox"><div class="h5">Box arrival</div>{donut(arr_seg, center=f"{arr['pct']}%", sub="in window")}'
             f'<div class="dncap">{arr_cap}</div></div>'
             f'{opn_box}</div>'
             + (legend([("In window", V), ("Late arrival", RED), ("Opening off-window", AMBER)]) if has_opening
                else legend([("In window", V), ("Late arrival", RED)])))
    # ---- page set is fluid -------------------------------------------------
    # The opening-compliance page is dropped entirely when no box opening was
    # captured (arrival-only export); the investigation queue paginates so EVERY
    # off-window box is listed; evidence paginates at EVCAP frames per page.
    EVCAP, QCAP = 6, 26
    ev_chunks = [evidence[i:i + EVCAP] for i in range(0, len(evidence), EVCAP)] or [[]]
    q = data["queue"]
    q_chunks = [q[i:i + QCAP] for i in range(0, len(q), QCAP)]

    # curves page — arrival + opening, or arrival-only when no opening captured
    aw = [(_m(sh["arrival"][0]), _m(sh["arrival"][1])) for sh in shifts]
    arr_curve = (f'<div class="chbox"><div class="h5">Box arrivals across the day — earliest sighting per centre</div>'
                 f'{wave(data["arr_hist"], aw, data["arr_win"])}</div>')
    if has_opening:
        ow = [(_m(sh["opening"][0]), _m(sh["opening"][1])) for sh in shifts]
        opn_curve = (f'<div class="chbox" style="margin-top:6mm"><div class="h5">Box openings across the day</div>'
                     f'{wave(data["opn_hist"], ow, data["opn_win"])}</div>')
        curve_intro = ('When boxes arrived (top) and were opened (bottom) across the day, each plotted in '
                       '15-minute steps with the authorised window shaded green.')
        curve_kick, curve_title = "Timing across the day", "Arrival & opening curves"
    else:
        opn_curve = ""
        curve_intro = ('When boxes arrived across the day, plotted in 15-minute steps with the authorised '
                       'arrival window shaded green.')
        curve_kick, curve_title = "Arrival timing across the day", "Arrival curve"
    body4 = (f'<p class="fact">{curve_intro}</p>{arr_curve}{opn_curve}'
             f'{legend([("Detections per 15 min", BLUE), ("Authorised window", V)])}')

    def queue_page(n, total, chunk, pidx, npages):
        multi_state = data["dim"] == "state"
        nla = sum(1 for e in q if e["kind"].startswith("Late arrival"))
        rows = []
        for e in chunk:
            cls = "la" if "arrival" in e["kind"].lower() else "eo"
            sgn = "+" if e["dev"] > 0 else "−"
            st = f'<td>{esc(e["state"].title())}</td>' if multi_state else ""
            rows.append(f'<tr class="{cls}">{st}<td>{esc(e["district"].title()[:16])}</td>'
                        f'<td>{esc(e["centre"][:28])}</td>'
                        f'<td class="mono">{esc(e.get("date", ""))}</td><td>{esc(e.get("shift", ""))}</td>'
                        f'<td><span class="qt {cls}">{esc(e["kind"])}</span></td>'
                        f'<td class="mono">{esc(e["window"])}</td><td class="mono">{esc(e["actual"])}</td>'
                        f'<td class="mono"><b>{sgn}{abs(e["dev"])}m</b></td></tr>')
        st_head = "<th>State</th>" if multi_state else ""
        if pidx == 0:
            lead = (f'Every box that fell outside its authorised window — <b>{len(q)} in total</b> '
                    f'({nla} late arrivals, {len(q) - nla} opening exceptions), worst first.'
                    + (f' Listed in full across {npages} pages.' if npages > 1 else ' All are listed below.'))
        else:
            lo = pidx * QCAP + 1
            lead = f'Investigation queue continued — entries <b>{lo}–{lo + len(chunk) - 1}</b> of {len(q)}, worst first.'
        suffix = "" if npages == 1 else f" · {pidx + 1} of {npages}"
        body = (f'<p class="fact">{lead}</p>'
                f'<table class="qtbl"><thead><tr>{st_head}<th>District</th><th>Centre</th><th>Date</th><th>Shift</th><th>Type</th>'
                f'<th>Window</th><th>Actual</th><th>Deviation</th></tr></thead><tbody>{"".join(rows)}</tbody></table>')
        return _page("Off-window events, worst first", f"Investigation queue{suffix}", n, total, body, foot)

    def evidence_page(n, total, chunk, ci):
        if chunk:
            cards = "".join(
                f'<div class="ecard"><div class="eimg"><img src="file://{e["img"]}">'
                f'<span class="etag">TRUNK</span><span class="eday">{esc(e["tag"])}</span></div>'
                f'<div class="emeta"><div class="ec">{esc(e["centre"][:34])}</div>'
                f'<div class="ed"><span>{esc(e["loc"])}</span><span class="mono">{esc(e["time"])}</span></div></div></div>'
                for e in chunk)
            cont = "" if ci == 0 else " (continued)"
            lead = ('The actual alert frame behind each box, retrieved on demand from the evidence store.'
                    if ci == 0 else f'Evidence frames continued — {len(evidence)} in total.')
            body = f'<p class="fact">{lead}</p><div class="egrid2">{cards}</div>'
        else:
            cont, body = "", '<div class="empty">No evidence frames are linked for this export.</div>'
        return _page("Every flagged event has a retrievable frame",
                     f"The evidence — boxes on camera{cont}", n, total, body, foot)

    builders = [
        lambda n, t: _page(f"{exam.code} · secure question-paper box", "Compliance summary", n, t, body1, foot),
    ]
    # Multi-day report → one page per day (that day's shifts). Single day → the
    # richer aggregated arrival/opening pages (district bars, minute histograms).
    if per_day and len(per_day) > 1:
        for _dlabel, _dd in per_day:
            builders.append((lambda dl, dd: lambda n, t: _day_page(n, t, dl, dd, foot))(_dlabel, _dd))
    else:
        builders.append(lambda n, t: _compliance_bars_page(n, t, "arr", arr, data, foot))
        if has_opening:
            builders.append(lambda n, t: _compliance_bars_page(n, t, "opn", opn, data, foot))
    if geo and geo.get("values"):
        builders.append(lambda n, t: _geo_page(n, t, geo, foot))
    builders.append(lambda n, t: _page(curve_kick, curve_title, n, t, body4, foot))
    for qi, qc in enumerate(q_chunks):
        builders.append((lambda qc, qi: lambda n, t: queue_page(n, t, qc, qi, len(q_chunks)))(qc, qi))
    for ci, chunk in enumerate(ev_chunks):
        builders.append((lambda chunk, ci: lambda n, t: evidence_page(n, t, chunk, ci))(chunk, ci))

    total = len(builders)
    pages = "".join(b(i + 1, total) for i, b in enumerate(builders))
    return f'<!doctype html><html><head><meta charset="utf-8"><style>{CSS}</style></head><body>{pages}</body></html>'
