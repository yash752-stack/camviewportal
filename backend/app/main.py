"""CAMVIEW AI — Examination Compliance & Evidence Platform. Application entrypoint.

Navigation follows the locked hierarchy: Examination Library -> Examination
Workspace (modality hub) -> Modality Dashboard / Generate Report.
"""
from __future__ import annotations

import logging
import traceback
from contextlib import asynccontextmanager
import zlib
from pathlib import Path

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import delete as sa_delete, func, select
from sqlalchemy.orm import Session

from . import reporting as R
from .db import SessionLocal, get_session, init_db
from .models import Alert, Exam

log = logging.getLogger("camview.report")
from .registry import get_registry
from .report_render import generate_report_pdf
from . import auth, products
from .settings import get_settings
from .api.routes import router as api_router

settings = get_settings()
def _asset_v() -> int:
    return int((Path(__file__).parent / "web" / "static" / "app.css").stat().st_mtime)


TEMPLATES = Jinja2Templates(directory=str(Path(__file__).parent / "web" / "templates"))


def _heal_evidence_paths() -> None:
    """Make bundled evidence portable across machines.

    Evidence is captured with absolute paths (e.g. /Users/<someone>/Downloads/…).
    When the portal is shipped with its evidence vault bundled under
    backend/data/evidence/<exam-code>/, those stored paths won't resolve on a
    different Mac. On startup we detect a bundled vault and rebase the DB's
    evidence_root + every alert's evidence_image onto wherever the bundle now
    physically lives — so the portal renders identically anywhere, regardless of
    username or where the folder was dropped. Idempotent and cheap once healed.
    """
    with SessionLocal() as s:
        changed = False
        for exam in s.scalars(select(Exam)).all():
            bundled = (settings.evidence_dir / exam.code).resolve()
            if not bundled.is_dir():
                continue                       # no bundled vault for this exam — leave as-is
            new_root = str(bundled)
            old_root = exam.evidence_root or ""
            if old_root == new_root:
                continue                       # already healed
            if old_root:
                for a in s.scalars(select(Alert).where(
                        Alert.exam_id == exam.id, Alert.evidence_image != "")).all():
                    if a.evidence_image.startswith(old_root):
                        a.evidence_image = new_root + a.evidence_image[len(old_root):]
            exam.evidence_root = new_root
            changed = True
        if changed:
            s.commit()


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    _heal_evidence_paths()
    from .registry import catalogue_status
    status = catalogue_status()
    if not status["ok"]:
        log.error(
            "="*70 + "\n"
            "STARTUP WARNING: modality catalogue not found at:\n  %s\n"
            "Running on the built-in fallback copy instead, so the app will\n"
            "still work — but if this file was meant to be there (e.g. a custom\n"
            "catalogue, or the config/ folder went missing during install/copy),\n"
            "it should be restored.\n" + "="*70,
            status["path"],
        )
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)
app.include_router(api_router)
app.middleware("http")(auth.gate)


@app.get("/login", response_class=HTMLResponse)
def login_page(request: Request, next: str = "/", error: str = "", prefill: str = ""):
    if auth.identify(request):
        return RedirectResponse(next or "/", status_code=303)
    return TEMPLATES.TemplateResponse(request, "login.html", {
        "v": _asset_v(), "next": next or "/", "error": error, "prefill": prefill,
        "product": auth.PRODUCT, "product_code": auth.PRODUCT_CODE,
        "tagline": auth.TAGLINE,
        "demo": [(u, p, r) for u, (p, r) in auth.DEMO_USERS.items()],
        "products": products.catalogue(),
    })


@app.post("/login")
async def login_submit(request: Request):
    form = await request.form()
    username = (form.get("username") or "").strip()
    password = form.get("password") or ""
    nxt = form.get("next") or "/"
    if not auth.check(username, password):
        return TEMPLATES.TemplateResponse(request, "login.html", {
            "v": _asset_v(), "next": nxt, "prefill": username,
            "error": "That operator ID and passphrase do not match.",
            "product": auth.PRODUCT, "product_code": auth.PRODUCT_CODE,
            "tagline": auth.TAGLINE,
            "demo": [(u, p, r) for u, (p, r) in auth.DEMO_USERS.items()],
            "products": products.catalogue(),
        }, status_code=401)
    resp = RedirectResponse(nxt if nxt.startswith("/") else "/", status_code=303)
    resp.set_cookie(auth.COOKIE, auth.issue(username), httponly=True,
                    samesite="lax", max_age=60 * 60 * 12)
    return resp


@app.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=303)
    resp.delete_cookie(auth.COOKIE)
    return resp


app.mount("/static", StaticFiles(directory=str(Path(__file__).parent / "web" / "static")), name="static")
app.mount("/brand", StaticFiles(directory=str(settings.assets_dir)), name="brand")


def _exam_or_404(session: Session, code: str) -> Exam:
    exam = session.scalar(select(Exam).where(Exam.code == code))
    if not exam:
        raise HTTPException(404, "examination not found")
    return exam


# A stable per-exam accent, drawn from the application palette's category set.
# Deterministic on the exam code (crc32, not hash() -- that is salted per
# process and would repaint the library on every restart), so a given exam is
# always the same colour and the shelf reads as distinct objects.
_EXAM_ACCENTS = ["#A55242", "#3B5BB5", "#2F9E6E", "#684E86", "#B08A1E", "#35696C", "#4C6190"]


def _modality_label(mcode: str) -> str:
    m = get_registry().by_code(mcode)
    return m.display_label if m else mcode


