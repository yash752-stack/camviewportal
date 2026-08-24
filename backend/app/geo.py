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

_GEODIR = Path(__file__).parent / "web" / "static" / "geo"
_GEO = _GEODIR / "india_districts.geojson"


@lru_cache
def _detail_sources() -> dict[str, Path]:
    """State -> a higher-resolution district file, if one is bundled.

    The national file is heavily simplified (~31 points per district, and as
    few as 14 for a small one like Gautam Buddha Nagar), which is fine for a
    country-scale choropleth and useless when the data is one district. Any
    `<something>_districts.geojson` sitting beside it is treated as a detail
    source and keyed by the state it actually contains, so dropping in a new
    state's file is all it takes to light that state up -- no code change.
    """
    out: dict[str, Path] = {}
    for p in sorted(_GEODIR.glob("*_districts.geojson")):
        if p.name == _GEO.name or p.stat().st_size < 1024:
            continue
        try:
            gj = json.loads(p.read_text())
            names = {f["properties"].get("st_nm") for f in gj.get("features", [])}
            names.discard(None)
        except (OSError, ValueError, KeyError):
            continue
        if len(names) == 1:
            out[_norm(names.pop())] = p
    return out

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
def _load(src: str = ""):
    """Load a district source. `src` is a normalised state name for a detail
    file, or "" for the bundled national file."""
    path = _detail_sources().get(src, _GEO) if src else _GEO
    try:
        gj = json.loads(path.read_text())
    except (OSError, ValueError) as e:
        # Same failure class that's already hit other files on some machines
        # (antivirus quarantine is the usual cause) -- degrade instead of
        # crashing the map endpoint with an unhandled 500.
        import logging
        logging.getLogger("camview").error(f"Could not load {path}: {e}. The map will render empty until this file is restored.")
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


def _resolve(state: str, district: str, src: str = "") -> int | None:
    feats, by_sd, _ = _load(src)
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


# value -> colour ramp, light variant. Single source of truth: _heat() paints
# the map from these and ramp_css() paints the legend from the same list, so
# the two cannot disagree again.
_LIGHT_ZERO = "#EDE3D2"
_LIGHT_STOPS = [(246, 219, 210), (220, 161, 138), (201, 115, 95),
                (165, 82, 66), (117, 59, 48)]
_GAMMA = 0.62


def ramp_css() -> str:
    """CSS gradient stops for a legend that reads left=0 -> right=max.

    _heat applies t = (v/vmax) ** _GAMMA before picking a colour, so colour i
    sits at value (i/n) ** (1/_GAMMA), not at i/n. Spacing the legend evenly
    would overstate how much of the range the pale end covers."""
    n = len(_LIGHT_STOPS) - 1
    out = []
    for i, (r, g, b) in enumerate(_LIGHT_STOPS):
        pos = (i / n) ** (1 / _GAMMA) * 100
        out.append(f"#{r:02x}{g:02x}{b:02x} {pos:.1f}%")
    return ", ".join(out)


