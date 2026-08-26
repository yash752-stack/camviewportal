"""On-demand report rendering for the portal.

Builds the standardised facts-only event report for a modality and renders it to
PDF with headless Chromium. Same engine the batch CLI uses, callable from a web
route. Layout: 3 dense pages, severity-arranged, nothing stretched.
"""
from __future__ import annotations

import os
import re
import subprocess
from pathlib import Path

from PIL import Image
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import reporting as R
from .db import engine
from .models import Alert, Exam
from .settings import get_settings

_settings = get_settings()
LOGO = (_settings.assets_dir / "camview_logo_white_cropped.png").resolve()


def _find_chrome() -> str | None:
    """Locate a Chromium-family browser for headless PDF printing. Falls back
    across machines/installs so report export works wherever Chrome/Edge lives.
    Returns None (never a guessed path) if nothing is actually found, so callers
    can raise a clear error instead of crashing on a bogus path."""
    import shutil

    # Explicit override always wins (set CAMVIEW_CHROME_PATH if auto-detect
    # ever picks the wrong browser or none at all on a given machine).
    override = os.environ.get("CAMVIEW_CHROME_PATH", "").strip()
    if override and os.path.exists(override):
        return override

    candidates = [
        # macOS
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/Applications/Chromium.app/Contents/MacOS/Chromium",
        "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
        "/Applications/Brave Browser.app/Contents/MacOS/Brave Browser",
    ]
    # Windows (Edge ships with Windows 10/11; Chrome common too). Cover both
    # Program Files locations plus the native 64-bit path (ProgramW6432),
    # since a 32-bit-launched process can otherwise get redirected away from it.
    pf = os.environ.get("ProgramFiles", r"C:\Program Files")
    pfx = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
    pf64 = os.environ.get("ProgramW6432", pf)
    lad = os.environ.get("LOCALAPPDATA", "")
    candidates += [
        rf"{pf}\Google\Chrome\Application\chrome.exe",
        rf"{pfx}\Google\Chrome\Application\chrome.exe",
        rf"{pf64}\Google\Chrome\Application\chrome.exe",
        rf"{lad}\Google\Chrome\Application\chrome.exe" if lad else "",
        rf"{pfx}\Microsoft\Edge\Application\msedge.exe",
        rf"{pf}\Microsoft\Edge\Application\msedge.exe",
        rf"{pf64}\Microsoft\Edge\Application\msedge.exe",
        rf"{lad}\Microsoft\Edge\Application\msedge.exe" if lad else "",
        rf"{pfx}\BraveSoftware\Brave-Browser\Application\brave.exe",
    ]
    for p in candidates:
        if p and os.path.exists(p):
            return p
    for name in ("google-chrome", "chromium", "chromium-browser", "microsoft-edge",
                 "brave-browser", "chrome", "chrome.exe", "msedge", "msedge.exe"):
        found = shutil.which(name)
        if found:
            return found
    return None  # nothing found anywhere; _render_pdf() raises a clear error instead of crashing


CHROME = _find_chrome()


def _render_pdf(html_path: Path, pdf_path: Path, timeout: int = 120) -> Path:
    """Print an HTML file to PDF via headless Chrome/Edge, with error handling
    that turns a missing/broken browser into a clear message instead of a raw
    500 crash. Re-detects the browser on every call (cheap) so installing
    Chrome/Edge after the app started is picked up without a restart."""
    chrome = CHROME or _find_chrome()
    if not chrome:
        raise RuntimeError(
            "No Chrome, Edge or Brave browser could be found on this machine, so "
            "PDF reports can't be generated (dashboards and evidence still work "
            "without it). Install Google Chrome or Microsoft Edge, or set the "
            "CAMVIEW_CHROME_PATH environment variable to the full path of the "
            "browser's .exe, then restart the portal."
        )
    try:
        # In a Linux container Chromium must run with --no-sandbox and without
        # relying on /dev/shm (which is tiny by default), or it crashes on launch.
        # These flags are opt-in via CAMVIEW_CHROME_CONTAINER=1 so desktop
        # (Windows/macOS) behaviour is completely unchanged.
        extra = []
        if os.environ.get("CAMVIEW_CHROME_CONTAINER", "").strip() in ("1", "true", "yes"):
            extra = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-setuid-sandbox"]
        result = subprocess.run(
            [chrome, "--headless", "--disable-gpu", "--no-pdf-header-footer", *extra,
             f"--print-to-pdf={pdf_path.resolve()}", f"file://{html_path.resolve()}"],
            capture_output=True, timeout=timeout,
        )
    except FileNotFoundError as e:
        raise RuntimeError(
            f"Could not launch the browser expected at '{chrome}' ({e}). It may "
            "have been moved or uninstalled. Set CAMVIEW_CHROME_PATH to the "
            "correct browser .exe and restart the portal."
        ) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(
            f"PDF generation timed out after {timeout}s. The report may be very "
            "large, or the browser may be stuck — try again, or check that no "
            "antivirus/security policy is blocking the browser from running headless."
        ) from e
    if not pdf_path.exists() or pdf_path.stat().st_size == 0:
        stderr = (result.stderr or b"").decode(errors="replace").strip()
        detail = f" Browser error: {stderr[-500:]}" if stderr else ""
        raise RuntimeError(f"PDF was not produced by the browser (exit code {result.returncode}).{detail}")
    return pdf_path