@app.get("/", response_class=HTMLResponse)
def home(request: Request, session: Session = Depends(get_session)):
    exams = session.scalars(select(Exam).order_by(Exam.created_at.desc())).all()
    cards = []
    tot_alerts = tot_centres = 0
    for e in exams:
        mods = session.execute(
            select(Alert.modality_code, func.count(Alert.id)).where(Alert.exam_id == e.id)
            .group_by(Alert.modality_code).order_by(func.count(Alert.id).desc())).all()
        districts = session.scalar(
            select(func.count(func.distinct(Alert.district))).where(
                Alert.exam_id == e.id, Alert.district != ""))
        centres = session.scalar(
            select(func.count(func.distinct(Alert.centre_code))).where(Alert.exam_id == e.id))
        # the per-modality counts were already being computed and thrown away;
        # keeping them costs nothing and gives each card a real distribution bar
        mtot = sum(n for _, n in mods) or 1
        cards.append({"exam": e, "modalities": len(mods),
                      "mods": [{"code": m, "label": _modality_label(m), "n": n,
                                "pct": round(100 * n / mtot, 2)} for m, n in mods],
                      "districts": districts or 0, "centres": centres or 0})
        tot_alerts += e.alert_count or 0
        tot_centres += centres or 0
    # accent per conducting BODY, not per exam: every UPSSSC exam should read as
    # one family on the shelf. crc32 picks a preferred slot so a body keeps its
    # colour across restarts (hash() is salted per process); collisions walk to
    # the next free slot so two different bodies never share a hue.
    taken: dict[str, int] = {}
    used: set[int] = set()
    for c in cards:
        key = (c["exam"].body or c["exam"].code).strip().upper()
        if key not in taken:
            want = zlib.crc32(key.encode()) % len(_EXAM_ACCENTS)
            for step in range(len(_EXAM_ACCENTS)):
                slot = (want + step) % len(_EXAM_ACCENTS)
                if slot not in used:
                    break
            used.add(slot)
            if len(used) == len(_EXAM_ACCENTS):
                used.clear()       # more bodies than accents: start the cycle again
            taken[key] = slot
        c["accent"] = _EXAM_ACCENTS[taken[key]]
        c["body"] = c["exam"].body or ""

    totals = {"exams": len(exams), "alerts": tot_alerts, "centres": tot_centres}
    asset_v = int((Path(__file__).parent / "web" / "static" / "app.css").stat().st_mtime)
    return TEMPLATES.TemplateResponse(request, "home.html", {"cards": cards, "totals": totals, "v": asset_v})


@app.get("/upload", response_class=HTMLResponse)
def upload_page(request: Request):
    asset_v = int((Path(__file__).parent / "web" / "static" / "app.css").stat().st_mtime)
    return TEMPLATES.TemplateResponse(request, "upload.html", {"v": asset_v})