def _lerp(a, b, t):
    return tuple(round(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _heat(value: int, vmax: int, light: bool = False) -> str:
    # same rose->brick hue family as the workspace; `light` swaps the base from
    # near-black (dark workspace) to near-white (printed report) so the heat map
    # carries the portal's colour framing onto a white page
    if light:
        if value <= 0:
            # Land, NOT the page. Setting this to the panel colour made the
            # country vanish and left the busy districts floating as
            # disconnected blobs — a map has to read as a map before it reads
            # as data.
            return _LIGHT_ZERO
        # A blue-violet sequential ramp: one hue family, pale to deep, four
        # stops so the mid-range separates instead of banding. Terracotta was
        # doing an alarm's job on a page that already reports criticality in
        # numbers — the map's job is magnitude, and magnitude reads better cool.
        # Dusty slate-blue. The previous set was already cool but still
        # saturated enough to draw the eye district by district; chroma is
        # pulled down here so the map reads as one calm field with depth,
        # and the eye goes to the shape rather than to individual cells.
        # Sequential in the application's own brand hue (APP_PALETTE.md):
        # accent tint -> secondary terracotta -> primary -> dark accent. Five
        # stops so the mid-range separates instead of banding into one wash.
        stops = _LIGHT_STOPS
    else:
        if value <= 0:
            return "#241D1E"   # faint context fill so empty districts still read as a map
        stops = [(36, 29, 31), (120, 50, 62), (172, 56, 64)]  # muted grey -> dusky rose -> soft brick
    t = (value / vmax) ** _GAMMA if vmax else 0   # most districts sit low; spend
    # more of the ramp down there so the quiet ones still separate from each other
    n = len(stops) - 1
    seg = min(int(t * n), n - 1)
    r, g, b = _lerp(stops[seg], stops[seg + 1], (t * n) - seg)
    return f"#{r:02x}{g:02x}{b:02x}"


def choropleth(values: dict, width: int = 820, height: int = 560,
               label_top: int = 6, pulse: int = 3, light: bool = False,
               fit_full: bool = False) -> str:
    """values: {(state, district): count}  ->  auto-fitted India choropleth SVG.

    Backwards compatible: a plain {district: count} dict still renders, matched
    against any state. `light=True` renders the print variant (light base, dark
    labels) for embedding in the white PDF reports.
    """
    # White hairlines, not grey. Districts read as pieces of cut paper laid
    # on the page rather than cells in a grid — it is what makes a choropleth
    # look made rather than plotted.
    stroke = "#FBF6EC" if light else "#332829"
    lbl_fill = "#4A4239" if light else "#B2A5A5"
    halo = "#FBF6EC" if light else "#13100F"
    mk_fill = "#A55242" if light else "#E8535E"
    mk_txt = "#ffffff"
    dot_fill = "#8A7F6D" if light else "#F7F2F2"
    def _survey(src: str):
        """Resolve every data key against one source. Returns what matched."""
        fts, _sd, bstate = _load(src)
        mp: dict[int, int] = {}
        lbl: dict[int, str] = {}
        sts: set[str] = set()
        un_n = 0
        un_d: set[str] = set()
        for key, v in values.items():
            state, district = key if isinstance(key, tuple) else ("", key)
            ns = _norm(state)
            if ns in bstate:
                sts.add(ns)
            idx = _resolve(state, district, src)
            if idx is None:
                un_n += v
                un_d.add(f"{district} ({state})" if state else district)
                continue
            mp[idx] = mp.get(idx, 0) + v
            lbl[idx] = district
            if ns not in bstate:
                sts.add(fts[idx]["nstate"])
        return fts, bstate, mp, lbl, sts, un_n, un_d

    feats, by_state, mapped, label_of, states, unmatched_n, unmatched_districts = _survey("")
    if not feats:
        # geojson failed to load (see _load) -- degrade to a labelled placeholder
        # instead of crashing on min()/max() of an empty point list below.
        msg = "Map data unavailable"
        return (f'<svg viewBox="0 0 820 200" width="100%" height="100%" preserveAspectRatio="xMidYMid meet">'
                f'<text x="410" y="100" fill="{lbl_fill}" font-size="16" text-anchor="middle" '
                f'font-family="IBM Plex Mono,monospace">{msg}</text></svg>')

    # SCOPE, read off the data rather than configured per exam:
    #   national -> the exam spans more than one state
    #   state    -> many districts inside one state
    #   district -> a single district carries the exam
    # A one-state exam re-renders from that state's detail file when one is
    # bundled, because the national outline is far too coarse to zoom into.
    if len(states) == 1:
        only = next(iter(states))
        if only in _detail_sources():
            d_feats, d_by_state, d_mapped, d_label, d_states, d_un, d_und = _survey(only)
            if d_feats and d_mapped:
                feats, by_state, mapped, label_of = d_feats, d_by_state, d_mapped, d_label
                states, unmatched_n, unmatched_districts = d_states or {only}, d_un, d_und

    n_data = len(mapped)
    scope = "national" if len(states) > 1 else ("district" if n_data <= 1 else "state")

    # which districts to draw: at national scope the whole country, so India
    # reads as India instead of a handful of states floating in space; at state
    # or district scope only the state(s) the data touches.
    if scope == "national":
        draw = list(range(len(feats)))
    else:
        draw = sorted({i for ns in states for i in by_state.get(ns, [])})
    if not draw:
        draw = list(range(len(feats)))
    vmax = max(mapped.values()) if mapped else 1

    # fit the view to where the DATA is (+ context margin), not the whole drawn
    # state -- so a single-district exam zooms to that district instead of a big
    # empty silhouette. Surrounding districts still draw for context.
    # fit_full -> always frame the WHOLE drawn state(s), no matter where the data
    # falls; otherwise zoom to the data districts (+ context margin)
    # national frames the whole landmass; the tighter scopes frame the data
    focus = draw if (fit_full or scope == "national") else ([i for i in draw if mapped.get(i, 0) > 0] or draw)
    pts = [pt for i in focus for poly in feats[i]["polys"] for ring in poly for pt in ring]
    lons = [p[0] for p in pts]
    lats = [p[1] for p in pts]
    minx, miny, maxx, maxy = min(lons), min(lats), max(lons), max(lats)
    if fit_full:
        cm, fl = 0.05, 0.3
    elif scope == "district":
        # the sweet spot: enough neighbouring land that the district reads as
        # part of a country, tight enough that its actual shape is the subject
        cm, fl = 0.85, 0.10
    elif scope == "state":
        cm, fl = 0.10, 0.20
    else:
        cm, fl = 0.02, 0.15
    ex = max((maxx - minx) * cm, fl)
    ey = max((maxy - miny) * cm, fl)
    minx, maxx, miny, maxy = minx - ex, maxx + ex, miny - ey, maxy + ey

    # cull whatever the viewBox will not show -- at district scope this drops
    # ~70 off-screen districts, which is most of what made the frame cluttered
    def _bbox(i):
        xs = [p[0] for poly in feats[i]["polys"] for ring in poly for p in ring]
        ys = [p[1] for poly in feats[i]["polys"] for ring in poly for p in ring]
        return min(xs), min(ys), max(xs), max(ys)

    draw = [i for i in draw
            if (lambda b: b[0] <= maxx and b[2] >= minx and b[1] <= maxy and b[3] >= miny)(_bbox(i))]

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

    hair = {"district": 1.6, "state": 1.0}.get(scope, 0.8)
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
            f'stroke="{stroke}" stroke-width="{hair if light else 0.5}" '
            f'stroke-linejoin="round"/>')
        if val > 0 and cn:
            centroids.append((val, name, cx / cn, cy / cn))

    centroids.sort(reverse=True)
    # soft radial heat-glow halos on the hottest districts — the command-centre look
    glow = ""
    if centroids:
        gmax = centroids[0][0] or 1
        base = max(vbw, vbh)
        rings = '<g pointer-events="none">' + "".join(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{base * (0.022 + (val / gmax) ** 0.7 * 0.055):.1f}" fill="url(#hotglow)"/>'
            for val, name, x, y in centroids[:6]) + '</g>'
        hot0, hot1 = (("#C9735F", "#A55242") if light else ("#D79A82", "#C4816C"))
        o0, o1 = ((0.16, 0.05) if light else (0.34, 0.13))
        glow = (f'<defs><radialGradient id="hotglow" cx="50%" cy="50%" r="50%">'
                f'<stop offset="0%" stop-color="{hot0}" stop-opacity="{o0}"/>'
                f'<stop offset="38%" stop-color="{hot1}" stop-opacity="{o1}"/>'
                f'<stop offset="100%" stop-color="{hot1}" stop-opacity="0"/>'
                f'</radialGradient>'
                # Elevation, properly. A single blurred shadow reads as a
                # sticker; a raised object gives you three things at once — a
                # specular highlight along the edges facing the light, a tight
                # contact shadow directly beneath, and a wide ambient shadow
                # further out. All three, from one chain.
                f'<filter id="landlift" x="-14%" y="-14%" width="128%" height="132%">'
                f'<feGaussianBlur in="SourceAlpha" stdDeviation="1.0" result="lb"/>'
                f'<feSpecularLighting in="lb" surfaceScale="1.7" specularConstant="0.24" '
                f'specularExponent="26" lighting-color="#FFFFFF" result="sp">'
                f'<feDistantLight azimuth="228" elevation="58"/></feSpecularLighting>'
                f'<feComposite in="sp" in2="SourceAlpha" operator="in" result="spc"/>'
                f'<feComposite in="SourceGraphic" in2="spc" operator="arithmetic" '
                f'k1="0" k2="1" k3="{0.30 if light else 0}" k4="0" result="lit"/>'
                f'<feDropShadow in="lit" dx="0" dy="1.5" stdDeviation="1.8" '
                f'flood-color="#5A4A3E" flood-opacity="{0.15 if light else 0}" result="c1"/>'
                f'<feDropShadow in="c1" dx="0" dy="11" stdDeviation="15" '
                f'flood-color="#5A4A3E" flood-opacity="{0.15 if light else 0}"/>'
                f'</filter></defs>' + rings)
    labels = []
    # clutter control: one clear marker when a single district IS the story,
    # a handful for a state, fewer still nationally
    label_top = min(label_top, {"district": 1, "state": 6, "national": 5}.get(scope, label_top))
    pulse = min(pulse, 1 if scope == "district" else pulse)
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
                f'<text x="{pad:.1f}" y="{wy:.1f}" fill="{"#A94A60" if light else "#E8535E"}" font-size="11" '
                f'font-family="IBM Plex Mono,monospace">{wtxt}</text></g>')

    land = (f'<g filter="url(#landlift)">' + "".join(paths) + '</g>') if light         else "".join(paths)
    # glow first when light: it reads as warmth coming THROUGH the sheet rather
    # than a sticker laid on top of it
    body = (glow + land) if light else (land + glow)
    return (f'<svg viewBox="0 0 {vbw:.0f} {vbh:.0f}" width="100%" height="100%" '
            f'preserveAspectRatio="xMidYMid meet" data-scope="{scope}" '
            f'data-ramp="{ramp_css() if light else ""}">'
            + body + "".join(labels) + warn + "</svg>")


def resolve_name(district: str) -> str | None:
    """Legacy single-arg resolver kept for callers that pass a bare district."""
    idx = _resolve("", district)
    feats, _, _ = _load()
    return feats[idx]["district"] if idx is not None else None
