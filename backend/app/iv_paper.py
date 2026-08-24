"""The Innovatiview house paper — the sheet every CamView report is printed on.

CamView is an Innovatiview product, so its reports carry the company's standard
document identity: a navy-tinted textured stock, a wire-bound edge down the
left, the gear mark from the wordmark as a watermark, a navy rule along the
foot, and the Innovatiview wordmark on every page. A4 landscape throughout, so
the same file prints as a report and presents as a deck.

WHY THIS IS ONE MODULE. `comp_report` owns the chrome for the whole report
family — `event_report` and `comparison_report` both import its CSS and its
`_page` wrapper. Replacing those two things here therefore re-skins every
report at once, without touching the report logic that builds the graphs.

OFFLINE. Fonts are bundled under assets/fonts and referenced through
assets/fonts.css. A Google Fonts link would silently degrade to a system face
on an air-gapped exam-centre machine, which is exactly where this runs.

The sheet silhouette (deckle edge + binding punches) is generated geometry, not
an image, so it stays crisp at any print resolution.
"""
from __future__ import annotations

import math
from functools import lru_cache
from pathlib import Path

from .settings import get_settings

_A = get_settings().assets_dir.resolve()

# ── sheet geometry, in millimetres on a 297 x 210 sheet ─────────────────────
W, H = 297.0, 210.0
HOLE, PITCH, CX, FIRST, RAD = 4.6, 10.4, 7.0, 8.4, 0.55

# The system: muted teal, warm sand. Identical to the portal, so a report and
# the screen it came from are recognisably one product.
TEAL = "#2A4343"     # the anchor: ink, rules, primary marks
TEAL2 = "#416B66"
PAPER = "#FBF9F5"    # cream sheet
SAND = "#F2EFE8"
INK = "#213843"
MUTED = "#5A6B6B"
FAINT = "#8C948E"
RULE = "#E0DACE"
SOFT = "#EFEBE2"
OK = "#4E8279"
FLAG = "#C4553F"     # the one warm accent, reserved for attention
NAVY = TEAL          # alias: the report modules still import NAVY


def _rrect(cx: float, cy: float, s: float, r: float) -> str:
    x, y = cx - s / 2, cy - s / 2
    return (f"M {x+r:.2f} {y:.2f} H {x+s-r:.2f} A {r} {r} 0 0 1 {x+s:.2f} {y+r:.2f} "
            f"V {y+s-r:.2f} A {r} {r} 0 0 1 {x+s-r:.2f} {y+s:.2f} H {x+r:.2f} "
            f"A {r} {r} 0 0 1 {x:.2f} {y+s-r:.2f} V {y+r:.2f} "
            f"A {r} {r} 0 0 1 {x+r:.2f} {y:.2f} Z")


@lru_cache(maxsize=1)
def geometry() -> tuple[str, str, str]:
    """(edge, sheet, ink) paths. `sheet` is the fillable silhouette with the
    punches subtracted; `ink` is what gets a hairline."""
    pts = []
    for i in range(91):
        y = H * i / 90
        x = 1.6 + 0.45 * math.sin(y * 0.42) + 0.28 * math.sin(y * 1.13 + 1.7)
        pts.append((round(x, 2), round(y, 2)))
    edge = "M {} {}".format(*pts[0]) + "".join(f" L {a} {b}" for a, b in pts[1:])
    holes, cy = [], FIRST
    while cy < H - 6:
        holes.append(_rrect(CX, cy, HOLE, RAD))
        cy += PITCH
    hd = " ".join(holes)
    return edge, f"{edge} L {W} {H} L {W} 0 Z {hd}", f"{edge} {hd}"


def _file_url(name: str) -> str:
    return (_A / name).resolve().as_uri()


@lru_cache(maxsize=1)
def _mask_uri() -> str:
    from urllib.parse import quote
    _, sheet, _ = geometry()
    svg = ("<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 297 210' "
           "preserveAspectRatio='none'><path fill='%23fff' fill-rule='evenodd' "
           f"d='{sheet}'/></svg>")
    return "data:image/svg+xml," + quote(svg, safe="'/:=<>%#.,- ")


@lru_cache(maxsize=1)
def _fonts_css() -> str:
    """The bundled @font-face rules, with relative URLs made absolute so the
    rendered HTML can live in a temp directory and still find the faces."""
    css = (_A / "fonts.css").read_text(encoding="utf-8")
    return css.replace('url("fonts/', f'url("{(_A / "fonts").resolve().as_uri()}/')