@app.post("/upload")
async def create_exam(request: Request, session: Session = Depends(get_session)):
    """Ingest an uploaded alert Excel (+ evidence folder or local path) into a new exam.

    The form is parsed by hand with a raised file cap — an evidence drop is one file
    per frame, so a real exam easily exceeds Starlette's default 1000-file limit."""
    import re
    import shutil
    from datetime import datetime
    from .ingest.pipeline import ingest_exam, append_to_exam

    form = await request.form(max_files=100000, max_fields=2000)

    def _files(key):
        return [f for f in form.getlist(key) if hasattr(f, "filename") and f.filename]

    name = (form.get("name") or "").strip()
    body = (form.get("body") or "").strip()
    code = (form.get("code") or "").strip()
    exam_date = form.get("exam_date") or ""
    session_label = form.get("session_label") or ""
    evidence_path = form.get("evidence_path") or ""
    shifts_json = form.get("shifts_json") or ""
    shifts_by_date_json = form.get("shifts_by_date_json") or ""
    new_modalities_json = form.get("new_modalities_json") or ""
    # optional per-exam modality exclusions (e.g. the operator says this exam has
    # no trunk, so Trunk Placed / Trunk Open shouldn't be ingested). Sent as a
    # comma-separated list of modality codes from the create-exam wizard.
    exclude_raw = (form.get("exclude_modalities") or "").strip()
    exclude_modalities = {c.strip().upper() for c in exclude_raw.split(",") if c.strip()}
    try:
        centre_total = int(form.get("centre_total") or 0)
    except (TypeError, ValueError):
        centre_total = 0
    excel = _files("excel")
    evidence = _files("evidence")
    _cl = _files("centre_list")
    centre_list = _cl[0] if _cl else None
    if not excel:
        return JSONResponse({"ok": False, "error": "An alert Excel file is required."}, status_code=400)

    if not code or not name:
        return JSONResponse({"ok": False, "error": "Examination name and code are required."}, status_code=400)
    if session.scalar(select(Exam).where(Exam.code == code)):
        return JSONResponse({"ok": False, "error": f"An examination with code '{code}' already exists."}, status_code=400)

    updir = settings.data_dir / "uploads" / re.sub(r"[^A-Za-z0-9_-]+", "_", code)
    updir.mkdir(parents=True, exist_ok=True)
    # one or several alert exports — first creates the exam, the rest are merged
    # (deduplicated by Alarm ID) so a multi-day exam can be built in one shot
    xls: list[Path] = []
    for i, up in enumerate(excel):
        xl = updir / (Path(up.filename or f"source{i}.xlsx").name)
        with xl.open("wb") as f:
            shutil.copyfileobj(up.file, f)
        xls.append(xl)

    # evidence: a local folder path (best for large drops) takes precedence; else uploaded files
    media = {".jpg", ".jpeg", ".png", ".mp4", ".mkv", ".avi", ".mov"}
    evroot = None
    p = Path(evidence_path.strip()).expanduser() if evidence_path.strip() else None
    if p and p.is_dir():
        evroot = p
    elif evidence:
        evdir = updir / "evidence"
        evdir.mkdir(exist_ok=True)
        saved = 0
        for uf in evidence:
            if not uf.filename or Path(uf.filename).suffix.lower() not in media:
                continue
            with (evdir / Path(uf.filename).name).open("wb") as f:
                shutil.copyfileobj(uf.file, f)
            saved += 1
        evroot = evdir if saved else None

    d = None
    if exam_date.strip():
        try:
            d = datetime.strptime(exam_date.strip(), "%Y-%m-%d").date()
        except ValueError:
            d = None
    # operator decisions from the wizard: {channel: isInputDependent}. A new alarm
    # type marked input-dependent is still ingested & rendered, but flagged for a
    # developer to add a bespoke catalogue entry.
    import json as _json
    decisions: dict[str, bool] = {}
    if new_modalities_json.strip():
        try:
            raw_dec = _json.loads(new_modalities_json)
            if isinstance(raw_dec, dict):
                decisions = {str(k): bool(v) for k, v in raw_dec.items()}
        except (ValueError, TypeError):
            decisions = {}

    try:
        res = ingest_exam(session, code=code, name=name, body=body, session_label=session_label.strip(),
                          exam_date=d, excel_path=xls[0], evidence_root=evroot, decisions=decisions,
                          exclude_modalities=exclude_modalities)
        # merge any additional files into the just-created exam
        if len(xls) > 1:
            exam0 = session.get(Exam, res.exam_id)
            for xl in xls[1:]:
                ares = append_to_exam(session, exam=exam0, excel_path=xl, evidence_root=evroot,
                                      decisions=decisions, exclude_modalities=exclude_modalities)
                res.alert_count += ares.alert_count
                res.evidence_linked += ares.evidence_linked
                res.duplicates += ares.duplicates
                for k, v in ares.unmapped_channels.items():
                    res.unmapped_channels[k] = res.unmapped_channels.get(k, 0) + v
                for c, info in ares.new_modalities.items():
                    if c in res.new_modalities:
                        res.new_modalities[c]["count"] += info["count"]
                    else:
                        res.new_modalities[c] = info
        session.commit()
    except Exception as e:  # noqa: BLE001 - surface ingest errors to the uploader
        session.rollback()
        return JSONResponse({"ok": False, "error": f"Processing failed: {e}"}, status_code=500)

    # exam start date is a FACT, not manual policy: always the earliest alert
    # timestamp across all uploaded files — never depends on which file was picked
    # first. (The form's date is only a hint; the data is the source of truth.)
    mind = session.scalar(select(func.min(Alert.occurred_at)).where(Alert.exam_id == res.exam_id))
    if mind:
        ex = session.get(Exam, res.exam_id)
        ex.exam_date = mind.date()
        session.commit()

    # authorised trunk windows ARE exam policy (not in the data) -> persist what the
    # operator entered. Two shapes are accepted:
    #   * a per-date map {"YYYY-MM-DD": [shift,...], ...}  — each day may run a
    #     DIFFERENT number of shifts (one day one sitting, another day two);
    #   * a single flat list applied as the exam default (legacy / manual entry).
    import json
    from . import compliance as C

    def _clean_shifts(raw):
        out = []
        for s in raw or []:
            try:
                arr = [str(s["arrival"][0]).strip(), str(s["arrival"][1]).strip()]
                opn = [str(s["opening"][0]).strip(), str(s["opening"][1]).strip()]
            except (KeyError, IndexError, TypeError, AttributeError):
                continue
            if all(arr) and all(opn):
                out.append({"arrival": arr, "opening": opn})
        # identity is derived, never typed: earliest arrival = Shift 1
        out.sort(key=lambda s: s["arrival"][0])
        for i, s in enumerate(out):
            s["name"] = f"Shift {i + 1}"
        return out

    applied_per_date = False
    if shifts_by_date_json.strip():
        try:
            bydate = json.loads(shifts_by_date_json)
            if isinstance(bydate, dict):
                default_set = None
                for dk in sorted(bydate):
                    cl = _clean_shifts(bydate[dk])
                    if cl:
                        C.set_shifts(code, cl, date=dk)
                        applied_per_date = True
                        if default_set is None:
                            default_set = cl        # earliest configured day
                if default_set:
                    C.set_shifts(code, default_set)  # exam default = the first day
        except (ValueError, KeyError, TypeError):
            pass

    if not applied_per_date and shifts_json.strip():
        try:
            clean = _clean_shifts(json.loads(shifts_json))
            if clean:
                C.set_shifts(code, clean)
        except (ValueError, KeyError, TypeError):
            pass

    # official centre list (optional): the authoritative denominator. The alert
    # export only holds centres that fired >=1 alert, so the roster is what lets
    # us count silent (no-alert) centres.
    roster_n = 0
    if centre_list is not None and centre_list.filename:
        from .ingest.excel import read_centre_roster
        from .models import OfficialCentre
        rl = updir / ("roster_" + Path(centre_list.filename).name)
        with rl.open("wb") as f:
            shutil.copyfileobj(centre_list.file, f)
        try:
            rows = read_centre_roster(rl)
            for r in rows:
                session.add(OfficialCentre(
                    exam_id=res.exam_id, centre_code=r["centre_code"],
                    centre_name=r.get("centre_name", ""), district=r.get("district", ""),
                    state=r.get("state", "")))
            session.commit()
            roster_n = len(rows)
        except Exception:  # noqa: BLE001 - a bad roster shouldn't fail the whole ingest
            session.rollback()

    # operator-entered true centre total (denominator) — used when no roster file
    if centre_total and centre_total > 0:
        ex = session.get(Exam, res.exam_id)
        ex.centre_total = int(centre_total)
        session.commit()

    new_mods = list(res.new_modalities.values())
    return {"ok": True, "code": code, "alerts": res.alert_count,
            "evidence": res.evidence_linked, "roster": roster_n,
            "duplicates": res.duplicates, "unmapped": sum(res.unmapped_channels.values()),
            "newModalities": new_mods,
            "needsCode": [m for m in new_mods if m.get("needs_code")]}


