"""Convert the portal's dark stylesheets to the Innovatiview standard surface.

    python tools/relight.py --check     report what would change
    python tools/relight.py --apply     rewrite the stylesheets in place

WHY A SCRIPT. The UI carries ~290 hardcoded colours across app.css and
command.css. Re-typing them by hand guarantees drift: a few get missed, a few
get eyeballed slightly off, and the surface stops being one system. Mapping
them in OKLCH is reproducible and reviewable — rerun it and you get the same
answer.

THE MAPPING
  Neutrals (chroma < 0.035) are surfaces and inks. Their lightness is inverted
  onto a warm ramp: the darkest background becomes the lightest paper, and the
  brightest text becomes the darkest ink. The ramp carries a slight rose hue so
  the result reads as warm stock rather than grey.

  Chromatic colours keep their hue — a red must stay a red — but are re-seated
  for a light ground: lightness pulled down into a band that has real contrast
  against paper, chroma eased so nothing shouts.

  A short OVERRIDES table pins the colours that carry meaning (severity, the
  brand navy) to the validated Innovatiview values rather than a computed
  approximation.
"""
from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = [ROOT / "backend/app/web/static/app.css",
           ROOT / "backend/app/web/static/command.css"]

# ── THE SYSTEM: muted teal, warm sand ──────────────────────────────────────
#
# One philosophy, committed to. A deep slate-teal anchors everything — ink,
# primary action, the map's deep end — and a single warm accent (terracotta)
# carries whatever needs attention. Surfaces are sand and cream, not grey.
#
# Two things this buys: warm and cool never fight, because warmth lives in the
# paper and coolness in the ink; and it does not look like every other
# blue-grey product, which was the risk with the previous palette.
#
# INK IS TEAL, NOT BLACK. #213843 on sand reads softer than a true black while
# still landing near 12:1 — the contrast is there, the harshness is not.
PAPER_HUE = 72.0          # sand, not grey
PAPER_CHROMA = 0.014

# (inverted lightness) -> (new lightness)
_ANCHORS = [(0.00, 0.285), (0.08, 0.330), (0.30, 0.470), (0.50, 0.605),
            (0.66, 0.845), (0.78, 0.930), (0.86, 0.960), (1.00, 0.978)]


def _curve(x: float) -> float:
    for (x0, y0), (x1, y1) in zip(_ANCHORS, _ANCHORS[1:]):
        if x <= x1:
            t = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return _ANCHORS[-1][1]


OVERRIDES = {
    # surfaces: pinned, because elevation must not invert. A raised card has to
    # be lighter than the page; a straight inversion makes it darker, which is
    # what produced muddy card footers earlier.
    "#0b0d12": "#F2EFE8",   # page ground, warm sand
    "#0c1117": "#EFEBE2",
    "#0d1116": "#EFEBE2",
    "#0f1217": "#F7F4ED",   # topbar / rail
    "#14171e": "#FBF9F5",   # panel, cream
    "#161a21": "#F9F6F0",
    "#1b1f27": "#FFFFFF",   # panel, alternate
    "#232831": "#FFFFFF",   # raised
    "#262b34": "#E0DACE",   # border — borders DO invert
    "#1a1e25": "#EBE6DB",
    "#273040": "#D3CBBB",
    # ink: deep slate-teal
    "#e6e8ec": "#213843", "#dde3ea": "#2A4343", "#e7ecf2": "#2A4343",
    "#d6dbe2": "#38504F", "#9097a3": "#5A6B6B", "#8a93a0": "#68766F",
    "#646b78": "#8C948E", "#454c58": "#A9AEA2",
    # primary action / brand
    "#e8535e": "#2A4343", "#e0555a": "#2A4343", "#f5848c": "#416B66",
    "#7a2532": "#CBD8D2",
    "#243049": "#2A4343", "#2c3b57": "#38534F", "#3c5078": "#416B66",
    "#c8daf4": "#FFFFFF",
    # severity: the warm accent alarms, teal reassures
    "#d85c63": "#C4553F", "#e08a90": "#A8463F",
    "#db8a50": "#C07A46", "#dd9f6e": "#A87148",
    "#d2b65a": "#A8955C", "#dbc97d": "#95854F",
    "#5baa7c": "#4E8279", "#77c39a": "#5C9188",
}


# ── colour maths (OKLab / OKLCH) ────────────────────────────────────────────
def _s2l(c): return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
def _l2s(c):
    c = min(1.0, max(0.0, c))
    return 12.92 * c if c <= 0.0031308 else 1.055 * c ** (1 / 2.4) - 0.055


