"""The Innovatiview house paper — the sheet every CamView report is printed on.

CamView is an Innovatiview product, so its reports carry the company's current
document standard (the "digest" edition, September 2026): a near-white textured
stock with a torn left edge and a punch rail, the gear mark from the wordmark as
a watermark, a red-then-navy band along the foot, the wordmark on every page,
Jost for titles and labels, Source Serif for reading text, IBM Plex Mono for
numbers. Three colours only: navy proves, grey is context, oxide red is the one
thing that matters on a page. A4 landscape throughout.

WHAT LIVES HERE. `comp_report` owns the component styling for the whole report
family — `event_report` and `comparison_report` both import its CSS and its
`_page` wrapper. The page shell, the cover, the full-page photographs that sit
between sections, the back page and the type tokens all come from this module,
so re-skinning it re-skins every report at once.

PHOTOGRAPHS. Free images from Wikimedia Commons under assets/photos, chosen to
read as CamView's world — the exam hall, the cameras on the ceiling, the
monitoring room, the review station — and printed as full-page navy duotones
between the analytical pages, the way the digest standard does. Credits are
printed on the back page.

CLIENT MARK. The cover carries the conducting body's own mark when one is
configured in assets/clients/clients.json, so the same report adapts to the
client: the Emblem of India beside the NTA mark for a National Testing Agency
exam, a state board's crest for a state board, nothing but the name otherwise.

OFFLINE. Fonts are bundled under assets/fonts and referenced through
assets/fonts.css. Photographs and marks are embedded as data URIs, so the
rendered HTML can live in a temp directory and still print.

SIZE. Chrome rasterises a CSS mask-image at 300 dpi on every page, so the torn
edge is a clip-path in pixels; the grain is one semi-transparent layer only.
"""
from __future__ import annotations

import base64
import io
import json
import math
import re
from functools import lru_cache
from pathlib import Path

from .settings import get_settings

_A = get_settings().assets_dir.resolve()

# ── sheet geometry, in millimetres on a 297 x 210 sheet ─────────────────────
W, H = 297.0, 210.0
HOLE, PITCH, CX, FIRST, RAD = 4.6, 10.4, 7.0, 8.4, 0.55
_PX = 96 / 25.4   # CSS px per mm

# The system: the digest standard's three colours.
NAVY = "#3B5877"     # the anchor: structure, rules, established evidence
NAVY2 = "#7189A4"    # the second tone
GREY, GREY2, GREY3 = "#8A97A6", "#B8C0CA", "#D5DAE0"
RED = "#B6403A"      # oxide red: the single accent
PAPER = "#FDFDFE"
SAND = "#F4F5F7"
INK = "#1E2A3D"
MUTED = "#5E6B7A"
FAINT = "#8B95A3"
RULE = "#D5DAE0"
SOFT = "#EEF1F4"
OK = NAVY
FLAG = RED
TEAL = TEAL2 = NAVY  # aliases: earlier report modules still import these


def _rrect(cx: float, cy: float, s: float, r: float) -> str:
    x, y = cx - s / 2, cy - s / 2
    return (f"M {x+r:.2f} {y:.2f} H {x+s-r:.2f} A {r:.2f} {r:.2f} 0 0 1 {x+s:.2f} {y+r:.2f} "
            f"V {y+s-r:.2f} A {r:.2f} {r:.2f} 0 0 1 {x+s-r:.2f} {y+s:.2f} H {x+r:.2f} "
            f"A {r:.2f} {r:.2f} 0 0 1 {x:.2f} {y+s-r:.2f} V {y+r:.2f} "
            f"A {r:.2f} {r:.2f} 0 0 1 {x+r:.2f} {y:.2f} Z")


@lru_cache(maxsize=4)
def geometry(k: float = 1.0) -> tuple[str, str, str]:
    """(edge, sheet, ink) paths in units of mm * k. `sheet` is the fillable
    silhouette with the punches subtracted; `ink` is what gets a hairline."""
    pts = []
    for i in range(91):
        y = H * i / 90
        x = 1.6 + 0.45 * math.sin(y * 0.42) + 0.28 * math.sin(y * 1.13 + 1.7)
        pts.append((round(x * k, 2), round(y * k, 2)))
    edge = "M {} {}".format(*pts[0]) + "".join(f" L {a} {b}" for a, b in pts[1:])
    holes, cy = [], FIRST
    while cy < H - 6:
        holes.append(_rrect(CX * k, cy * k, HOLE * k, RAD * k))
        cy += PITCH
    hd = " ".join(holes)
    return edge, f"{edge} L {W*k:.2f} {H*k:.2f} L {W*k:.2f} 0 Z {hd}", f"{edge} {hd}"