@app.post("/api/analyze-excel")
async def analyze_excel(files: list[UploadFile] = File(...)):
    """Full auto-analysis for the create-exam wizard: guessed name/code, per-day
    shift detection with suggested trunk windows, centres, modalities. Accepts one
    OR several alert files (they're analysed together, deduplicated by Alarm ID).
    Persists nothing — the operator confirms/edits before the exam is created."""
    import shutil
    import tempfile
    from .analyze import analyze_workbook
    tmps: list[Path] = []
    try:
        for up in files:
            with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
                shutil.copyfileobj(up.file, tf)
                tmps.append(Path(tf.name))
        result = analyze_workbook(tmps, filename=(files[0].filename if files else "") or "")
        result["files"] = len(files)
        return {"ok": True, **result}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"Could not analyse the Excel: {e}"}, status_code=400)
    finally:
        for t in tmps:
            if t.exists():
                t.unlink()


@app.post("/api/inspect-excel")
async def inspect_excel(file: UploadFile = File(...)):
    """Quick read of an alert Excel for wizard pre-fill: distinct centres, how
    many days the timestamps span, and the date range. Never persists anything."""
    import shutil
    import tempfile
    from .ingest.excel import read_workbook
    tmp = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tf:
            shutil.copyfileobj(file.file, tf)
            tmp = Path(tf.name)
        centres, dates = set(), set()
        n, tmin, tmax = 0, None, None
        for a in read_workbook(tmp):
            n += 1
            if a.centre_code:
                centres.add(a.centre_code)
            if a.timestamp:
                dates.add(a.timestamp.date())
                tmin = a.timestamp if tmin is None or a.timestamp < tmin else tmin
                tmax = a.timestamp if tmax is None or a.timestamp > tmax else tmax
        return {"ok": True, "centres": len(centres), "alarms": n, "days": len(dates),
                "date_min": tmin.date().isoformat() if tmin else None,
                "date_max": tmax.date().isoformat() if tmax else None}
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": f"Could not read the Excel: {e}"}, status_code=400)
    finally:
        if tmp and tmp.exists():
            tmp.unlink()


@app.post("/api/exams/{code}/append")
async def append_exam(
    code: str,
    excel: UploadFile = File(...),
    evidence: list[UploadFile] = File(default=[]),
    evidence_path: str = Form(""),
    session: Session = Depends(get_session),
):
    """Merge a later shift/day's alert export (+ optional evidence) into an
    existing exam. Duplicate Alarm IDs are skipped, so it's safe to re-upload."""
    import re
    import shutil
    from .ingest.pipeline import append_to_exam

    exam = session.scalar(select(Exam).where(Exam.code == code))
    if not exam:
        return JSONResponse({"ok": False, "error": f"No examination '{code}'."}, status_code=404)

    updir = settings.data_dir / "uploads" / re.sub(r"[^A-Za-z0-9_-]+", "_", code)
    updir.mkdir(parents=True, exist_ok=True)
    xl = updir / ("append_" + Path(excel.filename or "more.xlsx").name)
    with xl.open("wb") as f:
        shutil.copyfileobj(excel.file, f)

    media = {".jpg", ".jpeg", ".png", ".mp4", ".mkv", ".avi", ".mov"}
    evroot = None
    p = Path(evidence_path.strip()).expanduser() if evidence_path.strip() else None
    if p and p.is_dir():
        evroot = p
    elif evidence:
        evdir = updir / "evidence"
        evdir.mkdir(exist_ok=True)
        saved = 0
        for uf in evidence:
            if not uf.filename or Path(uf.filename).suffix.lower() not in media:
                continue
            with (evdir / Path(uf.filename).name).open("wb") as f:
                shutil.copyfileobj(uf.file, f)
            saved += 1
        evroot = evdir if saved else None

    try:
        res = append_to_exam(session, exam=exam, excel_path=xl, evidence_root=evroot)
    except Exception as e:  # noqa: BLE001
        session.rollback()
        return JSONResponse({"ok": False, "error": f"Append failed: {e}"}, status_code=500)

    # a later file may carry earlier timestamps — keep the exam start date as the min
    mind = session.scalar(select(func.min(Alert.occurred_at)).where(Alert.exam_id == exam.id))
    if mind and (exam.exam_date is None or mind.date() < exam.exam_date):
        exam.exam_date = mind.date()
        session.commit()

    # a genuinely new modality in an appended file is adopted & rendered, not
    # dropped — surface which types were newly recognised
    new_mods = list(res.new_modalities.values())
    return {"ok": True, "code": code, "added": res.alert_count, "duplicates": res.duplicates,
            "evidence": res.evidence_linked, "total": exam.alert_count,
            "unmapped": sum(res.unmapped_channels.values()),
            "newModalities": new_mods}


@app.get("/api/exams/{code}/shifts")
def get_exam_shifts(code: str, date: str = "", session: Session = Depends(get_session)):
    exam = session.scalar(select(Exam).where(Exam.code == code))
    if not exam:
        return JSONResponse({"ok": False, "error": f"No examination '{code}'."}, status_code=404)
    from .compliance import get_shifts, configured_dates
    d = date.strip() or None
    return {"ok": True, "code": code, "date": d, "shifts": get_shifts(code, d),
            "configured_dates": configured_dates(code)}