def hex_to_oklch(h: str):
    h = h.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (_s2l(int(h[i:i + 2], 16) / 255) for i in (0, 2, 4))
    l = (0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b) ** (1 / 3)
    m = (0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b) ** (1 / 3)
    s = (0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b) ** (1 / 3)
    L = 0.2104542553 * l + 0.7936177850 * m - 0.0040720468 * s
    A = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s
    B = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s
    return L, math.hypot(A, B), (math.degrees(math.atan2(B, A)) + 360) % 360


def oklch_to_hex(L, C, hdeg):
    hr = math.radians(hdeg)
    a, b = C * math.cos(hr), C * math.sin(hr)
    l_ = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3
    m_ = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3
    s_ = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3
    r = 4.0767416621 * l_ - 3.3077115913 * m_ + 0.2309699292 * s_
    g = -1.2684380046 * l_ + 2.6097574011 * m_ - 0.3413193965 * s_
    bb = -0.0041960863 * l_ - 0.7034186147 * m_ + 1.7076147010 * s_
    return "#" + "".join(f"{round(_l2s(v) * 255):02X}" for v in (r, g, bb))


# (inverted lightness) -> (new lightness). Backgrounds open out to paper,
# inks land dark, mid-tones keep their spacing.
# Pastel surface: nothing is allowed to be black. The darkest ink sits at
# L 0.44, which still clears WCAG AA (about 4.6:1) against the paper — go any
# lighter and body text stops being legible, which is the one thing a report
# interface cannot trade away. Secondary and tertiary inks are softer again.
_ANCHORS = [(0.00, 0.435), (0.08, 0.455), (0.30, 0.545), (0.50, 0.655),
            (0.66, 0.855), (0.78, 0.940), (0.86, 0.972), (1.00, 0.988)]


def _curve(x: float) -> float:
    for (x0, y0), (x1, y1) in zip(_ANCHORS, _ANCHORS[1:]):
        if x <= x1:
            t = 0.0 if x1 == x0 else (x - x0) / (x1 - x0)
            return y0 + t * (y1 - y0)
    return _ANCHORS[-1][1]


def convert(hexcode: str) -> str:
    key = hexcode.lower()
    if len(key) == 4:
        key = "#" + "".join(c * 2 for c in key[1:])
    if key in OVERRIDES:
        return OVERRIDES[key]

    L, C, h = hex_to_oklch(key)

    if C < 0.035:
        # A surface or an ink. A straight inversion will not do: the dark UI
        # packs every background into L 0.14-0.30 and every text colour into
        # L 0.45-0.92, so inverting linearly lands the page background at a
        # muddy 0.84 and leaves the surfaces barely separable. This curve is
        # anchored so the backgrounds open out to near-paper while the inks
        # stay genuinely dark, and the mid-tones keep their spacing.
        nl = _curve(1.0 - L)
        # warmth rises toward the paper end; ink stays close to neutral so it
        # does not read as brown
        # inks carry MORE colour than the paper here — a soft mauve-taupe
        # rather than grey is what makes the surface read as pastel
        t = max(0.0, min(1.0, (nl - 0.435) / 0.553))
        c = PAPER_CHROMA * (1.0 - 0.55 * t)
        return oklch_to_hex(nl, c, PAPER_HUE)

    # chromatic: keep the hue, re-seat it soft. Chroma is capped well below
    # the source so nothing shouts off the page.
    nl = max(0.55, min(0.66, 1.06 - L))
    nc = min(C * 0.55, 0.095)
    return oklch_to_hex(nl, nc, h)


HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")


def main(apply: bool) -> None:
    total, table = 0, {}
    for path in TARGETS:
        src = path.read_text(encoding="utf-8")
        found = [m for m in HEX.findall(src) if len(m) in (4, 7)]
        for f in found:
            table.setdefault(f.lower(), convert(f))
        out = HEX.sub(lambda m: convert(m.group(0)) if len(m.group(0)) in (4, 7) else m.group(0), src)
        total += len(found)
        if apply:
            path.with_suffix(path.suffix + ".dark-backup").write_text(src, encoding="utf-8")
            path.write_text(out, encoding="utf-8")

    items = sorted(table.items(), key=lambda kv: hex_to_oklch(kv[0])[0])
    print(f"\n  {total} colour references · {len(table)} distinct\n")
    print(f"  {'from':<10}{'to':<10}  L(before) -> L(after)")
    for a, b in items:
        la, _, _ = hex_to_oklch(a)
        lb, _, _ = hex_to_oklch(b)
        pin = "  (pinned)" if a in OVERRIDES else ""
        print(f"  {a:<10}{b:<10}   {la:.2f}  ->  {lb:.2f}{pin}")
    print(f"\n  {'APPLIED (originals kept as *.dark-backup)' if apply else 'dry run — pass --apply to write'}\n")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--check", action="store_true")
    main(ap.parse_args().apply)