def _file_url(name: str) -> str:
    return (_A / name).resolve().as_uri()


def _b64(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode()


@lru_cache(maxsize=1)
def _fonts_css() -> str:
    """The bundled @font-face rules, with relative URLs made absolute so the
    rendered HTML can live in a temp directory and still find the faces."""
    css = (_A / "fonts.css").read_text(encoding="utf-8")
    return css.replace('url("fonts/', f'url("{(_A / "fonts").resolve().as_uri()}/')


@lru_cache(maxsize=2)
def _gear_uri(fill: str) -> str:
    """The gear mark as an SVG data URI in one flat colour (no CSS filter, which
    Chrome would rasterise)."""
    g = (_A / "iv-gear-watermark.svg").read_text(encoding="utf-8")
    g = re.sub(r"<\?xml[^>]*\?>", "", g).strip()
    g = re.sub(r'fill="#[0-9A-Fa-f]{6}"', f'fill="{fill}"', g)
    return "data:image/svg+xml;base64," + base64.b64encode(g.encode("utf-8")).decode()


@lru_cache(maxsize=1)
def _logo_b64() -> str:
    return _b64(_A / "iv-logo-navy.png")


# ── photographs ───────────────────────────────────────────────────────────────
PHOTOS = _A / "photos"


@lru_cache(maxsize=16)
def duotone_b64(path: str, maxpx: int = 1800, q: int = 78) -> str:
    """Desaturated base, navy-to-pale-grey duotone, navy multiply overlay, a
    little contrast, fine grain — the digest standard's photograph treatment."""
    from PIL import Image, ImageChops, ImageEnhance, ImageOps
    im = Image.open(path).convert("L")
    im.thumbnail((maxpx, maxpx))
    im = ImageEnhance.Contrast(im).enhance(1.15)
    im = ImageOps.colorize(im, (24, 52, 79), (221, 229, 235))
    navy = Image.new("RGB", im.size, (59, 88, 119))
    im = Image.blend(im, ImageChops.multiply(im, navy), 0.40)
    try:
        import numpy as np
        a = np.asarray(im).astype("int16")
        rng = np.random.default_rng(7)
        a = a + rng.integers(-9, 10, size=a.shape[:2])[:, :, None]
        im = Image.fromarray(a.clip(0, 255).astype("uint8"))
    except Exception:
        pass
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=q, optimize=True)
    return base64.b64encode(buf.getvalue()).decode()


def _photo_uri(key: str) -> str:
    p = PHOTOS / f"{key}.jpg"
    if not p.exists():
        return ""
    return "data:image/jpeg;base64," + duotone_b64(str(p))


@lru_cache(maxsize=1)
def photo_credits() -> dict:
    p = PHOTOS / "credits.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


# ── client marks ──────────────────────────────────────────────────────────────
CLIENTS = _A / "clients"


def _img_b64(p: Path, cls: str, alt: str) -> str:
    if not p or not p.exists():
        return ""
    mime = "image/svg+xml" if p.suffix.lower() == ".svg" else "image/png"
    return f'<img class="{cls}" src="data:{mime};base64,{_b64(p)}" alt="{alt}">'


def client_block(body: str, esc=str) -> str:
    """The 'Prepared for' block on the cover: the Emblem of India for a
    government body, the body's own mark when one is on file, then the name."""
    from . import clients as CL
    c = CL.find(body)
    if c:
        marks = ""
        if c["emblem"]:
            marks += _img_b64(CLIENTS / "emblem-of-india.svg", "emb", "Emblem of India")
        if c["mark_path"]:
            marks += _img_b64(c["mark_path"], "cmk", c["name"])
        line = c.get("line", "")
        return (f'<div class="cclient">{marks}<div class="cfor">Prepared for<br><b>{esc(c["name"])}</b>'
                + (f"<br>{esc(line)}" if line else "") + "</div></div>")
    if body:
        marks = _img_b64(CLIENTS / "emblem-of-india.svg", "emb", "Emblem of India") if CL.is_government(body) else ""
        return f'<div class="cclient">{marks}<div class="cfor">Prepared for<br><b>{esc(body)}</b></div></div>'
    return ""