CSS = """@page{size:A4;margin:0}*{margin:0;padding:0;box-sizing:border-box}
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500;600&family=IBM+Plex+Serif:wght@500;600;700&display=swap');
body{font-family:'IBM Plex Sans',sans-serif;color:#1a1a1a;background:#5a5a5a}
.page{width:210mm;height:296mm;background:#fff;margin:0 auto;padding:16mm 18mm 11mm;position:relative;page-break-after:always;display:flex;flex-direction:column;overflow:hidden}
.rule{height:4px;background:#1f7a3d;margin:-4mm 0 6mm}
.head{display:flex;justify-content:space-between;align-items:flex-end;border-bottom:1px solid #e2e2e0;padding-bottom:9px;margin-bottom:16px}
.eyebrow{font-size:9px;letter-spacing:.16em;text-transform:uppercase;color:#8a8a88}
.htitle{font-family:'IBM Plex Serif',serif;font-size:20px;font-weight:600;margin-top:4px}
.pg{font-family:'IBM Plex Mono';font-size:10px;letter-spacing:.1em;color:#999;text-transform:uppercase}
.brandrow{display:flex;justify-content:space-between;align-items:center;margin-bottom:13px}
.brandrow .logo{height:30px}
.ctitle{font-family:'IBM Plex Serif',serif;font-size:32px;font-weight:600;line-height:1.1}
.csub{font-size:13px;color:#555;margin-top:7px}
.kstrip{display:flex;border:1px solid #e2e2e0;border-radius:3px;margin:18px 0 0}
.kstrip .k{flex:1;padding:13px 15px;border-right:1px solid #eee}.kstrip .k:last-child{border-right:none}
.kstrip .n{font-family:'IBM Plex Mono';font-size:21px;font-weight:600}
.kstrip .l{font-size:8.5px;letter-spacing:.09em;text-transform:uppercase;color:#999;margin-top:5px}
.sect-d{font-size:11.5px;color:#777;margin:2px 0 14px}
.panel{border:1px solid #e2e2e0;border-radius:3px;padding:16px 18px;margin-bottom:12px}
.cgraph-h{display:flex;justify-content:space-between;align-items:baseline;margin-bottom:10px}
.cgraph-h .t{font-size:11px;text-transform:uppercase;letter-spacing:.07em;color:#888}
.rr{display:grid;grid-template-columns:140px 1fr 50px;align-items:center;gap:12px;padding:5.5px 0}
.rr .dn{font-size:11.5px}.rr .tk{height:16px;background:#e7e9e7;border-radius:2px;overflow:hidden}
.rr .fl{display:block;height:100%;min-width:2px}.rr .vn{font-family:'IBM Plex Mono';font-size:11px;text-align:right}
.vleg{display:flex;align-items:center;gap:9px;font-size:10px;color:#999;margin-top:12px}
.vleg .ramp{width:120px;height:9px;border-radius:2px;background:linear-gradient(90deg,rgb(122,199,150),rgb(13,84,41))}
table{width:100%;border-collapse:collapse;font-size:11.5px}
th{text-align:left;font-size:8.5px;letter-spacing:.07em;text-transform:uppercase;color:#999;border-bottom:1.5px solid #e2e2e0;padding:8px}
th.num,td.num{text-align:right}
td{padding:9.5px 8px;border-bottom:1px solid #f0f0ee}td.rk{color:#bbb;font-family:'IBM Plex Mono';width:24px}
td.mono{font-family:'IBM Plex Mono'}td.num{font-weight:600;font-family:'IBM Plex Mono'}
.gal{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
.ev{border:1px solid #e2e2e0;border-radius:3px;overflow:hidden}
.ev .imw{aspect-ratio:4/3;background:#222}.ev img{width:100%;height:100%;object-fit:cover;display:block}
.ev figcaption{padding:8px 9px;font-size:10px;line-height:1.5}.ev figcaption b{font-family:'IBM Plex Mono'}
.ev .cm{color:#888}.ev .ref{font-family:'IBM Plex Mono';font-size:7.5px;color:#bbb}
.foot{margin-top:auto;display:flex;justify-content:space-between;font-size:8.5px;color:#999;border-top:1px solid #e2e2e0;padding:8px 0 10px}
.tlchart{height:200px;display:flex;align-items:flex-end;gap:0;border-bottom:1px solid #e2e2e0;padding-top:8px}
.tlbar{flex:1 1 0;background:#3f9a5e}.tlbar.pk{background:#1f7a3d}.tlbar.nz{min-width:2.5px;border-radius:1px 1px 0 0}
.tlaxis{display:flex;justify-content:space-between;font-family:'IBM Plex Mono';font-size:10px;color:#999;padding-top:7px}
.summary{display:grid;grid-template-columns:172px 1fr;gap:26px;align-items:center;border:1px solid #e2e2e0;border-radius:3px;padding:16px 20px;margin-top:14px}
.summary .dlab{text-align:center;font-size:9px;letter-spacing:.09em;text-transform:uppercase;color:#999;margin-top:7px}
.leg .lr{display:flex;align-items:center;gap:11px;padding:7px 0;font-size:13px;border-bottom:1px solid #f1f1ef}
.leg .lr:last-child{border-bottom:none}
.leg .sw{width:11px;height:11px;border-radius:2px;flex:none}
.leg .ln{color:#333} .leg .desc{color:#999;font-size:11px}
.leg .lv{margin-left:auto;font-family:'IBM Plex Mono';font-weight:600;font-size:13px}
.leg .lp{font-family:'IBM Plex Mono';color:#aaa;width:40px;text-align:right;font-size:11px}
.sleg{display:flex;gap:16px;font-size:10.5px;color:#777;margin-top:13px}
.sleg .s{display:flex;align-items:center;gap:6px}.sleg .sw{width:9px;height:9px;border-radius:2px}
td .sd{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:8px;vertical-align:0}
.grow{flex:1;display:flex;flex-direction:column}
.grow .tlchart{flex:1;height:auto;min-height:0}
.drank{flex:1;display:flex;flex-direction:column;justify-content:space-between;padding:10px 0}
.drank .rr{padding:0}
.crow{display:grid;grid-template-columns:1.05fr 1fr 1fr;gap:13px;margin-top:14px}
.cpanel{border:1px solid #e2e2e0;border-radius:3px;padding:15px 16px}
.cpanel .ch{font-size:9px;letter-spacing:.1em;text-transform:uppercase;color:#999;text-align:center;margin-bottom:13px}
.wtab{width:100%;font-size:11.5px;border-collapse:collapse}
.wtab th{font-size:8.5px;letter-spacing:.05em;text-transform:uppercase;color:#999;text-align:left;padding:7px 6px;border-bottom:1px solid #e2e2e0;background:#fafafa}
.wtab td{padding:8px 6px;border-bottom:1px solid #f0f0ee;font-family:'IBM Plex Mono';font-size:11px}
.wtab td.lab{font-family:'IBM Plex Sans';font-weight:600}
.cdon{display:flex;flex-direction:column;align-items:center;justify-content:center}
.cdon .sub{font-size:11px;color:#777;margin-top:8px;text-align:center}.cdon .sub b{color:#1a1a1a;font-family:'IBM Plex Mono'}
.cdon .sub .bad{color:#C4553F}.cdon .sub .warn{color:#C07A46}
"""

import math
_TIERCOL = {"r": "#C4553F", "o": "#C07A46", "y": "#A8955C", "g": "#4E8279"}
_TIERNAME = {"r": "Critical", "o": "High", "y": "Elevated", "g": "Normal"}
_TIERDESC = {"r": "sustained / repeated", "o": "elevated", "y": "intermittent", "g": "transient"}
_TIERRANK = {"r": 0, "o": 1, "y": 2, "g": 3}


def _tier(run: int, count: int, is_count: bool) -> str:
    if is_count:
        return "r" if count >= 5 else "o" if count >= 2 else "y"
    return "r" if run >= 75 else "o" if run >= 45 else "y" if run >= 15 else "g"


def _sev_donut(sev: dict) -> str:
    total = sum(sev.values()) or 1
    R, off, segs = 52, 0.0, ""
    C = 2 * math.pi * R
    for t in ("r", "o", "y", "g"):
        frac = sev[t] / total
        if frac <= 0:
            continue
        segs += (f'<circle cx="70" cy="70" r="{R}" fill="none" stroke="{_TIERCOL[t]}" stroke-width="19" '
                 f'stroke-dasharray="{frac*C:.1f} {C:.1f}" stroke-dashoffset="{-off*C:.1f}" transform="rotate(-90 70 70)"/>')
        off += frac
    return (f'<svg viewBox="0 0 140 140" width="150">{segs}'
            f'<text x="70" y="66" text-anchor="middle" font-size="28" font-weight="700" font-family="IBM Plex Mono" fill="#1a1a1a">{sev["r"]}</text>'
            f'<text x="70" y="86" text-anchor="middle" font-size="7.5" fill="#999" letter-spacing="1">CRITICAL</text></svg>')


