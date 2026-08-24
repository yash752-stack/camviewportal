"""Imagery for an examination centre, from whatever the alert export gives us.

The export carries four usable fields per centre -- code, name, district and
state -- and no address, pincode or coordinates. So every provider here is
handed the same thing: a best-effort place query built from those four, plus
the centre's own evidence frames as an always-available fallback.

Design is a provider list, tried in order, first hit wins:

    EvidenceProvider   the centre's own CCTV frame. Always available, always
                       correct, needs no network and no key. This is the only
                       provider that is *about this centre* rather than about
                       a place that shares its name.
    StreetViewProvider Google Street View Static -- a real photograph of the
                       building, when Google has imagery for the query. Checked
                       against the free metadata endpoint first so a miss costs
                       no quota.
    StaticMapProvider  Google Maps Static -- a satellite/hybrid tile centred on
                       the query. Resolves far more often than Street View
                       because it falls back to the locality.

Nothing here is wired into ingest or the UI yet: `audit()` runs offline with no
key and reports how many centres could plausibly resolve, which is the number
that decides whether the paid providers are worth turning on at all.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Protocol
from urllib.parse import urlencode

from .settings import get_settings

# Names that are a room, a role or a placeholder rather than a findable place.
# "Command control room" is the literal centre name in one real export -- no
# geocoder on earth resolves that, and pretending otherwise wastes quota and
# puts a photo of the wrong building in a compliance report.
_UNPLACEABLE = re.compile(
    r"^\s*(command|control|monitoring|server|exam|examination|test)?\s*"
    r"(control\s*)?(room|centre|center|hall|lab|office|hq|headquarters|na|n/?a|-+|\d+)\s*$",
    re.I,
)
# Tokens that suggest a real, findable institution.
_PLACE_HINT = re.compile(
    r"\b(school|vidyalaya|vidhyalaya|college|university|institute|academy|"
    r"public|convent|inter|degree|polytechnic|itiy?|iti|campus|bhawan|bhavan|"
    r"sr\.?\s*sec|senior\s*secondary|h\.?s\.?s|hss|kendriya|jawahar|saraswati)\b",
    re.I,
)


@dataclass(frozen=True)
class Centre:
    code: str
    name: str
    district: str = ""
    state: str = ""

    def query(self) -> str:
        """The place string handed to any external provider."""
        parts = [p.strip() for p in (self.name, self.district, self.state, "India") if p and p.strip()]
        # drop a district that is already inside the name, so we don't send
        # "XYZ School, Noida, Noida, Uttar Pradesh"
        out: list[str] = []
        for p in parts:
            if not any(p.lower() == q.lower() for q in out):
                out.append(p)
        return ", ".join(out)

    @property
    def placeable(self) -> str:
        """How likely this name is to resolve: 'good' | 'weak' | 'none'."""
        n = (self.name or "").strip()
        if not n or _UNPLACEABLE.match(n):
            return "none"
        if _PLACE_HINT.search(n):
            return "good"
        return "weak" if len(n.split()) >= 2 else "none"


@dataclass
class Image:
    url: str            # what the page should load
    kind: str           # 'evidence' | 'streetview' | 'staticmap'
    caption: str = ""
    attribution: str = ""
    centre_code: str = ""


class Provider(Protocol):
    name: str

    def available(self) -> bool: ...
    def fetch(self, centre: Centre) -> Image | None: ...


# --------------------------------------------------------------------------- #
# providers
# --------------------------------------------------------------------------- #
@dataclass
class EvidenceProvider:
    """The centre's own captured frame. No key, no network, never wrong."""

    name: str = "evidence"
    exam_code: str = ""
    frames: dict[str, str] = field(default_factory=dict)   # centre_code -> alarm id

    def available(self) -> bool:
        return bool(self.frames)

    def fetch(self, centre: Centre) -> Image | None:
        alarm = self.frames.get(centre.code)
        if not alarm:
            return None
        from urllib.parse import quote
        return Image(url=f"/api/evidence/{self.exam_code}/{quote(alarm, safe='')}",
                     kind="evidence", caption=centre.name,
                     attribution="CamView capture", centre_code=centre.code)