@app.post("/api/exams/{code}/shifts")
async def set_exam_shifts(code: str, request: Request, session: Session = Depends(get_session)):
    """Set the authorised arrival + opening windows for an exam. Windows are numbered
    by time (earliest = Shift 1). A `date` scopes them to that day; without a date
    they become the exam default that every unconfigured day inherits."""
    import re as _re
    exam = session.scalar(select(Exam).where(Exam.code == code))
    if not exam:
        return JSONResponse({"ok": False, "error": f"No examination '{code}'."}, status_code=404)
    from .compliance import set_shifts
    body = await request.json()
    shifts = body.get("shifts") if isinstance(body, dict) else body
    date = (body.get("date") if isinstance(body, dict) else None) or None
    if date is not None:
        date = str(date).strip()
        if not _re.match(r"^\d{4}-\d{2}-\d{2}$", date):
            return JSONResponse({"ok": False, "error": "Date must be YYYY-MM-DD."}, status_code=400)

    def _ok(t: str) -> bool:
        return bool(_re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", (t or "").strip()))

    clean = []
    for i, sh in enumerate(shifts or []):
        try:
            arr = [str(sh["arrival"][0]).strip(), str(sh["arrival"][1]).strip()]
            opn = [str(sh["opening"][0]).strip(), str(sh["opening"][1]).strip()]
        except (KeyError, IndexError, TypeError, AttributeError):
            return JSONResponse({"ok": False, "error": f"Shift {i + 1}: missing arrival/opening times."}, status_code=400)
        if not all(_ok(x) for x in arr + opn):
            return JSONResponse({"ok": False, "error": f"Shift {i + 1}: times must be HH:MM (24-hour)."}, status_code=400)
        clean.append({"arrival": arr, "opening": opn})
    if not clean:
        return JSONResponse({"ok": False, "error": "At least one shift is required."}, status_code=400)

    # Shift identity is derived, never typed: order the day's shifts by arrival
    # time and number them — the earliest session is Shift 1, automatically.
    def _mins(t: str) -> int:
        h, m = t.split(":")
        return int(h) * 60 + int(m)

    clean.sort(key=lambda s: _mins(s["arrival"][0]))
    for i, s in enumerate(clean):
        s["name"] = f"Shift {i + 1}"
    set_shifts(code, clean, date=date)
    return {"ok": True, "code": code, "date": date, "shifts": clean}


@app.patch("/api/exams/{code}")
async def edit_exam(code: str, request: Request, session: Session = Depends(get_session)):
    """Edit an examination's editable details after creation: display name,
    session label, and — with full migration — the exam code.

    name/session are DB-only and always safe. The code is a key used in four
    external places (the shift-window store, the uploads folder, the evidence
    vault folder, and reportgen artefacts), so renaming it migrates every one of
    those, and refuses a code that already belongs to another exam.

    NOTE: exam_date is intentionally NOT editable here — it's derived from the
    earliest alert timestamp and re-derived on every append, so it stays a fact
    about the data rather than a typed-in value.
    """
    import json
    import re
    import shutil
    exam = _exam_or_404(session, code)
    body = await request.json()
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "Expected a JSON object."}, status_code=400)

    changed = []

    # --- name (free text, non-empty) ------------------------------------------
    if "name" in body:
        new_name = str(body["name"]).strip()
        if not new_name:
            return JSONResponse({"ok": False, "error": "Name cannot be empty."}, status_code=400)
        if new_name != exam.name:
            exam.name = new_name
            changed.append("name")

    # --- session label (free text, may be empty) ------------------------------
    if "session" in body:
        new_session = str(body["session"]).strip()
        if new_session != exam.session:
            exam.session = new_session
            changed.append("session")

    # --- code (unique key; migrate all external artefacts) --------------------
    if "code" in body:
        new_code = str(body["code"]).strip()
        if not new_code:
            return JSONResponse({"ok": False, "error": "Code cannot be empty."}, status_code=400)
        if not re.match(r"^[A-Za-z0-9 _-]{1,64}$", new_code):
            return JSONResponse(
                {"ok": False, "error": "Code may use letters, numbers, spaces, hyphens and underscores (max 64)."},
                status_code=400)
        if new_code != exam.code:
            clash = session.scalar(select(Exam).where(Exam.code == new_code, Exam.id != exam.id))
            if clash:
                return JSONResponse(
                    {"ok": False, "error": f"Another examination already uses the code '{new_code}'."},
                    status_code=409)

            old_code = exam.code
            slug = lambda c: re.sub(r"[^A-Za-z0-9_-]+", "_", c)

            # 1) shift-window store (trunk_windows.json) — keyed by exam code
            tw = settings.data_dir / "trunk_windows.json"
            if tw.exists():
                try:
                    cfg = json.loads(tw.read_text())
                    if old_code in cfg:
                        cfg[new_code] = cfg.pop(old_code)
                        tw.write_text(json.dumps(cfg, indent=2))
                except (ValueError, OSError):
                    pass

            # 2) uploads folder — named from a slug of the code
            up_old = settings.data_dir / "uploads" / slug(old_code)
            up_new = settings.data_dir / "uploads" / slug(new_code)
            if up_old.exists() and slug(old_code) != slug(new_code):
                try:
                    if up_new.exists():
                        for p in up_old.iterdir():
                            shutil.move(str(p), str(up_new / p.name))
                        shutil.rmtree(up_old, ignore_errors=True)
                    else:
                        shutil.move(str(up_old), str(up_new))
                except OSError:
                    pass

            # 3) evidence vault folder — evidence_dir / code — and rebase alert paths
            ev_old = (settings.evidence_dir / old_code)
            ev_new = (settings.evidence_dir / new_code)
            if ev_old.is_dir() and old_code != new_code:
                try:
                    if not ev_new.exists():
                        shutil.move(str(ev_old), str(ev_new))
                    old_root = str(ev_old.resolve())
                    new_root = str(ev_new.resolve())
                    for a in session.scalars(select(Alert).where(
                            Alert.exam_id == exam.id, Alert.evidence_image != "")).all():
                        if a.evidence_image.startswith(old_root):
                            a.evidence_image = new_root + a.evidence_image[len(old_root):]
                    if (exam.evidence_root or "").startswith(old_root):
                        exam.evidence_root = new_root + exam.evidence_root[len(old_root):]
                except OSError:
                    pass

            # 4) reportgen artefacts are keyed by exam.id (stable across rename) —
            #    nothing to migrate there.

            exam.code = new_code
            changed.append("code")

    if changed:
        session.commit()
    return {"ok": True, "code": exam.code, "name": exam.name,
            "session": exam.session, "changed": changed}