# ── CSS ───────────────────────────────────────────────────────────────────────
@lru_cache(maxsize=1)
def paper_css() -> str:
    """The chrome: page shell, stock, edge, watermark, footer, cover, photo and
    back pages, and the type tokens. Deliberately carries no component styling
    — the report modules keep their own tables, charts and cards."""
    _, sheet_px, _ = geometry(_PX)
    return _fonts_css() + f"""
:root{{
  --navy:{NAVY};--navy2:{NAVY2};--paper:{PAPER};--ink:{INK};--muted:{MUTED};--faint:{FAINT};
  --rule:{RULE};--soft:{SOFT};--ok:{OK};--flag:{FLAG};--red:{RED};--grey:{GREY};--grey2:{GREY2};--grey3:{GREY3};
  --edge-ink:rgba(59,88,119,.26);--grain:.42;--mm:1mm;

  /* ── THE LOCKED TYPE SCALE (digest edition) ─────────────────────────
     Every report uses these and only these. Calibrated for A4 landscape
     at 100%: body at 9.5pt/1.5 is the density a dense operational report
     needs without becoming a wall of text. */
  --t-display: 26pt;  --lh-display: 1.05;   /* cover title only       */
  --t-title:   17pt;  --lh-title:   1.08;   /* page title             */
  --t-head:    11pt;  --lh-head:    1.20;   /* section head           */
  --t-sub:      9pt;  --lh-sub:     1.35;   /* sub-head               */
  --t-body:   9.5pt;  --lh-body:    1.50;   /* running text           */
  --t-data:   8.5pt;  --lh-data:    1.40;   /* tables, figures        */
  --t-cap:    7.5pt;  --lh-cap:     1.35;   /* captions, footnotes    */
  --t-micro:  6.4pt;  --lh-micro:   1.20;   /* eyebrows, page numbers */
  --track-label: .16em;
  --track-tight: -.018em;

  /* ── THE LOCKED GRID ───────────────────────────────────────────────
     Twelve columns across the live area with a 4mm gutter, and a 4mm
     baseline unit for vertical rhythm. */
  --gutter: 4mm;
  --unit:   4mm;
  --col: calc((297mm - 20mm - 13mm - 11 * var(--gutter)) / 12);
}}
*{{margin:0;padding:0;box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
@page{{size:297mm 210mm;margin:0}}
html,body{{background:#fff;color:var(--ink);
  font-family:"Jost","Segoe UI",system-ui,sans-serif;
  font-size:var(--t-body);line-height:var(--lh-body);
  font-variant-numeric:tabular-nums}}

.ivgrid{{display:grid;grid-template-columns:repeat(12,var(--col));gap:var(--gutter)}}
.c2{{grid-column:span 2}} .c3{{grid-column:span 3}} .c4{{grid-column:span 4}}
.c5{{grid-column:span 5}} .c6{{grid-column:span 6}} .c7{{grid-column:span 7}}
.c8{{grid-column:span 8}} .c9{{grid-column:span 9}} .c12{{grid-column:span 12}}
.u1{{margin-bottom:var(--unit)}} .u2{{margin-bottom:calc(2*var(--unit))}}
.u3{{margin-bottom:calc(3*var(--unit))}} .u4{{margin-bottom:calc(4*var(--unit))}}
.mono,.pn{{font-family:"IBMPlexMono",ui-monospace,Consolas,monospace}}
.serif{{font-family:"SourceSerif",Georgia,serif}}

.page{{position:relative;width:297mm;height:210mm;overflow:hidden;
  display:flex;flex-direction:column;page-break-after:always;
  background-color:var(--paper);
  clip-path:path(evenodd,"{sheet_px}")}}
.page:last-child{{page-break-after:auto}}

/* The stock: a seamless fibre tile plus page-wide formation, one faint layer. */
.page::before{{content:"";position:absolute;inset:0;z-index:0;pointer-events:none;
  opacity:var(--grain);
  background-image:url("{_file_url('paper-fibre.png')}"),url("{_file_url('paper-mottle.png')}");
  background-size:34mm 34mm,100% 100%;background-repeat:repeat,no-repeat}}

.ivedge{{position:absolute;inset:0;z-index:4;pointer-events:none}}
.ivedge svg{{width:100%;height:100%;display:block}}
/* the gear: bled off the bottom-right corner on every sheet */
.ivwm{{position:absolute;right:-28mm;bottom:-24mm;width:150mm;opacity:.07;z-index:0;pointer-events:none}}
.ivwm img{{width:100%;height:auto;display:block}}
.ivbase{{position:absolute;left:0;right:0;bottom:0;height:3mm;z-index:5;
  background:linear-gradient(90deg,{RED} 0 20mm,{NAVY} 20mm 100%)}}
.ivlogo{{position:absolute;top:8mm;right:11mm;width:34mm;height:auto;z-index:5}}

/* Page furniture. The header keeps comp_report's kick/title/page-number shape
   so no report module has to change its call. */
.ph{{position:relative;z-index:2;padding:9mm 13mm 3.5mm 20mm;
  border-bottom:.45mm solid var(--navy);
  display:flex;justify-content:space-between;align-items:flex-end;gap:8mm}}
.ph .kick{{font-family:"IBMPlexMono",monospace;font-size:var(--t-micro);letter-spacing:var(--track-label);
  text-transform:uppercase;color:var(--faint);margin-bottom:1.8mm;
  display:flex;align-items:center;gap:2.5mm}}
.ph .kick::before{{content:"";width:8mm;height:.5mm;background:var(--red);flex:none}}
.ph .pt{{font-size:var(--t-title);font-weight:700;color:var(--navy);letter-spacing:var(--track-tight);line-height:1.06}}
.ph .pn{{font-size:var(--t-micro);color:var(--faint);letter-spacing:.09em;
  text-transform:uppercase;white-space:nowrap;padding-bottom:1mm;margin-right:36mm}}
.pbody{{position:relative;z-index:2;flex:1;padding:5.5mm 13mm 5mm 20mm;overflow:hidden;min-height:0}}
.pf{{position:relative;z-index:5;display:flex;justify-content:space-between;align-items:center;
  font-family:"IBMPlexMono",monospace;font-size:var(--t-micro);letter-spacing:.09em;text-transform:uppercase;
  color:var(--faint);padding:0 13mm 7mm 20mm}}

/* ── cover ── */
.cov .ivlogo{{left:20mm;right:auto;top:11mm;width:42mm}}
.cov .cphoto{{position:absolute;left:47%;right:0;top:0;bottom:3mm;z-index:1;background-size:cover;background-position:center}}
.cov .ckick{{position:absolute;left:20mm;top:34mm;z-index:2;font-family:"IBMPlexMono",monospace;font-size:7pt;letter-spacing:.16em;text-transform:uppercase;color:var(--red)}}
.cov .ctitle{{position:absolute;left:20mm;top:42mm;width:38%;z-index:2;font-size:30pt;line-height:1.08;font-weight:700;color:var(--navy);letter-spacing:-.022em}}
.cov .csub{{position:absolute;left:20mm;top:104mm;width:38%;z-index:2;font-family:"SourceSerif",Georgia,serif;font-size:10.5pt;line-height:1.5;color:var(--ink)}}
.cov .cmeta{{position:absolute;left:20mm;top:136mm;width:38%;z-index:2;font-family:"IBMPlexMono",monospace;font-size:7.5pt;line-height:1.7;letter-spacing:.04em;color:var(--muted)}}
.cov .cclient{{position:absolute;left:20mm;bottom:20mm;width:40%;z-index:2;display:flex;align-items:center;gap:5mm}}
.cov .cclient .emb{{height:15mm;width:auto}}
.cov .cclient .cmk{{height:11mm;width:auto;max-width:34mm;object-fit:contain}}
.cov .cclient .cfor{{font-size:8pt;line-height:1.45;color:var(--ink);border-left:.4pt solid var(--rule);padding-left:5mm}}
.cov .cclient .cfor b{{color:var(--navy);font-size:9.5pt}}

/* ── full-page photograph between sections ── */
.photo{{background:var(--navy)}}
.photo .ph{{position:absolute;inset:0 0 3mm 0;z-index:1;background-size:cover;background-position:center;border:0;padding:0}}
.photo .gearov{{position:absolute;right:-22mm;bottom:-16mm;width:110mm;opacity:.22;z-index:2}}
.photo .pcap{{position:absolute;left:20mm;bottom:12mm;z-index:3;font-family:"IBMPlexMono",monospace;font-size:7pt;letter-spacing:.14em;text-transform:uppercase;color:rgba(255,255,255,.82)}}

/* ── back page ── */
.back .bmark{{position:absolute;left:0;right:0;top:78mm;text-align:center;z-index:2}}
.back .bmark img{{width:64mm}}
.back .btag{{position:absolute;left:0;right:0;top:104mm;text-align:center;font-size:8pt;letter-spacing:.32em;text-transform:uppercase;color:var(--red);z-index:2}}
.back .bcred{{position:absolute;left:20mm;right:70mm;bottom:14mm;z-index:2;font-size:6.5pt;line-height:1.45;color:var(--faint)}}
.back .bcred b{{color:var(--muted);font-weight:600}}
"""


