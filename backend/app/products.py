"""The Innovatiview product suite, as the gate presents it.

Names and taglines are the company's own, taken from innovatiview.com. Only
CamView is on this interface today; the rest are listed as present-but-pending
rather than hidden, because the point of a standard interface is that an
operator can see the whole suite from any one product.

Icons are simple line glyphs drawn here rather than sourced, so they share a
single stroke weight and read at 26px. Tints are the pale wash behind a
selected disc — quiet enough that ten of them together do not turn the ring
into a colour chart.
"""
from __future__ import annotations

_I = {
    "cctv": '<svg viewBox="0 0 24 24"><path d="M3 7l14-3 1.4 5.2L4.4 12.2z"/>'
            '<path d="M4.4 12.2L6 17M11 6.5l1 3.6"/><path d="M18.4 9.2l2.6-.7"/>'
            '<circle cx="6" cy="19" r="2"/></svg>',
    "finger": '<svg viewBox="0 0 24 24"><path d="M12 3a7 7 0 0 0-7 7v3"/>'
              '<path d="M19 10a7 7 0 0 0-3.5-6"/><path d="M8.5 20.5A9 9 0 0 0 10 15v-5a2 2 0 1 1 4 0v5"/>'
              '<path d="M16.5 19.5A9 9 0 0 0 17.5 15"/><path d="M5.5 17.5A9 9 0 0 1 5 15"/></svg>',
    "signal": '<svg viewBox="0 0 24 24"><path d="M5 15.5a7 7 0 0 1 0-9.9"/>'
              '<path d="M19 5.6a7 7 0 0 1 0 9.9"/><path d="M8 12.7a3 3 0 0 1 0-4.2"/>'
              '<path d="M16 8.5a3 3 0 0 1 0 4.2"/><circle cx="12" cy="10.6" r="1.6"/>'
              '<path d="M12 12.2V21"/></svg>',
    "wand": '<svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/>'
            '<path d="M12 14v7M8 21h8"/><path d="M5 8h1.5M17.5 8H19"/></svg>',
    "portrait": '<svg viewBox="0 0 24 24"><rect x="4" y="3" width="16" height="18" rx="2"/>'
                '<circle cx="12" cy="10" r="2.6"/><path d="M7.5 17.5a4.8 4.8 0 0 1 9 0"/></svg>',
    "server": '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="6" rx="1.5"/>'
              '<rect x="3" y="14" width="18" height="6" rx="1.5"/>'
              '<path d="M7 7h.01M7 17h.01"/></svg>',
    "qr": '<svg viewBox="0 0 24 24"><rect x="3" y="3" width="7" height="7" rx="1"/>'
          '<rect x="14" y="3" width="7" height="7" rx="1"/><rect x="3" y="14" width="7" height="7" rx="1"/>'
          '<path d="M14 14h3v3h-3zM20 14v3M14 20h6"/></svg>',
    "pin": '<svg viewBox="0 0 24 24"><path d="M12 21s7-5.7 7-11a7 7 0 1 0-14 0c0 5.3 7 11 7 11z"/>'
           '<circle cx="12" cy="10" r="2.5"/></svg>',
    "scan": '<svg viewBox="0 0 24 24"><path d="M4 8V5.5A1.5 1.5 0 0 1 5.5 4H8"/>'
            '<path d="M16 4h2.5A1.5 1.5 0 0 1 20 5.5V8"/><path d="M20 16v2.5a1.5 1.5 0 0 1-1.5 1.5H16"/>'
            '<path d="M8 20H5.5A1.5 1.5 0 0 1 4 18.5V16"/><path d="M4 12h16"/></svg>',
    "bolt": '<svg viewBox="0 0 24 24"><path d="M13 2L5 13.5h6L10.5 22 19 10.5h-6z"/></svg>',
    "otr": '<svg viewBox="0 0 24 24"><rect x="3" y="4.5" width="18" height="15" rx="2"/>'
           '<circle cx="8.8" cy="10.6" r="2.1"/>'
           '<path d="M5.4 16.2a3.9 3.9 0 0 1 6.8 0"/>'
           '<path d="M14.6 9.6H19M14.6 13H19"/></svg>',
}

# name, slug, icon, tagline, tint, live
PRODUCTS = [
    ("TrustView",   "trustview",   _I["finger"],
     "Biometric security for impersonation control at every step of a critical process.",
     "#D9E4DF", False),
    ("CamView",     "camview",     _I["cctv"],
     "AI/ML powered CCTV surveillance with an integrated command control room, "
     "eliminating malpractice while keeping the whole examination under evidence.",
     "#BFDAD3", True),
    ("ConnectView", "connectview", _I["signal"],
     "One-touch secured line for seamless communication in no-network zones.",
     "#DCE6DA", False),
    ("GuardView",   "guardview",   _I["wand"],
     "Manual and HHMD frisking to detect mobiles, smartwatches and Bluetooth devices.",
     "#F3DCCB", False),
    ("InfraView",   "infraview",   _I["server"],
     "Fully equipped, secured computer centres for protected computing environments.",
     "#E2E2D4", False),
    ("seQRView",    "seqrview",    _I["qr"],
     "Offline QR system with colour-coded ID cards for ground-staff and invigilator access control.",
     "#D3E2DE", False),
    ("TrackView",   "trackview",   _I["pin"],
     "GPS-enabled tracking that protects critical documents from theft and tampering.",
     "#E7DED0", False),
    ("ScanView",    "scanview",    _I["scan"],
     "On-spot OMR scanning, extracting and uploading data to secure cloud storage in real time.",
     "#DDE7DC", False),
    ("PowerView",   "powerview",   _I["bolt"],
     "Static and mobile generator backup for uninterrupted operations.",
     "#F5E3C9", False),
    ("OTR",         "otr",         _I["otr"],
     "One Time Registration — a candidate registers once, and that verified "
     "profile carries forward into every examination they apply to.",
     "#EADFCE", False),
]


def catalogue() -> list[dict]:
    return [{"name": n, "slug": s, "icon": i, "tagline": t, "tint": c, "live": v}
            for n, s, i, t, c, v in PRODUCTS]


def by_slug(slug: str) -> dict | None:
    for p in catalogue():
        if p["slug"] == slug:
            return p
    return None