@app.delete("/api/exams/{code}")
def delete_exam(code: str, session: Session = Depends(get_session)):
    """Delete an examination and all its data (alerts, generated reports, uploads, windows)."""
    import json
    import re
    import shutil
    exam = _exam_or_404(session, code)
    eid = exam.id
    session.execute(sa_delete(Alert).where(Alert.exam_id == eid))
    session.delete(exam)
    session.commit()
    # best-effort cleanup of on-disk artefacts
    rg = settings.data_dir / "reportgen"
    if rg.exists():
        for p in rg.glob(f"{eid}_*"):
            shutil.rmtree(p, ignore_errors=True)
    shutil.rmtree(settings.data_dir / "uploads" / re.sub(r"[^A-Za-z0-9_-]+", "_", code), ignore_errors=True)
    tw = settings.data_dir / "trunk_windows.json"
    if tw.exists():
        try:
            cfg = json.loads(tw.read_text())
            if cfg.pop(code, None) is not None:
                tw.write_text(json.dumps(cfg, indent=2))
        except (ValueError, OSError):
            pass
    return {"ok": True}


@app.get("/exam/{code}", response_class=HTMLResponse)
def command_center(code: str, request: Request, session: Session = Depends(get_session)):
    exam = _exam_or_404(session, code)
    default_modality = session.scalar(
        select(Alert.modality_code).where(Alert.exam_id == exam.id)
        .group_by(Alert.modality_code).order_by(func.count(Alert.id).desc()).limit(1))
    # cache-bust static assets on every change so the browser never serves stale JS/CSS
    _st = Path(__file__).parent / "web" / "static"
    asset_v = int(max((p.stat().st_mtime for p in (_st / "command.js", _st / "command.css", _st / "app.css")), default=0))
    return TEMPLATES.TemplateResponse(
        request, "command.html", {"exam": exam, "default_modality": default_modality or "", "v": asset_v})


@app.get("/exam/{code}/m/{mcode}", response_class=HTMLResponse)
def modality_dashboard(code: str, mcode: str, request: Request,
                       session: Session = Depends(get_session)):
    exam = _exam_or_404(session, code)
    d = R.gather(session, exam.id, mcode, _modality_label(mcode))
    # per-minute series rebased to the active window for the template chart
    peak_hm = "--"
    if d.minute_series:
        start = (d.tmin.hour * 60 + d.tmin.minute) // 5 * 5
        end = (d.tmax.hour * 60 + d.tmax.minute + 4) // 5 * 5
        series = [d.minute_series.get(m, 0) for m in range(start, end + 1)]
        labels = [f"{m//60:02d}:{m%60:02d}" for m in range(start, end + 1) if m % 15 == 0]
        pm = max(d.minute_series, key=d.minute_series.get)
        peak_hm = f"{pm//60:02d}:{pm%60:02d}"
    else:
        series, labels = [], []
    stats = d.centre_stats
    is_count = d.mode == "count"
    metric_max = max((s.alerts if is_count else s.detections for s in stats), default=1)
    return TEMPLATES.TemplateResponse(request, "modality.html", {
        "exam": exam, "d": d, "series": series, "labels": labels,
        "series_max": max(series) if series else 1, "peak_hm": peak_hm,
        "worst_centre": stats[0] if stats else None,
        "worst_district": d.districts_ranked[0] if d.districts_ranked else None,
        "longest_run": max((s.longest_run_min for s in stats), default=0),
        "metric_max": metric_max, "is_count": is_count,
    })


@app.get("/api/exams/{code}/evidence-candidates")
def evidence_candidates(code: str, modality: str, session: Session = Depends(get_session)):
    """Ranked frames the report would consider, for operator one-by-one curation.
    Trunk -> off-window violations worst first; event -> worst centres' frames."""
    exam = _exam_or_404(session, code)
    codes = [c for c in modality.split(",") if c]
    out: list[dict] = []
    try:
        if codes and set(codes) <= {"TP", "TO"}:
            from . import compliance as C
            data = C.compute(session, exam)
            alarms = [e["alarm"] for e in data["queue"] if e.get("alarm")]
            haveimg = {a for a, in session.execute(
                select(Alert.alarm_id).where(Alert.exam_id == exam.id, Alert.alarm_id.in_(alarms),
                                             Alert.evidence_image != "")).all()}
            seen = set()
            for e in data["queue"]:
                if e["alarm"] not in haveimg or e["code"] in seen:
                    continue
                seen.add(e["code"])
                sgn = "+" if e["dev"] > 0 else "−"
                out.append({"alarm": e["alarm"], "centre": e["centre"], "code": e["code"],
                            "district": e["district"].title(), "modality": _modality_label("TP" if "arrival" in e["kind"].lower() else "TO"),
                            "sub": f'{e["kind"]} {sgn}{abs(e["dev"])}m · {e["actual"]}'})
        else:
            mcode = codes[0] if codes else ""
            from .reporting import centre_stats
            stats = centre_stats(session, exam.id, mcode)
            for cs in stats[:60]:
                a = session.scalar(
                    select(Alert).where(Alert.exam_id == exam.id, Alert.modality_code == mcode,
                                        Alert.centre_code == cs.centre_code, Alert.evidence_image != "")
                    .order_by(Alert.occurred_at))
                if not a:
                    continue
                out.append({"alarm": a.alarm_id, "centre": a.centre_name or a.centre_code,
                            "code": a.centre_code, "district": (a.district or "").title(),
                            "modality": _modality_label(mcode),
                            "sub": f'{a.zone or a.camera_name} · {R._ts(a.occurred_at)}'})
                if len(out) >= 40:
                    break
    except Exception as e:
        log.error("evidence-candidates failed for %s/%s: %s\n%s", code, modality, e, traceback.format_exc())
        raise HTTPException(500, f"Could not load evidence photos ({type(e).__name__}: {e}). Full details were printed to the server console window.")
    return {"candidates": out, "label": _modality_label(codes[0]) if codes else ""}