@dataclass
class _GoogleProvider:
    api_key: str = ""
    size: str = "640x400"

    def available(self) -> bool:
        return bool(self.api_key)


@dataclass
class StreetViewProvider(_GoogleProvider):
    """A photograph of the place, when Google has one.

    The metadata endpoint is free and returns status OK/ZERO_RESULTS, so a
    lookup that has no imagery never spends a billable request -- and never
    renders Google's grey 'no imagery' placeholder into your report.
    """

    name: str = "streetview"

    def has_imagery(self, centre: Centre) -> bool:
        import urllib.request, json
        q = urlencode({"location": centre.query(), "key": self.api_key})
        url = f"https://maps.googleapis.com/maps/api/streetview/metadata?{q}"
        try:
            with urllib.request.urlopen(url, timeout=8) as r:
                return json.loads(r.read()).get("status") == "OK"
        except Exception:
            return False

    def fetch(self, centre: Centre) -> Image | None:
        if not self.available() or centre.placeable == "none":
            return None
        if not self.has_imagery(centre):
            return None
        q = urlencode({"location": centre.query(), "size": self.size,
                       "fov": "80", "pitch": "6", "key": self.api_key})
        return Image(url=f"https://maps.googleapis.com/maps/api/streetview?{q}",
                     kind="streetview", caption=centre.name,
                     attribution="Google Street View", centre_code=centre.code)


@dataclass
class StaticMapProvider(_GoogleProvider):
    """A satellite/hybrid tile centred on the query. Resolves far more often
    than Street View because it degrades to the locality rather than failing."""

    name: str = "staticmap"
    zoom: int = 17
    maptype: str = "hybrid"

    def fetch(self, centre: Centre) -> Image | None:
        if not self.available() or centre.placeable == "none":
            return None
        q = urlencode({"center": centre.query(), "zoom": self.zoom, "size": self.size,
                       "scale": "2", "maptype": self.maptype,
                       "markers": f"color:0xA55242|{centre.query()}", "key": self.api_key})
        return Image(url=f"https://maps.googleapis.com/maps/api/staticmap?{q}",
                     kind="staticmap", caption=centre.name,
                     attribution="Google Maps", centre_code=centre.code)


# --------------------------------------------------------------------------- #
# resolver
# --------------------------------------------------------------------------- #
def build_providers(exam_code: str = "", frames: dict[str, str] | None = None) -> list[Provider]:
    """Providers in preference order, skipping any that isn't configured."""
    s = get_settings()
    key = getattr(s, "google_maps_key", "") or ""
    chain: list[Provider] = [EvidenceProvider(exam_code=exam_code, frames=frames or {})]
    if key:
        chain += [StreetViewProvider(api_key=key), StaticMapProvider(api_key=key)]
    return [p for p in chain if p.available()]


def resolve(centre: Centre, providers: Iterable[Provider]) -> Image | None:
    for p in providers:
        try:
            img = p.fetch(centre)
        except Exception:
            continue          # a provider outage must never break the page
        if img:
            return img
    return None


def cache_key(centre: Centre) -> str:
    return hashlib.sha1(centre.query().lower().encode()).hexdigest()[:16]


# --------------------------------------------------------------------------- #
# audit -- runs offline, no key, no network
# --------------------------------------------------------------------------- #
def audit(centres: Iterable[Centre]) -> dict:
    """How many of these centres could plausibly resolve to a real place?

    Run this on real export data BEFORE enabling any paid provider. If most
    centres grade 'none', the imagery feature cannot work from this data and
    the fix is an address column in the centre-list upload, not an API key.
    """
    buckets: dict[str, list[Centre]] = {"good": [], "weak": [], "none": []}
    for c in centres:
        buckets[c.placeable].append(c)
    total = sum(len(v) for v in buckets.values()) or 1
    return {
        "total": total,
        "counts": {k: len(v) for k, v in buckets.items()},
        "pct": {k: round(100 * len(v) / total, 1) for k, v in buckets.items()},
        "samples": {k: [c.name for c in v[:5]] for k, v in buckets.items()},
        "example_query": next((c.query() for c in buckets["good"] or buckets["weak"]), ""),
    }