@lru_cache(maxsize=1)
def _furniture() -> str:
    _, sheet, ink = geometry()
    return (
        f'<div class="ivwm"><img src="{_gear_uri(NAVY)}" alt=""></div>'
        f'<img class="ivlogo" src="data:image/png;base64,{_logo_b64()}" alt="Innovatiview">'
        f'<div class="ivedge"><svg viewBox="0 0 297 210" preserveAspectRatio="none">'
        f'<defs><clipPath id="ivclip" clipPathUnits="userSpaceOnUse">'
        f'<path d="{sheet}" clip-rule="evenodd"/></clipPath></defs>'
        f'<g clip-path="url(#ivclip)"><path d="{ink}" fill="none" '
        f'stroke="var(--edge-ink)" stroke-width="0.7"/></g></svg></div>'
        f'<div class="ivbase"></div>'
    )


def page(kick: str, title: str, n: int, total: int, body: str, foot: str, esc=str) -> str:
    """One sheet of the house paper.

    Signature matches comp_report._page exactly, so swapping it in re-skins the
    whole report family without a single call site changing.
    """
    return (f'<section class="page">{_furniture()}'
            f'<div class="ph"><div><div class="kick">{esc(kick)}</div>'
            f'<div class="pt">{esc(title)}</div></div>'
            f'<div class="pn">Page {n} of {total}</div></div>'
            f'<div class="pbody">{body}</div>{foot}</section>')