@app.get("/exam/{code}/report/{mcode}")
def download_report(code: str, mcode: str, photos: str = "", days: str = "",
                    session: Session = Depends(get_session)):
    exam = _exam_or_404(session, code)
    codes = [c for c in mcode.split(",") if c]
    pics = [p for p in photos.split(",") if p]
    day_list = [d for d in days.split(",") if d] or None
    try:
        if codes and set(codes) <= {"TP", "TO"}:
            # trunk modalities are a compliance archetype -> the window-compliance report
            from .report_render import generate_compliance_report_pdf
            pdf = generate_compliance_report_pdf(session, exam.id, photos=pics or None, days=day_list)
        elif len(codes) == 1:
            pdf = generate_report_pdf(session, exam.id, codes[0], _modality_label(codes[0]), photos=pics or None, days=day_list)
        else:
            from .report_render import generate_combined_report_pdf
            labels = {c: _modality_label(c) for c in codes}
            pdf = generate_combined_report_pdf(session, exam.id, codes, labels, days=day_list)
    except Exception as e:
        log.error("report generation failed for %s/%s: %s\n%s", code, mcode, e, traceback.format_exc())
        raise HTTPException(500, f"Report generation failed ({type(e).__name__}: {e}). Full details were printed to the server console window.")
    if not pdf.exists():
        raise HTTPException(500, "report generation failed")
    return FileResponse(pdf, media_type="application/pdf", filename=pdf.name)


@app.get("/exam/{code}/report/district/{district}")
def download_district_report(code: str, district: str, m: str = "",
                             session: Session = Depends(get_session)):
    exam = _exam_or_404(session, code)
    from .report_render import generate_district_report_pdf
    try:
        pdf = generate_district_report_pdf(session, exam.id, district, [c for c in m.split(",") if c])
    except Exception as e:
        log.error("district report generation failed for %s/%s: %s\n%s", code, district, e, traceback.format_exc())
        raise HTTPException(500, f"Report generation failed ({type(e).__name__}: {e}). Full details were printed to the server console window.")
    if not pdf.exists():
        raise HTTPException(500, "report generation failed")
    return FileResponse(pdf, media_type="application/pdf", filename=pdf.name)


@app.get("/exam/{code}/report/centre/{centre}")
def download_centre_report(code: str, centre: str, m: str = "",
                           session: Session = Depends(get_session)):
    exam = _exam_or_404(session, code)
    from .report_render import generate_centre_report_pdf
    try:
        pdf = generate_centre_report_pdf(session, exam.id, centre, [c for c in m.split(",") if c])
    except Exception as e:
        log.error("centre report generation failed for %s/%s: %s\n%s", code, centre, e, traceback.format_exc())
        raise HTTPException(500, f"Report generation failed ({type(e).__name__}: {e}). Full details were printed to the server console window.")
    if not pdf.exists():
        raise HTTPException(500, "report generation failed")
    return FileResponse(pdf, media_type="application/pdf", filename=pdf.name)


def _tier(run: int, count: int, is_count: bool) -> str:
    if is_count:
        return "r" if count >= 5 else "o" if count >= 2 else "y"
    return "r" if run >= 75 else "o" if run >= 45 else "y" if run >= 15 else "g"


_TIER_RANK = {"r": 0, "o": 1, "y": 2, "g": 3}
_TIER_LET = {0: "r", 1: "o", 2: "y", 3: "g"}


