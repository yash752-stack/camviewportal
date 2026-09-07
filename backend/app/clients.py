"""Conducting bodies and their marks — the client library.

Every examination belongs to a conducting body (NTA, UPSSSC, UPESSC, RUHS, a
state board ...). The body's own mark goes on the cover of every report and in
the workspace header, so the same portal reads as the client's the moment the
exam is created. This module is the one place that knows a body's mark:

- `assets/clients/clients.json` is the shipped library: names, aliases, a mark
  file where a free one exists, and whether the Emblem of India belongs beside
  it (government bodies).
- `<data_dir>/clients/` holds marks added from the portal — the wizard's body
  step or the exam's Edit details — so an operator can add a body that is not
  in the library and its logo without touching the code. Entries there override
  the library.

Matching is forgiving: the exam's body is compared to each entry's name, slug,
aliases and acronym, case-insensitively, so "NTA", "National Testing Agency"
and "nta - neet" all find the same mark.
"""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path

from .settings import get_settings

_S = get_settings()
LIB = _S.assets_dir / "clients"          # shipped with the portal
USER = _S.data_dir / "clients"           # added from the portal, per deployment

_STOP = {"of", "and", "the", "for", "in", "&"}
_GOV = ("commission", "board", "agency", "council", "parishad", "university", "government", "ministry",
        "authority", "department", "institute", "selection", "examination", "testing", "corporation", "directorate")


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")[:64]


def acronym(name: str) -> str:
    words = [w for w in re.findall(r"[A-Za-z]+", name or "") if w.lower() not in _STOP]
    return "".join(w[0] for w in words).lower()


def is_government(name: str) -> bool:
    n = (name or "").lower()
    return any(w in n for w in _GOV)


def _read(p: Path) -> list[dict]:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _norm(entry: dict, root: Path) -> dict:
    name = entry.get("name", "")
    e = {
        "slug": entry.get("slug") or slug(name),
        "name": name,
        "match": [m.lower() for m in entry.get("match", [])],
        "emblem": bool(entry.get("emblem", False)),
        "line": entry.get("line", ""),
        "credit": entry.get("credit", ""),
        "mark": entry.get("mark") or "",
        "mark_path": None,
    }
    if e["mark"]:
        p = root / e["mark"]
        if p.exists():
            e["mark_path"] = p
    return e


def library() -> list[dict]:
    """Every known body, user-added entries overriding shipped ones by slug."""
    out: dict[str, dict] = {}
    for e in _read(LIB / "clients.json"):
        n = _norm(e, LIB)
        out[n["slug"]] = n
    for e in _read(USER / "clients.json"):
        n = _norm(e, USER)
        out[n["slug"]] = n
    return sorted(out.values(), key=lambda x: x["name"].lower())


def find(body: str) -> dict | None:
    """The entry whose name, slug, alias or acronym fits the exam's body."""
    b = (body or "").strip().lower()
    if not b:
        return None
    bs, ba = slug(b), acronym(body)
    lib = library()
    for e in lib:                              # exact first
        if b == e["name"].lower() or bs == e["slug"] or b in e["match"] or (ba and ba == e["slug"]):
            return e
    for e in lib:                              # then a contained alias or acronym
        for t in e["match"] + [e["slug"]]:
            if len(t) > 3 and (t in b or t in bs):
                return e
        if len(ba) > 2 and ba == acronym(e["name"]):
            return e
    return None


def by_slug(s: str) -> dict | None:
    for e in library():
        if e["slug"] == s:
            return e
    return None


def mark_url(body: str) -> str:
    e = find(body)
    return f"/api/clients/{e['slug']}/mark" if e and e["mark_path"] else ""


def public(e: dict) -> dict:
    return {"slug": e["slug"], "name": e["name"], "aliases": e["match"], "emblem": e["emblem"],
            "hasMark": bool(e["mark_path"]), "mark": (f"/api/clients/{e['slug']}/mark" if e["mark_path"] else ""),
            "line": e["line"]}


def save(name: str, mark_bytes: bytes | None, mark_name: str | None, emblem: bool | None = None,
         aliases: list[str] | None = None, line: str | None = None) -> dict:
    """Add or update a body from the portal. A mark is an SVG or PNG; without
    one the entry still exists so the body appears in the dropdown."""
    name = (name or "").strip()
    if not name:
        raise ValueError("A body name is required.")
    s = slug(name)
    USER.mkdir(parents=True, exist_ok=True)
    entries = _read(USER / "clients.json")
    cur = next((e for e in entries if (e.get("slug") or slug(e.get("name", ""))) == s), None)
    base = by_slug(s) or {}
    if cur is None:
        cur = {"slug": s, "name": name, "match": list(base.get("match", [])), "emblem": base.get("emblem", is_government(name)),
               "mark": base.get("mark", "") if base.get("mark_path") and base.get("mark_path").parent == USER else "", "line": base.get("line", "")}
        entries.append(cur)
    ac = acronym(name)
    for a in [ac] + (aliases or []):
        if a and a.lower() not in cur["match"]:
            cur["match"].append(a.lower())
    if emblem is not None:
        cur["emblem"] = bool(emblem)
    if line is not None:
        cur["line"] = line.strip()
    if mark_bytes and mark_name:
        ext = Path(mark_name).suffix.lower()
        if ext not in (".svg", ".png"):
            raise ValueError("The mark must be an SVG or PNG file.")
        if ext == ".svg" and b"<svg" not in mark_bytes[:4000].lower():
            raise ValueError("That SVG does not look like an SVG file.")
        for old in USER.glob(f"{s}.*"):
            old.unlink(missing_ok=True)
        (USER / f"{s}{ext}").write_bytes(mark_bytes)
        cur["mark"] = f"{s}{ext}"
    (USER / "clients.json").write_text(json.dumps(entries, indent=1, ensure_ascii=False), encoding="utf-8")
    return _norm(cur, USER)


def mark_file(s: str) -> Path | None:
    e = by_slug(s)
    return e["mark_path"] if e else None