def cover(exam_name: str, kind: str, sub: str, meta_lines: list[str], body: str = "",
          photo: str = "cover", esc=str) -> str:
    """The cover: wordmark, a red eyebrow naming the report, the exam as the
    title, a serif subtitle, the run's facts in mono, the client block, and the
    CamView photograph as a navy duotone across the right of the sheet."""
    meta = "<br>".join(esc(m) for m in meta_lines if m)
    return (f'<section class="page cov">{_furniture()}'
            f'<div class="cphoto" style="background-image:url({_photo_uri(photo)})"></div>'
            f'<div class="ckick">CamView AI &middot; {esc(kind)}</div>'
            f'<div class="ctitle">{esc(exam_name)}</div>'
            f'<div class="csub">{esc(sub)}</div>'
            f'<div class="cmeta">{meta}</div>'
            f'{client_block(body, esc)}</section>')


def photo_page(key: str, caption: str = "") -> str:
    """One full-bleed duotone photograph, the gear faint in white over it."""
    uri = _photo_uri(key)
    if not uri:
        return ""
    cap = f'<div class="pcap">{caption}</div>' if caption else ""
    return (f'<section class="page photo"><div class="ph" style="background-image:url({uri})"></div>'
            f'<img class="gearov" src="{_gear_uri("#FFFFFF")}" alt="">{cap}<div class="ivbase"></div></section>')


def back_page(photo_keys: list[str]) -> str:
    cr = photo_credits()
    lines = []
    for k in photo_keys:
        c = cr.get(k)
        if c:
            lines.append(f'<b>{c["title"].replace("File:", "")}</b> — {c["artist"]}, {c["lic"]}, Wikimedia Commons')
    cred = ("Photographs, printed as navy duotones: " + "; ".join(lines) + ".") if lines else ""
    return (f'<section class="page back">{_furniture()}'
            f'<div class="bmark"><img src="data:image/png;base64,{_logo_b64()}" alt="Innovatiview"></div>'
            f'<div class="btag">Be Distinct</div>'
            f'<div class="bcred">{cred}</div></section>')


def document(css: str, pages: list[str], cover_html: str, photos: dict[int, str] | None = None,
             captions: dict[str, str] | None = None) -> str:
    """Assemble a report: cover, then the content pages with a full-page
    photograph inserted before each index listed in `photos` ({index: key}),
    then the back page carrying the photo credits."""
    photos = photos or {}
    captions = captions or {}
    out = [cover_html]
    used = []
    for i, p in enumerate(pages):
        k = photos.get(i)
        if k:
            out.append(photo_page(k, captions.get(k, "")))
            used.append(k)
        out.append(p)
    out.append(back_page(["cover"] + used))
    return (f'<!doctype html><html><head><meta charset="utf-8"><style>{css}</style></head>'
            f'<body>{"".join(out)}</body></html>')
