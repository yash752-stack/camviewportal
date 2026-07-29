"""State-aware India district choropleth.

Renders an SVG heatmap of district alert concentration from the bundled
all-India GeoJSON (759 districts, each tagged with its state). The map draws
only the states the exam's data actually spans and auto-fits to them, so a
single-state exam (UP) zooms to that state while a national exam (NEET) shows
its whole footprint — no per-exam hardcoding.

District names in exports carry spelling, suffix and renamed-district variants
(e.g. "Bengaluru- Urban", "Hyderabad/Secunderabad"), reconciled here to the
GeoJSON canonical names so values land on the right district.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

_GEO = Path(__file__).parent / "web" / "static" / "geo" / "india_districts.geojson"

# export spelling / renamed-district -> GeoJSON canonical (keys & values both
# in _norm form: lowercase, alnum-only). The bundled GeoJSON already uses
# several post-2011-census renamed names (e.g. Prayagraj, Ayodhya, Bengaluru
# Urban, Mysuru) rather than the pre-rename ones, so entries below are checked
# in BOTH directions: whichever spelling an export uses, the other one is
# tried too. That way it doesn't matter whether a given organisation's data
# still says "Allahabad" or has already switched to "Prayagraj".
_ALIAS_PAIRS = [
    ("bulandshahar", "bulandshahr"), ("chitrakut", "chitrakoot"), ("kanshiramnagar", "kasganj"),
    ("jyotibaphulenagar", "amroha"), ("lakhimpur", "lakhimpurkheri"), ("santravidasnagar", "bhadohi"),
    ("prayagraj", "allahabad"), ("ayodhya", "faizabad"), ("kanpur", "kanpurnagar"),
    ("bengalururural", "bangalorerural"), ("bengaluruurban", "bangaloreurban"),
    ("bengaluru", "bengaluruurban"), ("secunderabad", "hyderabad"), ("mysuru", "mysore"),
    ("mysurumysore", "mysuru"), ("kalaburagi", "gulbarga"), ("belagavi", "belgaum"),
    ("ballari", "bellary"), ("tumakuru", "tumkur"), ("shivamogga", "shimoga"),
    ("davangere", "davanagere"), ("chikkamagaluru", "chikmagalur"), ("kanchipuram", "kancheepuram"),
    ("noida", "gautambuddhanagar"), ("naugarh", "siddharthnagar"), ("bagalkot", "bagalkote"),
    ("ambikapur", "surguja"), ("nellore", "spsnellore"), ("itanagar", "papumpare"),
    ("hayathnagar", "rangareddy"), ("gudur", "spsnellore"), ("tirupathi", "chittoor"),
    ("machilipatnam", "krishna"), ("kakinada", "eastgodavari"), ("tadepalligudem", "westgodavari"),
    ("nandyal", "kurnool"), ("mangalagiri", "guntur"), ("rajahmundry", "eastgodavari"),
    # city/town name used in place of the formal district name
    ("guwahati", "kamrupmetropolitan"), ("hubli", "dharwad"), ("silchar", "cachar"),
    ("veraval", "girsomnath"), ("vyara", "tapi"), ("modasa", "aravalli"),
    ("mangaluru", "dakshinakannada"), ("mangalore", "dakshinakannada"),
    ("vijayawada", "krishna"), ("gooty", "anantapur"), ("kadapa", "ysrkadapa"),
    ("balasinor", "mahisagar"),
    # confirmed typos seen in real exports
    ("sahranpur", "saharanpur"), ("mahendergarh", "mahendragarh"),
    ("chikaballapur", "chikkaballapura"),
    # Telangana districts created in the 2016 reorganisation, carved out of
    # the ones named here -- the bundled GeoJSON only has the combined form
    ("gadwal", "jogulambagadwal"), ("kothagudem", "bhadradrikothagudem"),
    ("medchal", "medchalmalkajgiri"), ("janjgir", "janjgirchampa"),
    # "Warangal" alone is ambiguous post-2021 (split into Hanumakonda/Warangal);
    # best-effort default to the half that kept the name
    ("warangal", "warangalrural"),
    # confirmed against a second real exam's data: one-letter spelling variants
    # distinct from the ones already covered above
    ("gautambuddhnagar", "gautambuddhanagar"), ("sidharthnagar", "siddharthnagar"),
]
_ALIAS: dict[str, str] = {}
for _a, _b in _ALIAS_PAIRS:
    _ALIAS.setdefault(_a, _b)
    _ALIAS.setdefault(_b, _a)


def _norm(x: str) -> str:
    x = (x or "").lower().strip()
    for cut in ("/", "(", "["):       # drop suffixes like "/Secunderabad", "(Dist- …)"
        if cut in x:
            x = x.split(cut)[0]
    return "".join(ch for ch in x if ch.isalnum())


def _norm_variants(x: str) -> list[str]:
    """Every normalized candidate worth trying for a raw district string.

    Real exports aren't consistent about which side of a separator holds the
    canonical district name -- "Bhilai/Durg" needs the part AFTER the slash,
    "Hyderabad/Secunderabad" needs the part BEFORE it, and "Sasaram (Rohtas)"
    needs the part INSIDE the parens while "Mangaluru (Mangalore)" needs an
    alias for the part OUTSIDE them. Trying every side (in a stable order, so
    the first genuine match wins) handles all of these without needing to
    guess which convention a given export used."""
    x = (x or "").strip()
    variants = [x]
    for open_c, close_c in (("(", ")"), ("[", "]")):
        if open_c in x:
            before, _, rest = x.partition(open_c)
            inside = rest.split(close_c)[0] if close_c in rest else rest
            variants += [before, inside]
    if "/" in x:
        variants += x.split("/")
    out, seen = [], set()
    for v in variants:
        n = "".join(ch for ch in v.lower().strip() if ch.isalnum())
        if n and n not in seen:
            seen.add(n)
            out.append(n)
    return out


@lru_cache
def _load():
    try:
        gj = json.loads(_GEO.read_text())
    except (OSError, ValueError) as e:
        # Same failure class that's already hit other files on some machines
        # (antivirus quarantine is the usual cause) -- degrade instead of
        # crashing the map endpoint with an unhandled 500.
        import logging
        logging.getLogger("camview").error(f"Could not load {_GEO}: {e}. The map will render empty until this file is restored.")
        return [], {}, {}
    feats = []  # list of {district, state, nstate, ndist, polys}
    for f in gj["features"]:
        p = f["properties"]
        geom = f["geometry"]
        if not geom or not p.get("district") or not p.get("st_nm"):
            continue  # skip state-outline features that carry no district
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        feats.append({"district": p["district"], "state": p["st_nm"],
                      "nstate": _norm(p["st_nm"]), "ndist": _norm(p["district"]), "polys": polys})
    by_sd = {}            # (nstate, ndist) -> idx
    by_state: dict[str, list[int]] = {}
    for i, ft in enumerate(feats):
        by_sd[(ft["nstate"], ft["ndist"])] = i
        by_state.setdefault(ft["nstate"], []).append(i)
    return feats, by_sd, by_state


def _resolve(state: str, district: str) -> int | None:
    feats, by_sd, _ = _load()
    ns = _norm(state)
    variants = _norm_variants(district)
    # 1) direct match within the state, then 2) renamed-district/city alias -- for
    # every candidate segment of the raw string, not just the first
    for nd in variants:
        for cand in (nd, _ALIAS.get(nd)):
            if cand and (ns, cand) in by_sd:
                return by_sd[(ns, cand)]
    # 3) same district name in any state (state column missing / drifted)
    for nd in variants:
        for cand in (nd, _ALIAS.get(nd)):
            if not cand:
                continue
            for (s, d), i in by_sd.items():
                if d == cand:
                    return i
    return None


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _heat(value: int, vmax: int, light: bool = False) -> str:
    # same rose->brick hue family as the workspace; `light` swaps the base from
    # near-black (dark workspace) to near-white (printed report) so the heat map
    # carries the portal's colour framing onto a white page
    if light:
        if value <= 0:
            return "#eceef0"   # light neutral context fill
        stops = [(254, 226, 206), (236, 112, 70), (150, 32, 24)]   # warm sand -> orange -> deep brick
    else:
        if value <= 0:
            return "#241D1E"   # faint context fill so empty districts still read as a map
        stops = [(36, 29, 31), (120, 50, 62), (172, 56, 64)]  # muted grey -> dusky rose -> soft brick
    t = (value / vmax) ** 0.8 if vmax else 0   # gentler curve -> fewer districts glow bright
    if t <= 0.5:
        r, g, b = _lerp(stops[0], stops[1], t / 0.5)
    else:
        r, g, b = _lerp(stops[1], stops[2], (t - 0.5) / 0.5)
    return f"#{r:02x}{g:02x}{b:02x}"


def choropleth(values: dict, width: int = 820, height: int = 560,
               label_top: int = 6, pulse: int = 3, light: bool = False,
               fit_full: bool = False) -> str:
    """values: {(state, district): count}  ->  auto-fitted India choropleth SVG.

    Backwards compatible: a plain {district: count} dict still renders, matched
    against any state. `light=True` renders the print variant (light base, dark
    labels) for embedding in the white PDF reports.
    """
    stroke = "#d9dee3" if light else "#332829"
    lbl_fill = "#33404d" if light else "#B2A5A5"
    halo = "#ffffff" if light else "#13100F"
    mk_fill = "#C0392B" if light else "#E8535E"
    mk_txt = "#ffffff"
    dot_fill = "#7a8590" if light else "#F7F2F2"
    feats, _, by_state = _load()
    if not feats:
        # geojson failed to load (see _load) -- degrade to a labelled placeholder
        # instead of crashing on min()/max() of an empty point list below.
        msg = "Map data unavailable"
        return (f'<svg viewBox="0 0 820 200" width="100%" height="100%" preserveAspectRatio="xMidYMid meet">'
                f'<text x="410" y="100" fill="{lbl_fill}" font-size="16" text-anchor="middle" '
                f'font-family="IBM Plex Mono,monospace">{msg}</text></svg>')
    mapped: dict[int, int] = {}      # feature idx -> value
    label_of: dict[int, str] = {}    # feature idx -> data district label (for clicks)
    states: set[str] = set()   # geojson states the DATA explicitly names (drives what we draw)
    unmatched_n = 0     # alerts whose district isn't in the bundled geojson at all
    unmatched_districts: set[str] = set()
    for key, v in values.items():
        state, district = key if isinstance(key, tuple) else ("", key)
        ns = _norm(state)
        if ns in by_state:
            states.add(ns)
        idx = _resolve(state, district)
        if idx is None:
            unmatched_n += v
            unmatched_districts.add(f"{district} ({state})" if state else district)
            continue
        mapped[idx] = mapped.get(idx, 0) + v
        label_of[idx] = district
        if ns not in by_state:   # state name unknown -> fall back to the matched feature's state
            states.add(feats[idx]["nstate"])

    # which districts to draw: every district in the states the data touches
    draw = sorted({i for ns in states for i in by_state.get(ns, [])})
    if not draw:
        draw = list(range(len(feats)))
    vmax = max(mapped.values()) if mapped else 1

    # fit the view to where the DATA is (+ context margin), not the whole drawn
    # state — so a single-district exam zooms to that district instead of a big
    # empty silhouette. Surrounding districts still draw for context.
    # fit_full -> always frame the WHOLE drawn state(s), no matter where the data
    # falls; otherwise zoom to the data districts (+ context margin)
    focus = draw if fit_full else ([i for i in draw if mapped.get(i, 0) > 0] or draw)
    pts = [pt for i in focus for poly in feats[i]["polys"] for ring in poly for pt in ring]
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    minx, miny, maxx, maxy = min(lons), min(lats), max(lons), max(lats)
    cm, fl = (0.05, 0.3) if fit_full else (0.28, 0.4)
    ex = max((maxx - minx) * cm, fl)
    ey = max((maxy - miny) * cm, fl)
    minx, maxx, miny, maxy = minx - ex, maxx + ex, miny - ey, maxy + ey

    # tight viewBox that hugs the geography (longitude compressed by latitude),
    # so a compact state (UP) fills the panel just like a wide one (India)
    latc = math.cos(math.radians((miny + maxy) / 2)) or 1
    gw, gh = (maxx - minx) or 1, (maxy - miny) or 1
    TARGET = 1000.0
    scale = TARGET / max(gw * latc, gh)
    pad = TARGET * 0.03
    vbw, vbh = gw * latc * scale + 2 * pad, gh * scale + 2 * pad

    def proj(lon, lat):
        return pad + (lon - minx) * latc * scale, pad + (maxy - lat) * scale

    paths, centroids = [], []
    for i in draw:
        ft = feats[i]
        d = ""
        cx = cy = cn = 0
        for poly in ft["polys"]:
            for ring in poly:
                for j, pt in enumerate(ring):
                    x, y = proj(*pt)
                    d += f"{'M' if j == 0 else 'L'}{x:.1f},{y:.1f}"
                    cx += x; cy += y; cn += 1
                d += "Z"
        val = mapped.get(i, 0)
        name = label_of.get(i, ft["district"])
        # no <title>: the workspace renders a rich hover popover over each district
        paths.append(
            f'<path class="dpath" data-d="{name}" d="{d}" fill="{_heat(val, vmax, light)}" '
            f'stroke="{stroke}" stroke-width="0.5"/>')
        if val > 0 and cn:
            centroids.append((val, name, cx / cn, cy / cn))

    centroids.sort(reverse=True)
    # soft radial heat-glow halos on the hottest districts — the command-centre look
    glow = ""
    if not light and centroids:
        gmax = centroids[0][0] or 1
        base = max(vbw, vbh)
        rings = '<g pointer-events="none">' + "".join(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{base * (0.045 + (val / gmax) ** 0.5 * 0.105):.1f}" fill="url(#hotglow)"/>'
            for val, name, x, y in centroids[:10]) + '</g>'
        glow = ('<defs><radialGradient id="hotglow" cx="50%" cy="50%" r="50%">'
                '<stop offset="0%" stop-color="#FF6E55" stop-opacity="0.55"/>'
                '<stop offset="38%" stop-color="#F0463C" stop-opacity="0.20"/>'
                '<stop offset="100%" stop-color="#F0463C" stop-opacity="0"/>'
                '</radialGradient></defs>' + rings)
    labels = []
    mr = max(8.0, max(vbw, vbh) / 60)
    for k, (val, name, x, y) in enumerate(centroids[:label_top]):
        if k < pulse:
            anim = "" if light else (
                f'<animate attributeName="r" values="{mr:.1f};{mr*2.7:.1f}" dur="1.8s" repeatCount="indefinite" calcMode="spline" keySplines="0.2 0 0.4 1" keyTimes="0;1"/>'
                f'<animate attributeName="opacity" values="0.45;0" dur="1.8s" repeatCount="indefinite"/>')
            labels.append(
                f'<g pointer-events="none">'
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{mr:.1f}" fill="{mk_fill}" opacity="0.45">{anim}</circle>'
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{mr:.1f}" fill="{mk_fill}" stroke="{halo}" stroke-width="1"/>'
                f'<text x="{x:.1f}" y="{y:.1f}" fill="{mk_txt}" font-size="{mr*0.9:.1f}" font-weight="700" '
                f'font-family="IBM Plex Mono,monospace" text-anchor="middle" dominant-baseline="central">{val:,}</text>'
                f'<text x="{x:.1f}" y="{y + mr + 11:.1f}" fill="{lbl_fill}" font-size="10.5" text-anchor="middle" '
                f'font-family="IBM Plex Mono,monospace" style="paint-order:stroke;stroke:{halo};stroke-width:3px">{name}</text></g>')
        else:
            labels.append(
                f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3" fill="{dot_fill}" opacity="0.85" pointer-events="none"/>'
                f'<text x="{x + 6:.1f}" y="{y + 3:.1f}" fill="{lbl_fill}" font-size="10.5" pointer-events="none" '
                f'font-family="IBM Plex Mono,monospace" style="paint-order:stroke;stroke:{halo};stroke-width:3px">{name} {val:,}</text>')

    warn = ""
    if unmatched_n:
        wtxt = (f"{unmatched_n:,} alert{'s' if unmatched_n != 1 else ''} from "
                f"{len(unmatched_districts)} district{'s' if len(unmatched_districts) != 1 else ''} "
                f"not shown (not in this map's district data)")
        wy = vbh - 10
        warn = (f'<g><title>{"; ".join(sorted(unmatched_districts))}</title>'
                f'<text x="{pad:.1f}" y="{wy:.1f}" fill="{"#a3453c" if light else "#E8535E"}" font-size="11" '
                f'font-family="IBM Plex Mono,monospace">{wtxt}</text></g>')

    return (f'<svg viewBox="0 0 {vbw:.0f} {vbh:.0f}" width="100%" height="100%" '
            f'preserveAspectRatio="xMidYMid meet">'
            + "".join(paths) + glow + "".join(labels) + warn + "</svg>")


def resolve_name(district: str) -> str | None:
    """Legacy single-arg resolver kept for callers that pass a bare district."""
    idx = _resolve("", district)
    feats, _, _ = _load()
    return feats[idx]["district"] if idx is not None else None