@lru_cache(maxsize=1)
def paper_css() -> str:
    """The chrome: page shell, stock, edge, watermark, footer and type tokens.
    Deliberately carries no component styling — the report modules keep their
    own tables, charts and cards."""
    return _fonts_css() + f"""
:root{{
  --navy:{NAVY};--paper:{PAPER};--ink:{INK};--muted:{MUTED};--faint:{FAINT};
  --rule:{RULE};--soft:{SOFT};--ok:{OK};--flag:{FLAG};
  --edge-ink:rgba(42,67,67,.24);--grain:.62;--mm:1mm;

  /* ── THE LOCKED TYPE SCALE ─────────────────────────────────────────
     Every report uses these and only these. A one-off size is how a
     family of documents stops looking like a family. Calibrated for A4
     landscape at 100%: body at 9.5pt/1.5 is the density a dense
     operational report needs without becoming a wall of text. */
  --t-display: 26pt;  --lh-display: 1.05;   /* cover title only       */
  --t-title:   17pt;  --lh-title:   1.08;   /* page title             */
  --t-head:    11pt;  --lh-head:    1.20;   /* section head           */
  --t-sub:      9pt;  --lh-sub:     1.35;   /* sub-head               */
  --t-body:   9.5pt;  --lh-body:    1.50;   /* running text           */
  --t-data:   8.5pt;  --lh-data:    1.40;   /* tables, figures        */
  --t-cap:    7.5pt;  --lh-cap:     1.35;   /* captions, footnotes    */
  --t-micro:  6.4pt;  --lh-micro:   1.20;   /* eyebrows, page numbers */
  --track-label: .16em;
  --track-tight: -.024em;

  /* ── THE LOCKED GRID ───────────────────────────────────────────────
     Twelve columns across the live area with a 4mm gutter, and a 4mm
     baseline unit for vertical rhythm. Every panel snaps to it, so two
     reports built months apart still line up with each other. */
  --gutter: 4mm;
  --unit:   4mm;
  --col: calc((297mm - 20mm - 13mm - 11 * var(--gutter)) / 12);
}}
*{{margin:0;padding:0;box-sizing:border-box;-webkit-print-color-adjust:exact;print-color-adjust:exact}}
@page{{size:297mm 210mm;margin:0}}
html,body{{background:#fff;color:var(--ink);
  font-family:"Archivo","Segoe UI",system-ui,sans-serif;
  font-size:var(--t-body);line-height:var(--lh-body);
  font-variant-numeric:tabular-nums}}

/* The grid, available to any report that lays out on it. */
.ivgrid{{display:grid;grid-template-columns:repeat(12,var(--col));gap:var(--gutter)}}
.c2{{grid-column:span 2}} .c3{{grid-column:span 3}} .c4{{grid-column:span 4}}
.c5{{grid-column:span 5}} .c6{{grid-column:span 6}} .c7{{grid-column:span 7}}
.c8{{grid-column:span 8}} .c9{{grid-column:span 9}} .c12{{grid-column:span 12}}
.u1{{margin-bottom:var(--unit)}} .u2{{margin-bottom:calc(2*var(--unit))}}
.u3{{margin-bottom:calc(3*var(--unit))}} .u4{{margin-bottom:calc(4*var(--unit))}}
.mono,.pn{{font-family:"IBMPlexMono",ui-monospace,Consolas,monospace}}

.page{{position:relative;width:297mm;height:210mm;overflow:hidden;
  display:flex;flex-direction:column;page-break-after:always;
  background-color:var(--paper);
  -webkit-mask-image:url("{_mask_uri()}");mask-image:url("{_mask_uri()}");
  -webkit-mask-size:100% 100%;mask-size:100% 100%;
  -webkit-mask-repeat:no-repeat;mask-repeat:no-repeat}}
.page:last-child{{page-break-after:auto}}

/* The stock: a seamless fibre tile plus page-wide formation. Plain alpha, no
   blend mode — mix-blend-mode drops out inside a mask and renders nothing. */
.page::before{{content:"";position:absolute;inset:0;z-index:0;pointer-events:none;
  opacity:var(--grain);
  background-image:url("{_file_url('paper-fibre.png')}"),url("{_file_url('paper-mottle.png')}");
  background-size:34mm 34mm,100% 100%;background-repeat:repeat,no-repeat}}

.ivedge{{position:absolute;inset:0;z-index:4;pointer-events:none}}
.ivedge svg{{width:100%;height:100%;display:block}}
.ivwm{{position:absolute;right:-30mm;bottom:-22mm;width:124mm;opacity:.075;z-index:0;pointer-events:none}}
.ivwm img{{width:100%;height:auto;display:block}}
.ivbase{{position:absolute;left:0;right:0;bottom:0;height:4mm;background:var(--navy);z-index:5}}
.ivlogo{{position:absolute;top:7mm;right:11mm;width:32mm;height:auto;z-index:5;opacity:.92}}

/* Page furniture. The header keeps comp_report's kick/title/page-number shape
   so no report module has to change its call. */
.ph{{position:relative;z-index:2;padding:9mm 13mm 3.5mm 20mm;
  border-bottom:.4mm solid var(--navy);
  display:flex;justify-content:space-between;align-items:flex-end;gap:8mm}}
.ph .kick{{font-family:"IBMPlexMono",monospace;font-size:var(--t-micro);letter-spacing:var(--track-label);
  text-transform:uppercase;color:var(--faint);margin-bottom:1.8mm;
  display:flex;align-items:center;gap:2.5mm}}
.ph .kick::before{{content:"";width:8mm;height:.4mm;background:var(--navy);flex:none}}
.ph .pt{{font-size:var(--t-title);font-weight:700;color:var(--navy);letter-spacing:-.024em;line-height:1.06}}
.ph .pn{{font-size:var(--t-micro);color:var(--faint);letter-spacing:.09em;
  text-transform:uppercase;white-space:nowrap;padding-bottom:1mm;margin-right:34mm}}
.pbody{{position:relative;z-index:2;flex:1;padding:5.5mm 13mm 5mm 20mm;overflow:hidden;min-height:0}}
.pf{{position:relative;z-index:5;display:flex;justify-content:space-between;align-items:center;
  font-family:"IBMPlexMono",monospace;font-size:var(--t-micro);letter-spacing:.09em;text-transform:uppercase;
  color:var(--faint);padding:0 13mm 7mm 20mm}}
"""


@lru_cache(maxsize=1)
def _furniture() -> str:
    _, sheet, ink = geometry()
    return (
        f'<div class="ivwm"><img src="{_file_url("iv-gear-watermark.svg")}" alt=""></div>'
        f'<img class="ivlogo" src="{_file_url("iv-logo-navy.png")}" alt="Innovatiview">'
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