@app.get("/api/exams/{code}/board")
def board(code: str, modality: str, days: str = "", session: Session = Depends(get_session)):
    """Single or multi-modality board. `modality` may be comma-separated; the queue,
    timeline, districts and severity aggregate across the selected set. `days` is an
    optional comma-separated YYYY-MM-DD filter — empty means all exam days."""
    exam = _exam_or_404(session, code)
    reg = get_registry()
    codes = [c for c in modality.split(",") if c]
    day_list = [d for d in days.split(",") if d] or None

    # all exam days (unfiltered) — the selector chips always show the full set
    days_avail = [{"date": str(d), "count": n} for d, n in session.execute(
        select(func.date(Alert.occurred_at), func.count(Alert.id))
        .where(Alert.exam_id == exam.id, Alert.occurred_at.is_not(None))
        .group_by(func.date(Alert.occurred_at)).order_by(func.date(Alert.occurred_at))).all()]

    mod_rows = session.execute(
        select(Alert.modality_code, func.count(Alert.id))
        .where(Alert.exam_id == exam.id).group_by(Alert.modality_code)
    ).all()
    modalities = sorted(
        [{"code": c, "label": (reg.by_code(c).display_label if reg.by_code(c) else c),
          "count": n, "archetype": (reg.by_code(c).archetype if reg.by_code(c) else "event")}
         for c, n in mod_rows], key=lambda m: -m["count"])

    ds = [R.gather_cached(session, exam.id, c, _modality_label(c), days=day_list,
                          stamp=exam.alert_count or 0) for c in codes]
    single = len(ds) == 1

    cmap: dict[str, dict] = {}
    for d in ds:
        is_count = d.mode == "count"
        for s in d.centre_stats:
            c = cmap.setdefault(s.centre_code, {
                "code": s.centre_code, "name": s.centre_name, "district": s.district,
                "alerts": 0, "tr": 3, "run": 0, "detections": 0, "mods": []})
            c["alerts"] += s.alerts
            c["run"] = max(c["run"], s.longest_run_min)
            c["detections"] += s.detections
            t = _tier(s.longest_run_min, s.alerts, is_count)
            c["tr"] = min(c["tr"], _TIER_RANK[t])
            c["mods"].append({"code": d.code, "label": d.label, "alerts": s.alerts, "tier": t,
                              "run": s.longest_run_min, "detections": s.detections, "mode": d.mode})
    # within a tier, rank by the metric the queue actually shows: sustained run
    # for a single sustained modality, alert count otherwise. (Keeps the visible
    # column monotonic — a 30-min centre never sits below a 15-min one.)
    sustained_single = single and ds[0].mode != "count"
    centres = sorted(
        cmap.values(),
        key=(lambda c: (c["tr"], -c["run"], -c["alerts"])) if sustained_single
        else (lambda c: (c["tr"], -c["alerts"], -c["run"])))
    for c in centres:
        c["tier"] = _TIER_LET[c["tr"]]
        del c["tr"]

    # trunk modalities are a compliance archetype: per-centre deviation from the
    # authorised arrival/opening window is the meaningful metric, not "longest run".
    if "TP" in codes or "TO" in codes:
        from . import compliance as C
        devs = C.centre_deviations(session, exam, day_list)
        for c in centres:
            d = devs.get(c["code"], {})
            # attach BOTH checkpoints so arrival and opening are shown consistently
            # (opening is None -> "—" when the export has no Trunk-Open events)
            c["arrDev"] = d.get("arr")
            c["opnDev"] = d.get("opn")

    dmap: dict[str, int] = {}
    for c in centres:
        if c["district"]:
            dmap[c["district"]] = dmap.get(c["district"], 0) + c["alerts"]
    districts = sorted(([k, v] for k, v in dmap.items()), key=lambda x: -x[1])[:16]

    ms: dict[int, int] = {}
    for d in ds:
        for k, v in d.minute_series.items():
            ms[k] = ms.get(k, 0) + v
    tmins = [d.tmin for d in ds if d.tmin]
    tmaxs = [d.tmax for d in ds if d.tmax]
    tmin, tmax = (min(tmins) if tmins else None), (max(tmaxs) if tmaxs else None)
    if ms and tmin and tmax:
        start = (tmin.hour * 60 + tmin.minute) // 5 * 5
        end = (tmax.hour * 60 + tmax.minute + 4) // 5 * 5
        series = [ms.get(m, 0) for m in range(start, end + 1)]
        labels = [f"{m//60:02d}:{m%60:02d}" for m in range(start, end + 1) if m % 15 == 0]
        pm = max(ms, key=ms.get)
        peak_hm = f"{pm//60:02d}:{pm%60:02d}"
    else:
        series, labels, peak_hm = [], [], "--"

    total = sum(d.total for d in ds)
    label = ds[0].label if single else f"{len(ds)} modalities"
    distinct_districts = len({c["district"] for c in centres if c["district"]})
    state = session.scalar(
        select(Alert.state).where(Alert.exam_id == exam.id, Alert.state != "").limit(1)) or ""

    return {
        "exam": {"code": exam.code, "name": exam.name, "state": state,
                 "session": exam.session,
                 "date": exam.exam_date.strftime("%d %b %Y") if exam.exam_date else ""},
        "modalities": modalities, "selected": codes, "single": single,
        "label": label, "isCount": single and ds[0].mode == "count",
        "mode": ds[0].mode if single else "mixed",
        "distLabel": "alerts",
        "kpis": {"total": total, "centres": len(centres), "districts": distinct_districts,
                 "cameras": sum(d.cameras for d in ds),
                 "window": f"{tmin.strftime('%H:%M') if tmin else '--'}–{tmax.strftime('%H:%M') if tmax else '--'}"},
        "timeline": {"series": series, "labels": labels,
                     "max": max(series) if series else 1, "peak": peak_hm},
        "districts": districts, "centres": centres,
        "worstDistrict": districts[0] if districts else None,
        "worstCentre": centres[0] if centres else None,
        "longestRun": max((c["run"] for c in centres), default=0),
        "roster": _roster_coverage(session, exam.id),
        "days": days_avail,
        "daysSelected": day_list or [d["date"] for d in days_avail],
    }


def _roster_coverage(session: Session, exam_id: int) -> dict | None:
    """Coverage against the true centre total: how many reported >=1 alert and how
    many stayed silent. Prefers an uploaded official roster (names the silent
    centres); falls back to the operator-entered total (count only). None if
    neither is set."""
    from .models import OfficialCentre
    acodes = {r[0] for r in session.execute(
        select(Alert.centre_code).where(Alert.exam_id == exam_id, Alert.centre_code != "").distinct()).all()}
    roster = session.execute(
        select(OfficialCentre.centre_code, OfficialCentre.centre_name, OfficialCentre.district)
        .where(OfficialCentre.exam_id == exam_id)).all()
    if roster:
        rcodes = {r[0] for r in roster}
        silent = sorted(({"code": c, "name": n, "district": d} for c, n, d in roster if c not in acodes),
                        key=lambda x: (x["district"], x["name"]))
        return {"total": len(rcodes), "reported": len(rcodes & acodes),
                "silentN": len(silent), "silent": silent[:200]}
    ex = session.get(Exam, exam_id)
    total = ex.centre_total if ex else 0
    if total and total > 0:
        reported = len(acodes)
        return {"total": total, "reported": min(reported, total),
                "silentN": max(0, total - reported), "silent": []}
    return None


@app.get("/api/exams/{code}/map")
def board_map(code: str, modality: str, session: Session = Depends(get_session)):
    """State-aware India district choropleth for the selected modalities."""
    from fastapi.responses import Response
    from . import geo
    exam = _exam_or_404(session, code)
    codes = [c for c in modality.split(",") if c]
    rows = session.execute(
        select(Alert.state, Alert.district, func.count(Alert.id))
        .where(Alert.exam_id == exam.id, Alert.modality_code.in_(codes), Alert.district != "")
        .group_by(Alert.state, Alert.district)
    ).all()
    values = {(st, d): n for st, d, n in rows}
    # light=True: every report already passes it; the portal's own map was the
    # last caller left on the dark path, which is why it rendered as a black
    # landmass with a red glow on a cream page.
    svg = geo.choropleth(values, width=820, height=560, label_top=6, light=True)
    return Response(svg, media_type="image/svg+xml")


@app.get("/api/bodies")
def known_bodies(session: Session = Depends(get_session)):
    """Bodies already in use, so the wizard suggests rather than asks blind."""
    rows = session.scalars(
        select(Exam.body).where(Exam.body != "").group_by(Exam.body).order_by(func.count(Exam.id).desc())).all()
    return {"bodies": list(rows)}


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