def _thumb(img_path: str, key: str, thumbs: Path) -> Path | None:
    try:
        im = Image.open(img_path).convert("RGB")
        w, h = im.size
        tr = 4 / 3
        if w / h > tr:
            nw = int(h * tr); im = im.crop(((w - nw) // 2, 0, (w - nw) // 2 + nw, h))
        else:
            nh = int(w / tr); im = im.crop((0, (h - nh) // 2, w, (h - nh) // 2 + nh))
        im = im.resize((480, 360))
        p = thumbs / f"{key}.jpg"; im.save(p, quality=85); return p.resolve()
    except Exception:
        return None


def _timeline(d) -> tuple[str, str]:
    if not d.tmin or not d.tmax:
        return "", ""
    start = (d.tmin.hour * 60 + d.tmin.minute) // 5 * 5
    end = (d.tmax.hour * 60 + d.tmax.minute + 4) // 5 * 5
    vals = [d.minute_series.get(m, 0) for m in range(start, end + 1)]
    vmax = max(vals) or 1
    peak_i = vals.index(max(vals))
    bars = "".join(
        f'<div class="tlbar{" pk" if i == peak_i else ""}{" nz" if v > 0 else ""}" style="height:{v/vmax*100:.1f}%"></div>'
        for i, v in enumerate(vals)
    )
    axis = "".join(f"<span>{m//60:02d}:{m%60:02d}</span>"
                   for m in range(start, end + 1) if m % 15 == 0)
    return bars, axis


def _gcol(v: int, vmax: int) -> str:
    t = (v / vmax) ** 0.5 if vmax else 0
    lo, hi = (122, 199, 150), (13, 84, 41)
    return f"rgb({int(lo[0]+(hi[0]-lo[0])*t)},{int(lo[1]+(hi[1]-lo[1])*t)},{int(lo[2]+(hi[2]-lo[2])*t)})"


def _centre_table(d, dtier=None) -> tuple[str, str]:
    rows = d.centre_stats[:22]
    is_count = d.mode == "count"
    sd = lambda s: f'<span class="sd" style="background:{_TIERCOL[_tier(s.longest_run_min, s.alerts, is_count)]}"></span>'
    if d.mode == "sustained":
        head = "<tr><th></th><th>Centre Code</th><th>Centre Name</th><th>District</th><th class='num'>Alerts</th><th class='num'>Detections</th><th class='num'>Longest Run</th></tr>"
        body = "".join(f"<tr><td class='rk'>{i+1}</td><td class='mono'>{sd(s)}{s.centre_code}</td><td>{s.centre_name[:32]}</td><td>{s.district}</td><td class='num'>{s.alerts:,}</td><td class='num'>{s.detections:,}</td><td class='num'>{s.longest_run_min} min</td></tr>" for i, s in enumerate(rows))
        note = "Centres ranked by sustained detections — distinct ~15-minute checkpoints showing the condition. Longest run is the longest unbroken stretch. Dot shows severity."
    elif d.mode == "sustained_count":
        head = "<tr><th></th><th>Centre Code</th><th>Centre Name</th><th>District</th><th class='num'>Alerts</th><th class='num'>Detections</th><th class='num'>Peak / 15 min</th></tr>"
        body = "".join(f"<tr><td class='rk'>{i+1}</td><td class='mono'>{sd(s)}{s.centre_code}</td><td>{s.centre_name[:32]}</td><td>{s.district}</td><td class='num'>{s.alerts:,}</td><td class='num'>{s.detections:,}</td><td class='num'>{s.peak_burst}</td></tr>" for i, s in enumerate(rows))
        note = "Centres ranked by sustained detections and by the most alerts within any 15-minute window. Dot shows severity."
    else:
        head = "<tr><th></th><th>Centre Code</th><th>Centre Name</th><th>District</th><th class='num'>Alerts</th></tr>"
        body = "".join(f"<tr><td class='rk'>{i+1}</td><td class='mono'>{sd(s)}{s.centre_code}</td><td>{s.centre_name[:38]}</td><td>{s.district}</td><td class='num'>{s.alerts:,}</td></tr>" for i, s in enumerate(rows))
        note = "Centres ranked by alert count. Dot shows severity."
    return f'<table class="ctbl"><thead>{head}</thead><tbody>{body}</tbody></table>', note


def _pages(d, thumbs: Path) -> str:
    is_count = d.mode == "count"
    sev = {"r": 0, "o": 0, "y": 0, "g": 0}
    dcnt: dict[str, list] = {}
    for s in d.centre_stats:
        t = _tier(s.longest_run_min, s.alerts, is_count)
        sev[t] += 1
        if s.district:
            a = dcnt.setdefault(s.district, [0, 0])
            a[0] += 1
            if t in ("r", "o"):
                a[1] += 1

    def dgrade(dist):
        tot, hv = dcnt.get(dist, [1, 0])
        sh = hv / tot if tot else 0
        return "r" if sh >= 0.5 else "o" if sh >= 0.3 else "y" if sh >= 0.12 else "g"

    foot = f'<div class="foot"><span>CamView AI</span><span>{d.exam.name} · {d.label} · {d.exam.exam_date:%d %B %Y}</span><span>{d.centres} centres · {d.districts} districts</span></div>'
    peak_hm, peak_v = _peak_window(d.minute_series)
    bars, axis = _timeline(d)
    maxd = max((n for _, n in d.districts_ranked), default=1) or 1
    dbars = "".join(f'<div class="rr"><span class="dn">{dist}</span><span class="tk"><span class="fl" style="width:{100*n/maxd:.1f}%;background:{_TIERCOL[dgrade(dist)]}"></span></span><span class="vn">{n:,}</span></div>' for dist, n in d.districts_ranked)
    donut = _sev_donut(sev)
    leg = "".join(f'<div class="lr"><span class="sw" style="background:{_TIERCOL[t]}"></span><span class="ln">{_TIERNAME[t]}</span> <span class="desc">{_TIERDESC[t]}</span><span class="lv">{sev[t]}</span><span class="lp">{round(100*sev[t]/(d.centres or 1))}%</span></div>' for t in ("r", "o", "y", "g"))
    sleg = "".join(f'<span class="s"><span class="sw" style="background:{_TIERCOL[t]}"></span>{_TIERNAME[t]}</span>' for t in ("r", "o", "y", "g"))
    table_html, note = _centre_table(d)
    dt = f"{d.exam.exam_date:%d %B %Y}"
    # evidence paginates -> total page count is fluid (12 frames per A4 page)
    EVCAP = 12
    ev = list(d.evidence)
    ev_chunks = [ev[i:i + EVCAP] for i in range(0, len(ev), EVCAP)] or [[]]
    TOT = 3 + len(ev_chunks)

    def _evcells(chunk):
        return "".join(
            f'<figure class="ev"><div class="imw"><img src="file://{_thumb(a.evidence_image, a.alarm_id.replace("-","_"), thumbs)}"></div>'
            f'<figcaption><b>{a.centre_code}</b> {a.centre_name[:28]}<br>'
            f'<span class="cm">{a.district} · {a.zone} · {R._ts(a.occurred_at)}</span><br>'
            f'<span class="ref">Ref {a.alarm_id}</span></figcaption></figure>' for a in chunk)

    ev_pages = ""
    for ci, chunk in enumerate(ev_chunks):
        sect = ("Evidence frames, in the order curated for this report. Referenced by Alarm ID."
                if ci == 0 else f"Evidence frames continued — {len(ev)} in total.")
        inner = f'<div class="gal">{_evcells(chunk)}</div>' if chunk \
            else '<div class="sect-d">No evidence frames linked for this modality.</div>'
        ev_pages += (f'<div class="page"><div class="rule"></div><div class="head"><div>'
                     f'<div class="eyebrow">{d.label} · evidence</div>'
                     f'<div class="htitle">Evidence Frames{"" if ci == 0 else " (cont.)"}</div></div>'
                     f'<div class="pg">Page {4 + ci} of {TOT}</div></div>'
                     f'<div class="sect-d">{sect}</div>{inner}{foot}</div>')

    return f"""<div class="page"><div class="rule"></div>
  <div class="brandrow"><img class="logo" src="file://{LOGO}"><span class="pg">Page 1 of {TOT}</span></div>
  <div class="eyebrow">{d.exam.name} · {d.label}</div>
  <div class="ctitle">{d.label}</div>
  <div class="csub">{d.exam.name} · Exam Code {d.exam.code} · {dt}</div>
  <div class="kstrip">
    <div class="k"><div class="n">{d.total:,}</div><div class="l">Total Alerts</div></div>
    <div class="k"><div class="n">{d.centres}</div><div class="l">Centres</div></div>
    <div class="k"><div class="n">{d.districts}</div><div class="l">Districts</div></div>
    <div class="k"><div class="n">{d.cameras}</div><div class="l">Cameras</div></div>
    <div class="k"><div class="n">{R._hm(d.tmin)}</div><div class="l">First Alert</div></div>
    <div class="k"><div class="n">{R._hm(d.tmax)}</div><div class="l">Last Alert</div></div>
  </div>
  <div class="summary">
    <div><div>{donut}</div><div class="dlab">of {d.centres} centres</div></div>
    <div class="leg">{leg}</div>
  </div>
  <div class="panel grow" style="margin-top:14px"><div class="cgraph-h"><span class="t">Alerts by minute · {R._hm(d.tmin)}–{R._hm(d.tmax)} IST</span><span class="t">Peak {peak_hm} — {peak_v} alerts</span></div><div class="tlchart">{bars}</div><div class="tlaxis">{axis}</div></div>
  {foot}</div>
<div class="page"><div class="rule"></div><div class="head"><div><div class="eyebrow">{d.label} · by district</div><div class="htitle">Alerts by District</div></div><div class="pg">Page 2 of {TOT}</div></div>
  <div class="sect-d">Districts ranked by alert count. Bar colour shows the share of the district's centres that are Critical or High severity.</div>
  <div class="panel grow"><div class="drank">{dbars}</div><div class="sleg">{sleg}</div></div>
  {foot}</div>
<div class="page"><div class="rule"></div><div class="head"><div><div class="eyebrow">{d.label} · by centre</div><div class="htitle">Centres ranked by severity</div></div><div class="pg">Page 3 of {TOT}</div></div>
  <div class="sect-d">{note}</div>{table_html}
  {foot}</div>
{ev_pages}"""


_DOC = '<!DOCTYPE html><html><head><meta charset="utf-8"><style>{css}</style></head><body>{body}</body></html>'


def build_html(d, thumbs: Path) -> str:
    return _DOC.format(css=CSS, body=_pages(d, thumbs))


def _spike(session, exam_id: int, code: str, days=None) -> dict | None:
    """Busiest (centre, 15-min window) for a modality — flags an anomalous burst
    where one centre dominated a single window, to annotate on the day-curve."""
    from collections import defaultdict
    rows = session.execute(
        select(Alert.centre_code, Alert.centre_name, Alert.occurred_at)
        .where(Alert.exam_id == exam_id, Alert.modality_code == code, Alert.occurred_at.is_not(None),
               *R.days_cond(days))
    ).all()
    if not rows:
        return None
    bycw, bywin, names = defaultdict(int), defaultdict(int), {}
    for cc, cn, ts in rows:
        b = (ts.hour * 60 + ts.minute) // 15 * 15
        bycw[(b, cc)] += 1
        bywin[b] += 1
        names[cc] = cn or cc
    (b, cc), cnt = max(bycw.items(), key=lambda kv: kv[1])
    wt = bywin[b]
    vals = sorted(bycw.values())
    med = vals[len(vals) // 2] or 1
    # one centre fired far more than a typical centre does in a 15-min window
    return {"min": b, "centre": names.get(cc, cc), "count": cnt, "win_total": wt,
            "anomalous": cnt >= 8 and cnt >= 3 * med}


def _cooccur(session, exam_id: int, sel_code: str, sel_label: str, days=None) -> dict | None:
    """Cross-modality co-occurrence: of the centres this model flagged
    Critical/High, how many were ALSO flagged Critical/High by each other model.
    Surfaces multi-problem centres ('not just unsupervised — also crowded')."""
    from .main import _modality_label
    codes = [m for (m,) in session.execute(
        select(Alert.modality_code).where(
            Alert.exam_id == exam_id, Alert.modality_code.notin_(["TP", "TO"]),
            *R.days_cond(days))
        .distinct()).all()]
    flagged: dict[str, set] = {}
    for c in codes:
        stats = R.centre_stats(session, exam_id, c, days)
        ic = R.SEVERITY_MODE.get(c, "count") == "count"
        flagged[c] = {s.centre_code for s in stats
                      if _tier(s.longest_run_min, s.alerts, ic) in ("r", "o")}
    base = flagged.get(sel_code, set())
    if not base:
        return None
    rows = []
    for c in codes:
        if c == sel_code:
            continue
        ov = len(base & flagged.get(c, set()))
        rows.append((_modality_label(c), ov, c))
    rows.sort(key=lambda r: -r[1])
    return {"base_label": sel_label, "base_n": len(base), "rows": rows}


def _centre_activity(session, exam_id: int, code: str, centre_codes: list[str], days=None) -> dict:
    """Per-centre × 15-min activity for the given centres -> {code: {bin: count}}.
    Feeds the centre×time plot (which centres fired when)."""
    from collections import defaultdict
    if not centre_codes:
        return {}
    rows = session.execute(
        select(Alert.centre_code, Alert.occurred_at).where(
            Alert.exam_id == exam_id, Alert.modality_code == code,
            Alert.centre_code.in_(centre_codes), Alert.occurred_at.is_not(None),
            *R.days_cond(days))).all()
    mat: dict = defaultdict(lambda: defaultdict(int))
    for cc, ts in rows:
        mat[cc][(ts.hour * 60 + ts.minute) // 15 * 15] += 1
    return {cc: dict(v) for cc, v in mat.items()}


def _geo_values(session, exam_id: int, code: str, days=None) -> dict:
    """State-qualified {(state, district): count} so the heat map resolves each
    district within its own state — no stray same-named district pulled from
    another state's geometry."""
    rows = session.execute(
        select(Alert.state, Alert.district, func.count(Alert.id)).where(
            Alert.exam_id == exam_id, Alert.modality_code == code, Alert.district != "",
            *R.days_cond(days))
        .group_by(Alert.state, Alert.district)).all()
    return {(st or "", dist): n for st, dist, n in rows}


def _subloc_values(session, exam_id: int, code: str, days=None) -> list[tuple[str, int]]:
    """Alert counts grouped by camera sub-location (the Excel 'Camera Sub Location'),
    heaviest first. Used for INM/CD, where WHERE inside the centre matters — a
    control-room hit reads very differently from a hall one."""
    rows = session.execute(
        select(Alert.zone, func.count(Alert.id)).where(
            Alert.exam_id == exam_id, Alert.modality_code == code, Alert.zone != "",
            *R.days_cond(days))
        .group_by(Alert.zone).order_by(func.count(Alert.id).desc())).all()
    return [(z, n) for z, n in rows]


_SEV_W = {"Critical": 4, "High": 3, "Medium": 2, "Low": 1}


def _geo_weighted(session, exam_id: int, codes: list[str]) -> dict:
    """Severity-weighted detection pressure per (state, district) across the
    selected models: each alert weighted Critical 4 / High 3 / Medium 2 / Low 1."""
    from collections import defaultdict
    rows = session.execute(
        select(Alert.state, Alert.district, Alert.severity, func.count(Alert.id)).where(
            Alert.exam_id == exam_id, Alert.modality_code.in_(codes), Alert.district != "")
        .group_by(Alert.state, Alert.district, Alert.severity)).all()
    out: dict = defaultdict(int)
    for st, dist, sev, nn in rows:
        out[(st or "", dist)] += _SEV_W.get(sev, 1) * nn
    return dict(out)


def _geo_plain(session, exam_id: int, codes: list[str], days=None) -> dict:
    """Plain alert count per (state, district) across the selected models — a
    directly measurable concentration, no severity weighting."""
    from collections import defaultdict
    rows = session.execute(
        select(Alert.state, Alert.district, func.count(Alert.id)).where(
            Alert.exam_id == exam_id, Alert.modality_code.in_(codes), Alert.district != "",
            *R.days_cond(days))
        .group_by(Alert.state, Alert.district)).all()
    out: dict = defaultdict(int)
    for st, dist, nn in rows:
        out[(st or "", dist)] += nn
    return dict(out)


def _timeline_rows(session, d, exam_id: int, code: str, n: int = 12, days=None) -> list[dict]:
    is_count = d.mode == "count"
    top = d.centre_stats[:n]
    act = _centre_activity(session, exam_id, code, [s.centre_code for s in top], days)
    return [{"name": s.centre_name or s.centre_code, "district": s.district,
             "act": act.get(s.centre_code, {}),
             "tier": _tier(s.longest_run_min, s.alerts, is_count)} for s in top]


def _profile(d) -> dict:
    """Compact, comparison-ready facts for one modality."""
    is_count = d.mode == "count"
    sev = {"r": 0, "o": 0, "y": 0, "g": 0}
    crit_codes: set[str] = set()
    for s in d.centre_stats:
        t = _tier(s.longest_run_min, s.alerts, is_count)
        sev[t] += 1
        if t == "r":
            crit_codes.add(s.centre_code)

    def metric(s):
        if d.mode == "sustained":
            return f"{s.longest_run_min} min"
        if d.mode == "sustained_count":
            return f"{s.peak_burst}/15m"
        return f"{s.alerts:,}"

    if d.minute_series:
        peak_hm, peak_v = _peak_window(d.minute_series)
    else:
        peak_hm, peak_v = "--", 0
    top = [{"code": s.centre_code, "name": s.centre_name, "district": s.district,
            "tier": _tier(s.longest_run_min, s.alerts, is_count), "metric": metric(s)}
           for s in d.centre_stats[:6]]

    # ranked bars for the modality dashboard, in this model's own metric
    def metric_n(s):
        if d.mode == "sustained":
            return s.longest_run_min
        if d.mode == "sustained_count":
            return s.peak_burst
        return s.alerts
    _ranked = sorted(d.centre_stats, key=metric_n, reverse=True)[:10]
    top_bars = [((s.centre_name or s.centre_code), metric_n(s),
                 _TIERCOL[_tier(s.longest_run_min, s.alerts, is_count)]) for s in _ranked]
    munit = " min" if d.mode == "sustained" else ("/15m" if d.mode == "sustained_count" else "")
    mlabel = "longest run" if d.mode == "sustained" else ("peak burst" if d.mode == "sustained_count" else "alerts")
    # per-district severe share -> bar colour (red->green by share Critical/High)
    dcnt: dict[str, list[int]] = {}
    for s in d.centre_stats:
        if s.district:
            t = _tier(s.longest_run_min, s.alerts, is_count)
            a = dcnt.setdefault(s.district, [0, 0]); a[0] += 1; a[1] += 1 if t in ("r", "o") else 0

    def dcol(name):
        tot, sv = dcnt.get(name, [1, 0]); sh = sv / tot if tot else 0
        return _TIERCOL["r"] if sh >= 0.5 else _TIERCOL["o"] if sh >= 0.3 else _TIERCOL["y"] if sh >= 0.12 else _TIERCOL["g"]
    dist_bars = [(name[:16], cnt, dcol(name)) for name, cnt in d.districts_ranked]

    return {
        "label": d.label, "total": d.total, "centres": d.centres, "districts": d.districts,
        "cameras": d.cameras, "win": f"{R._hm(d.tmin)}–{R._hm(d.tmax)}", "crit": sev["r"],
        "crit_codes": crit_codes,
        "mode": d.mode, "sev": sev, "dist": d.districts_ranked, "dist_bars": dist_bars,
        "dimlbl": "district", "series": d.minute_series,
        "geo": dict(d.districts_ranked),   # {district: count} -> heat map
        "tmin": R._hm(d.tmin), "tmax": R._hm(d.tmax),
        "tmin_m": (d.tmin.hour * 60 + d.tmin.minute) if d.tmin else None,
        "tmax_m": (d.tmax.hour * 60 + d.tmax.minute) if d.tmax else None,
        "peak_hm": peak_hm, "peak_v": peak_v,
        "centre_codes": {s.centre_code for s in d.centre_stats}, "top": top,
        "top_bars": top_bars, "metric_unit": munit, "metric_label": mlabel,
        "code": d.code,
    }


def _trunk_compliance(session, exam, code: str, d, days=None) -> dict | None:
    """Window-compliance for the secure box — BOTH checkpoints, always, so arrival
    and opening are shown consistently (opening = None when no Trunk-Open events).
    `kind` marks which checkpoint this page emphasises for the deviation chart."""
    from . import compliance as C
    devs = C.centre_deviations(session, exam, days)   # {centre: {arr,opn}}
    names = {s.centre_code: (s.centre_name or s.centre_code) for s in d.centre_stats}

    def summarise(k: str) -> dict | None:
        entries = [(cc, v[k]) for cc, v in devs.items() if v.get(k)]
        if not entries:
            return None
        gin = sum(1 for _, e in entries if e["cls"] == "in")
        late = sum(1 for _, e in entries if e["cls"] == "late")
        early = sum(1 for _, e in entries if e["cls"] == "early")
        total = len(entries)
        worst = sorted((x for x in entries if x[1]["cls"] != "in"), key=lambda x: -abs(x[1]["dev"]))[:10]
        return {"in": gin, "late": late, "early": early, "total": total,
                "pct": round(100 * gin / total) if total else 0,
                "win": entries[0][1]["window"],
                "worst": [(names.get(cc, cc), e["dev"], e["cls"]) for cc, e in worst]}

    arr, opn = summarise("arr"), summarise("opn")
    if not arr and not opn:
        return None
    return {"arr": arr, "opn": opn, "kind": "Opening" if code == "TO" else "Arrival"}


def _peak_window(minute_series: dict, span: int = 15) -> tuple:
    """Busiest `span`-minute window: (start_hm, count_in_window).

    Every modality page captions this "N alerts in the busiest 15 min", but the
    value used to be the count in the busiest single MINUTE — the argmax of
    minute_series. The two only agree when every alert in the window lands in one
    minute, which is why Camera Tampering (2 alerts, same minute) read correctly
    while Zone Intrusion (22 alerts across the morning) reported 2 instead of 9.

    Sliding sum over minute-of-day, so a window may start anywhere.
    """
    if not minute_series:
        return "--", 0
    lo, hi = min(minute_series), max(minute_series)
    best_start, best_n = lo, -1
    for start in range(lo, hi + 1):
        n = sum(minute_series.get(m, 0) for m in range(start, start + span))
        if n > best_n:
            best_start, best_n = start, n
    return f"{best_start//60:02d}:{best_start%60:02d}", best_n


def generate_combined_report_pdf(session: Session, exam_id: int, codes: list[str],
                                 labels: dict[str, str], days=None) -> Path:
    from . import comparison_report as CMP, event_report as EV
    ds = [R.gather(session, exam_id, c, labels.get(c, c), days=days) for c in codes]
    exam = ds[0].exam
    dt = f"{exam.exam_date:%d %B %Y}" if exam.exam_date else ""
    workdir = _settings.data_dir / "reportgen" / f"{exam_id}_combined_{'-'.join(codes)}"
    workdir.mkdir(parents=True, exist_ok=True)
    thumbs = workdir / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    profs = []
    for d, code in zip(ds, codes):
        P = _profile(d)
        P["spike"] = _spike(session, exam_id, code, days)
        P["compare"] = _cooccur(session, exam_id, code, labels.get(code, code), days)
        P["timeline_rows"] = _timeline_rows(session, d, exam_id, code, days=days)
        P["geo"] = _geo_values(session, exam_id, code, days)
        if code in ("INM", "CD"):
            P["subloc"] = _subloc_values(session, exam_id, code, days)
        if code in ("TP", "TO"):
            P["compliance"] = _trunk_compliance(session, exam, code, d, days)
        is_count = d.mode == "count"
        tiermap = {s.centre_code: _tier(s.longest_run_min, s.alerts, is_count) for s in d.centre_stats}
        frames = []
        for a in d.evidence[:6]:
            tp = _thumb(a.evidence_image, a.alarm_id.replace("-", "_"), thumbs)
            if not tp:
                continue
            frames.append({"img": tp, "tag": d.label[:18], "day": EV.TNAME[tiermap.get(a.centre_code, "g")],
                           "centre": a.centre_name or a.centre_code,
                           "loc": " · ".join(x for x in (a.district, a.zone) if x), "time": R._ts(a.occurred_at)})
        P["frames"] = frames
        profs.append(P)
    html_path = workdir / "combined.html"
    geo = _geo_plain(session, exam_id, codes, days)
    html_path.write_text(CMP.build(exam, profs, dt, geo=geo), encoding="utf-8")
    pdf_path = workdir / f"{exam.code}_Combined_{'-'.join(codes)}.pdf"
    return _render_pdf(html_path, pdf_path, timeout=180)

def generate_report_pdf(session: Session, exam_id: int, mcode: str, label: str,
                        photos: list[str] | None = None, days=None) -> Path:
    from . import event_report as EV
    d = R.gather(session, exam_id, mcode, label, photos=photos, days=days)
    P = _profile(d)
    P["spike"] = _spike(session, exam_id, mcode, days)
    P["compare"] = _cooccur(session, exam_id, mcode, label, days)
    P["timeline_rows"] = _timeline_rows(session, d, exam_id, mcode, days=days)
    P["geo"] = _geo_values(session, exam_id, mcode, days)
    if mcode in ("INM", "CD"):
        P["subloc"] = _subloc_values(session, exam_id, mcode, days)
    workdir = _settings.data_dir / "reportgen" / f"{exam_id}_{mcode}"
    thumbs = workdir / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    is_count = d.mode == "count"
    tiermap = {s.centre_code: _tier(s.longest_run_min, s.alerts, is_count) for s in d.centre_stats}
    frames = []
    for a in d.evidence:
        tp = _thumb(a.evidence_image, a.alarm_id.replace("-", "_"), thumbs)
        if not tp:
            continue
        t = tiermap.get(a.centre_code, "g")
        frames.append({"img": tp, "tag": label[:18], "day": EV.TNAME[t],
                       "centre": a.centre_name or a.centre_code,
                       "loc": " · ".join(x for x in (a.district, a.zone) if x), "time": R._ts(a.occurred_at)})
    dt = f"{d.exam.exam_date:%d %B %Y}" if d.exam.exam_date else ""
    html_path = workdir / "report.html"
    html_path.write_text(EV.build_event(d.exam, P, frames, dt), encoding="utf-8")
    safe = re.sub(r"[^A-Za-z0-9]+", "_", label).strip("_")
    pdf_path = workdir / f"{d.exam.code}_{safe}.pdf"
    return _render_pdf(html_path, pdf_path, timeout=120)


# ---------------- trunk compliance report (window archetype) ----------------
def _comp_evidence(session, exam_id, queue, thumbs, want: int = 6, only: list[str] | None = None, days=None):
    """Alert frames for the evidence page. `only` = an operator-curated alarm-id
    list (used verbatim, in order); otherwise the worst queued violations. `days`
    scopes the padding frames to the selected exam days (the queue is already scoped)."""
    qmap = {e["alarm"]: e for e in queue if e.get("alarm")}
    if only:
        order, want = list(only), len(only)
    else:
        order, seen = [], set()
        for e in queue:                       # off-window violations first
            if e.get("alarm") and e["code"] not in seen:
                seen.add(e["code"]); order.append(e["alarm"])
        if len(order) < want:                 # ...then representative box frames (so 100% exams still show evidence)
            reps = session.execute(
                select(Alert.alarm_id, Alert.modality_code).where(
                    Alert.exam_id == exam_id, Alert.modality_code.in_(["TP", "TO"]),
                    Alert.evidence_image != "", *R.days_cond(days)).order_by(Alert.occurred_at)
            ).all()
            tps = [a for a, m in reps if m == "TP"]   # arrivals
            tos = [a for a, m in reps if m == "TO"]   # openings
            from itertools import zip_longest
            mixed = [a for pair in zip_longest(tps, tos) for a in pair if a]   # alternate arrival/opening
            for alarm in mixed:
                if alarm not in order:
                    order.append(alarm)
                if len(order) >= want:
                    break
    if not order:
        return []
    rows = session.execute(
        select(Alert.alarm_id, Alert.evidence_image, Alert.centre_name, Alert.district,
               Alert.state, Alert.occurred_at, Alert.modality_code)
        .where(Alert.exam_id == exam_id, Alert.alarm_id.in_(order))
    ).all()
    amap = {r[0]: r for r in rows}
    out = []
    for alarm in order:
        if len(out) >= want:
            break
        r = amap.get(alarm)
        if not r or not r[1]:
            continue
        tp = _thumb(r[1], alarm.replace("-", "_"), thumbs)
        if not tp:
            continue
        e = qmap.get(alarm)
        if e:
            sgn = "+" if e["dev"] > 0 else "\u2212"
            tag, centre = f'{e["kind"]} {sgn}{abs(e["dev"])}m', e["centre"]
            loc, time = ", ".join(x for x in (e["district"].title(), e["state"].title()) if x), e["actual"]
        else:
            tag = "Box arrival" if r[6] == "TP" else "Box opening" if r[6] == "TO" else "Trunk"
            centre = r[2] or alarm
            loc = ", ".join(x for x in ((r[3] or "").title(), (r[4] or "").title()) if x)
            time = r[5].strftime("%H:%M:%S") if r[5] else ""
        out.append({"img": tp, "tag": tag, "centre": centre, "loc": loc, "time": time})
    return out


def generate_compliance_report_pdf(session: Session, exam_id: int,
                                   photos: list[str] | None = None, days=None) -> Path:
    from . import compliance as C, comp_report as CR
    from .models import OfficialCentre
    exam = session.get(Exam, exam_id)
    data = C.compute(session, exam, days)
    # roster coverage: centres in the official list whose secure box was NEVER
    # seen on camera (no Trunk-Placed/Opened alert at all) — a monitoring gap the
    # trunk data alone can't reveal, since it only holds centres that fired.
    roster = session.execute(
        select(OfficialCentre.centre_code, OfficialCentre.centre_name, OfficialCentre.district)
        .where(OfficialCentre.exam_id == exam_id)).all()
    tcodes = {r[0] for r in session.execute(
        select(Alert.centre_code).where(
            Alert.exam_id == exam_id, Alert.modality_code.in_(["TP", "TO"]),
            Alert.centre_code != "", *R.days_cond(days)).distinct()).all()}
    if roster:
        rcodes = {r[0] for r in roster}
        silent = [{"code": c, "name": n, "district": d} for c, n, d in roster if c not in tcodes]
        data["roster"] = {"total": len(rcodes), "reported": len(rcodes & tcodes),
                          "silentN": len(silent), "silent": silent}
    elif (exam.centre_total or 0) > 0:
        # operator-entered total, no per-centre list -> count only, silent unnamed
        data["roster"] = {"total": exam.centre_total, "reported": min(len(tcodes), exam.centre_total),
                          "silentN": max(0, exam.centre_total - len(tcodes)), "silent": []}
    workdir = _settings.data_dir / "reportgen" / f"{exam_id}_trunk"
    workdir.mkdir(parents=True, exist_ok=True)
    thumbs = workdir / "thumbs"
    thumbs.mkdir(parents=True, exist_ok=True)
    evidence = _comp_evidence(session, exam_id, data["queue"], thumbs, only=photos, days=days)
    # multi-day → a page per day (that day's shifts); compute each day on its own
    per_day = None
    if len(data.get("dates") or []) > 1:
        per_day = [(d.strftime("%d %B %Y"), C.compute(session, exam, [str(d)])) for d in data["dates"]]
    # total exam days (unfiltered) so a day-filtered report reads "2/3"
    total_days = session.scalar(
        select(func.count(func.distinct(func.date(Alert.occurred_at))))
        .where(Alert.exam_id == exam_id, Alert.occurred_at.is_not(None))) or len(data.get("dates") or [])
    # geographic heat map: shade districts by OFF-WINDOW box events (non-compliance);
    # if every box was compliant, fall back to box-sighting volume so the map still draws.
    from collections import Counter as _C
    offw = _C()
    for v in data["queue"]:
        offw[(v.get("state", ""), v.get("district") or "—")] += 1
    if offw:
        geo = {"values": dict(offw), "title": "Where box compliance issues concentrated",
               "cap": "Darker = more off-window box events (late arrivals + late/early openings)."}
    else:
        vol = session.execute(
            select(Alert.state, Alert.district, func.count(Alert.id)).where(
                Alert.exam_id == exam_id, Alert.modality_code.in_(["TP", "TO"]),
                Alert.district != "", *R.days_cond(days)).group_by(Alert.state, Alert.district)).all()
        geo = {"values": {(st, d): n for st, d, n in vol}, "title": "Where the secure box was tracked",
               "cap": "Every box arrival/opening was in window. Darker = more box sightings."} if vol else None
    html_path = workdir / "trunk.html"
    html_path.write_text(CR.build_body(exam, data, evidence, per_day=per_day, total_days=total_days, geo=geo), encoding="utf-8")
    pdf_path = workdir / f"{exam.code}_Secure_Box_Compliance.pdf"
    return _render_pdf(html_path, pdf_path, timeout=120)


# ---------------- district & centre drill-down reports ----------------
_TIER_LET = {0: "r", 1: "o", 2: "y", 3: "g"}


def _min_series(session, conds) -> dict:
    hm = func.strftime("%H:%M", Alert.occurred_at) if engine.dialect.name == "sqlite" \
        else func.to_char(Alert.occurred_at, "HH24:MI")
    ms = {}
    for s_hm, n in session.execute(select(hm, func.count(Alert.id)).where(*conds, Alert.occurred_at.is_not(None)).group_by(hm)).all():
        try:
            h, m = str(s_hm).split(":"); ms[int(h) * 60 + int(m)] = n
        except (ValueError, AttributeError):
            pass
    return ms


def _timeline_html(ms, tmin, tmax) -> str:
    if not ms or not tmin or not tmax:
        return '<div style="color:#aaa;font-size:11px">No timed alerts</div>'
    start = (tmin.hour * 60 + tmin.minute) // 5 * 5
    end = (tmax.hour * 60 + tmax.minute + 4) // 5 * 5
    vals = [ms.get(m, 0) for m in range(start, end + 1)]
    vmax = max(vals) or 1
    pk = vals.index(max(vals))
    bars = "".join(f'<div class="tlbar{" pk" if i == pk else ""}" style="height:{v/vmax*100:.1f}%"></div>' for i, v in enumerate(vals))
    axis = "".join(f"<span>{m//60:02d}:{m%60:02d}</span>" for m in range(start, end + 1) if m % 15 == 0)
    return f'<div class="tlchart">{bars}</div><div class="tlaxis">{axis}</div>'


def _merged_centres(session, exam_id, codes, district=None):
    cmap = {}
    for code in codes:
        is_count = R.SEVERITY_MODE.get(code) == "count"
        for s in R.centre_stats(session, exam_id, code):
            if district and s.district != district:
                continue
            c = cmap.setdefault(s.centre_code, {"code": s.centre_code, "name": s.centre_name, "district": s.district, "alerts": 0, "tr": 3, "run": 0, "det": 0})
            c["alerts"] += s.alerts
            c["run"] = max(c["run"], s.longest_run_min)
            c["det"] += s.detections
            c["tr"] = min(c["tr"], _TIERRANK[_tier(s.longest_run_min, s.alerts, is_count)])
    out = sorted(cmap.values(), key=lambda c: (c["tr"], -c["alerts"]))
    for c in out:
        c["tier"] = _TIER_LET[c["tr"]]
    return out


def _all_codes(session, exam_id, codes):
    if codes:
        return codes
    rows = session.execute(select(Alert.modality_code).where(Alert.exam_id == exam_id).distinct()).all()
    return [r[0] for r in rows if r[0] not in ("TP", "TO")] or [r[0] for r in rows]


def _label(code):
    from .registry import get_registry
    m = get_registry().by_code(code)
    return m.display_label if m else code


def generate_centre_report_pdf(session: Session, exam_id: int, centre: str, codes: list[str]) -> Path:
    exam = session.get(Exam, exam_id)
    codes = _all_codes(session, exam_id, codes)
    scope = _label(codes[0]) if len(codes) == 1 else f"{len(codes)} modalities"
    base = [Alert.exam_id == exam_id, Alert.centre_code == centre, Alert.modality_code.in_(codes)]
    info = session.execute(select(Alert.centre_name, Alert.district).where(*base).limit(1)).first()
    name, district = (info[0], info[1]) if info else (centre, "")
    total = session.scalar(select(func.count(Alert.id)).where(*base)) or 0
    cameras = session.scalar(select(func.count(func.distinct(Alert.camera_name))).where(*base)) or 0
    tmin = session.scalar(select(func.min(Alert.occurred_at)).where(*base))
    tmax = session.scalar(select(func.max(Alert.occurred_at)).where(*base))
    permod = session.execute(select(Alert.modality_code, func.count(Alert.id)).where(*base).group_by(Alert.modality_code).order_by(func.count(Alert.id).desc())).all()
    zones = session.execute(select(Alert.zone, func.count(Alert.id)).where(*base, Alert.zone != "").group_by(Alert.zone).order_by(func.count(Alert.id).desc())).all()
    ms = _min_series(session, base)
    alerts = list(session.scalars(select(Alert).where(*base).order_by(Alert.occurred_at.desc()).limit(36)))
    ev = [a for a in session.scalars(select(Alert).where(*base, Alert.evidence_image != "").order_by(Alert.occurred_at.desc()).limit(9))]

    workdir = _settings.data_dir / "reportgen" / f"{exam_id}_centre_{centre}"
    thumbs = workdir / "thumbs"; thumbs.mkdir(parents=True, exist_ok=True)
    mm = max((n for _, n in permod), default=1)
    modbars = "".join(f'<div class="rr"><span class="dn">{_label(c)}</span><span class="tk"><span class="fl" style="width:{100*n/mm:.0f}%;background:#1f7a3d"></span></span><span class="vn">{n:,}</span></div>' for c, n in permod)
    zlist = " · ".join(f"{z} ({n:,})" for z, n in zones[:4]) or "—"
    arows = "".join(f'<tr><td class="mono">{R._ts(a.occurred_at)}</td><td>{_label(a.modality_code)}</td><td>{a.zone}</td><td class="mono">{a.camera_name}</td><td class="mono" style="font-size:8.5px;color:#bbb">{a.alarm_id}</td></tr>' for a in alerts)
    cells = "".join(f'<figure class="ev"><div class="imw"><img src="file://{_thumb(a.evidence_image, a.alarm_id.replace("-","_"), thumbs)}"></div><figcaption><span class="cm">{a.zone} · {R._ts(a.occurred_at)}</span><br><span class="ref">Ref {a.alarm_id}</span></figcaption></figure>' for a in ev)
    dt = f"{exam.exam_date:%d %B %Y}" if exam.exam_date else ""
    foot = f'<div class="foot"><span>CamView AI</span><span>{exam.name} · Centre Dossier · {dt}</span><span>{centre} · {district}</span></div>'
    body = f"""<div class="page"><div class="rule"></div>
  <div class="brandrow"><img class="logo" src="file://{LOGO}"><span class="pg">Centre Dossier · 1 of 2</span></div>
  <div class="eyebrow">{exam.name} · {scope} · Centre Dossier</div>
  <div class="ctitle">{centre} · {name}</div>
  <div class="csub">{district} · Exam Code {exam.code} · {dt}</div>
  <div class="kstrip">
    <div class="k"><div class="n">{total:,}</div><div class="l">Total Alerts</div></div>
    <div class="k"><div class="n">{len(permod)}</div><div class="l">Modalities</div></div>
    <div class="k"><div class="n">{cameras}</div><div class="l">Cameras</div></div>
    <div class="k"><div class="n">{R._hm(tmin)}</div><div class="l">First Alert</div></div>
    <div class="k"><div class="n">{R._hm(tmax)}</div><div class="l">Last Alert</div></div>
  </div>
  <div class="summary" style="grid-template-columns:1fr"><div><div class="cgraph-h"><span class="t">Alerts by modality</span><span class="t">Zones: {zlist}</span></div>{modbars}</div></div>
  <div class="panel grow" style="margin-top:13px"><div class="cgraph-h"><span class="t">Alerts by minute · {R._hm(tmin)}–{R._hm(tmax)} IST</span></div>{_timeline_html(ms, tmin, tmax)}</div>
  {foot}</div>
<div class="page"><div class="rule"></div><div class="head"><div><div class="eyebrow">Centre Dossier · {centre}</div><div class="htitle">Recent Alerts &amp; Evidence</div></div><div class="pg">2 of 2</div></div>
  <div class="sect-d">Most recent {len(alerts)} alerts. Evidence frames referenced by Alarm ID.</div>
  <table class="ctbl"><thead><tr><th>Time</th><th>Modality</th><th>Zone</th><th>Camera</th><th>Alarm ID</th></tr></thead><tbody>{arows}</tbody></table>
  <div class="gal" style="margin-top:14px">{cells}</div>
  {foot}</div>"""
    hp = workdir / "centre.html"; hp.write_text(_DOC.format(css=CSS, body=body), encoding="utf-8")
    pdf = workdir / f"{exam.code}_Centre_{centre}.pdf"
    return _render_pdf(hp, pdf, timeout=120)


def generate_district_report_pdf(session: Session, exam_id: int, district: str, codes: list[str]) -> Path:
    exam = session.get(Exam, exam_id)
    codes = _all_codes(session, exam_id, codes)
    scope = _label(codes[0]) if len(codes) == 1 else f"{len(codes)} modalities"
    base = [Alert.exam_id == exam_id, Alert.district == district, Alert.modality_code.in_(codes)]
    total = session.scalar(select(func.count(Alert.id)).where(*base)) or 0
    cameras = session.scalar(select(func.count(func.distinct(Alert.camera_name))).where(*base)) or 0
    tmin = session.scalar(select(func.min(Alert.occurred_at)).where(*base))
    tmax = session.scalar(select(func.max(Alert.occurred_at)).where(*base))
    permod = session.execute(select(Alert.modality_code, func.count(Alert.id)).where(*base).group_by(Alert.modality_code).order_by(func.count(Alert.id).desc())).all()
    ms = _min_series(session, base)
    centres = _merged_centres(session, exam_id, codes, district)
    sev = {"r": 0, "o": 0, "y": 0, "g": 0}
    for c in centres:
        sev[c["tier"]] += 1
    ncen = len(centres)
    ev = [a for a in session.scalars(select(Alert).where(*base, Alert.evidence_image != "").order_by(Alert.occurred_at.desc()).limit(9))]

    workdir = _settings.data_dir / "reportgen" / f"{exam_id}_district_{district.replace(' ','_')}"
    thumbs = workdir / "thumbs"; thumbs.mkdir(parents=True, exist_ok=True)
    donut = _sev_donut(sev)
    leg = "".join(f'<div class="lr"><span class="sw" style="background:{_TIERCOL[t]}"></span><span class="ln">{_TIERNAME[t]}</span><span class="lv">{sev[t]}</span><span class="lp">{round(100*sev[t]/(ncen or 1))}%</span></div>' for t in ("r", "o", "y", "g"))
    mm = max((n for _, n in permod), default=1)
    modbars = "".join(f'<div class="rr"><span class="dn">{_label(c)}</span><span class="tk"><span class="fl" style="width:{100*n/mm:.0f}%;background:#1f7a3d"></span></span><span class="vn">{n:,}</span></div>' for c, n in permod)
    crows = "".join(f'<tr><td class="rk">{i+1}</td><td class="mono"><span class="sd" style="background:{_TIERCOL[c["tier"]]}"></span>{c["code"]}</td><td>{c["name"][:36]}</td><td class="num">{c["alerts"]:,}</td><td class="num">{c["det"]:,}</td><td class="num">{c["run"]} min</td></tr>' for i, c in enumerate(centres[:24]))
    cells = "".join(f'<figure class="ev"><div class="imw"><img src="file://{_thumb(a.evidence_image, a.alarm_id.replace("-","_"), thumbs)}"></div><figcaption><b>{a.centre_code}</b><br><span class="cm">{a.zone} · {R._ts(a.occurred_at)}</span></figcaption></figure>' for a in ev)
    dt = f"{exam.exam_date:%d %B %Y}" if exam.exam_date else ""
    foot = f'<div class="foot"><span>CamView AI</span><span>{exam.name} · District Report · {dt}</span><span>{district} · {ncen} centres</span></div>'
    body = f"""<div class="page"><div class="rule"></div>
  <div class="brandrow"><img class="logo" src="file://{LOGO}"><span class="pg">District Report · 1 of 2</span></div>
  <div class="eyebrow">{exam.name} · {scope} · District Report</div>
  <div class="ctitle">{district}</div>
  <div class="csub">Exam Code {exam.code} · {dt}</div>
  <div class="kstrip">
    <div class="k"><div class="n">{total:,}</div><div class="l">Total Alerts</div></div>
    <div class="k"><div class="n">{ncen}</div><div class="l">Centres</div></div>
    <div class="k"><div class="n">{cameras}</div><div class="l">Cameras</div></div>
    <div class="k"><div class="n">{R._hm(tmin)}</div><div class="l">First Alert</div></div>
    <div class="k"><div class="n">{R._hm(tmax)}</div><div class="l">Last Alert</div></div>
  </div>
  <div class="summary"><div><div>{donut}</div><div class="dlab">of {ncen} centres</div></div><div class="leg">{leg}</div></div>
  <div class="panel grow" style="margin-top:13px"><div class="cgraph-h"><span class="t">Alerts by minute · {R._hm(tmin)}–{R._hm(tmax)} IST</span></div>{_timeline_html(ms, tmin, tmax)}</div>
  {foot}</div>
<div class="page"><div class="rule"></div><div class="head"><div><div class="eyebrow">{district} · centres</div><div class="htitle">Centres ranked by severity</div></div><div class="pg">2 of 2</div></div>
  <div class="sect-d">Centres in {district}, worst-first. Dot shows severity. Evidence from the highest-severity centres.</div>
  <table class="ctbl"><thead><tr><th></th><th>Centre</th><th>Name</th><th class="num">Alerts</th><th class="num">Detections</th><th class="num">Longest Run</th></tr></thead><tbody>{crows}</tbody></table>
  <div class="gal" style="margin-top:14px">{cells}</div>
  {foot}</div>"""
    hp = workdir / "district.html"; hp.write_text(_DOC.format(css=CSS, body=body), encoding="utf-8")
    pdf = workdir / f"{exam.code}_District_{district.replace(' ','_')}.pdf"
    return _render_pdf(hp, pdf, timeout=120)
