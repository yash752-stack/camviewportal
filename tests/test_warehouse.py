"""Warehouse (procurement centre) alerts and the exam-details table."""
from datetime import datetime

from fastapi.testclient import TestClient

from app import auth, exam_rules as X
from app.db import SessionLocal, init_db
from app.ingest.pipeline import ingest_exam
from app.main import app
from app.models import Alert, Exam
from app.registry import get_registry, is_warehouse_site
from app.validation import validate_workbook
from test_exam_rules import inm_block, rec
from test_validation import base_rows, book, row


def wh(code, t, centre="PC-01", cam="PC-01_C1", zone="WH STORAGE AREA"):
    r = rec(code, t, centre=centre, cam=cam, zone=zone, stage="whole")
    r.sector = "warehouse"
    return r


def test_warehouse_site_and_resolution():
    reg = get_registry()
    assert is_warehouse_site("WH Entry / Exit") and is_warehouse_site("", "PC-04")
    assert not is_warehouse_site("ENTRY EXIT", "47066")
    assert reg.resolve("2", "Zone Intrusion", "WH Entry / Exit", "PC-01").code == "PB"
    assert reg.resolve("1", "Crowd Detection", "WH Other Area", "PC-01").code == "WC"
    assert reg.resolve("2", "Zone Intrusion", "ENTRY EXIT", "47066").code == "ZI"
    # a warehouse label beats an exam channel on a warehouse camera, not elsewhere
    assert reg.resolve("3", "Stack Height Exceeded", "WH Storage Area", "PC-02").code == "SHE"
    assert reg.resolve("3", "Stack Height Exceeded", "CONTROL ROOM", "47001").code == "TP"
    she = reg.by_code("SHE")
    assert she.sector == "warehouse" and she.stage == "whole" and reg.by_code("ZI").sector == "exam"


def test_warehouse_counts_whole_shift_and_stays_out_of_exam_views():
    recs = inm_block("09:00", "11:55") + inm_block("14:30", "17:25") + [
        rec("CD", "07:30", zone="ENTRY EXIT"),                 # exam, before the window: not compared
        wh("SHE", "07:10"), wh("SOR", "07:25"),                # warehouse, before the window: compared
        wh("VD", "13:00", zone="WH ENTRY EXIT"),
    ]
    ws = X.infer_windows(recs)
    out = X.analyse(recs, ws)
    feats = {f["code"]: f for f in out["features"]}
    assert feats["SHE"]["alerts"] == [1, 0] and feats["SHE"]["sector"] == "warehouse"
    assert feats["CD"]["alerts"] == [0, 0]
    assert feats["VD"]["alerts"] == [0, 1]                  # 1 PM falls in Shift 2
    assert out["centre_split"] == {"exam": 1, "warehouse": 1} and out["has_warehouse"]
    assert all(c["code"] != "PC-01" for s in out["concentration"].values() for c in s["ranked"])
    assert all(not z["zone"].startswith("WH") for z in out["scorecard"])
    she = next(b for b in out["analysis"] if b["code"] == "SHE")
    assert she["off_hours"] == [0, 0] and she["sector"] == "warehouse"
    assert she["risk"]["rules"][0]["other"] == "SOR" and she["risk"]["rules"][0]["hits"] == 1
    assert out["summary"][0]["warehouse"] == 2


def test_validation_reads_warehouse_rows(tmp_path):
    rs = base_rows() + [
        row(500, "2", "Zone Intrusion", "30/6/2026, 9:30:00", centre="PC-01", zone="WH Entry / Exit", cam="PC-01_C1"),
        row(501, "3", "Stack Height Exceeded", "30/6/2026, 9:40:00", centre="PC-01", zone="WH Storage Area", cam="PC-01_C2"),
    ]
    res = validate_workbook(book(tmp_path, rs))
    checks = {f["check"] for f in res["findings"]}
    assert {"warehouse_twin", "warehouse_label"} <= checks and "label_vs_channel" not in checks
    assert res["numbers"]["warehouse_alerts"] == 2 and res["numbers"]["centre_split"]["warehouse"] == 1


def test_warehouse_only_day_is_not_an_inm_warning(tmp_path):
    rs = [row(600 + i, "", "Vehicle Detection", f"30/6/2026, {8 + i // 6}:{(i % 6) * 10:02d}:00",
              centre="PC-02", zone="WH Entry / Exit") for i in range(24)]
    res = validate_workbook(book(tmp_path, rs))
    checks = {f["check"] for f in res["findings"]}
    assert "no_inm" not in checks and "warehouse_only" in checks


def test_details_and_summary_table(tmp_path):
    init_db()
    rs = base_rows()
    for r in rs[:10]:
        r[9] = f"TK{r[0]}"                                      # ten alerts carry a ticket
    rs.append(row(700, "", "Fire and Smoke Detection", "30/6/2026, 10:05:00", centre="PC-03", zone="WH Other Area"))
    p = book(tmp_path, rs)
    with SessionLocal() as s:
        res = ingest_exam(s, code="T-WH", name="Test WH", exam_date=None, excel_path=p, evidence_root=None)
        X.refresh_exam(s, s.get(Exam, res.exam_id))
        fsd = s.query(Alert).filter_by(exam_id=res.exam_id, modality_code="FSD").one()
        assert fsd.severity == "Critical"
    with TestClient(app) as c:
        c.cookies.set(auth.COOKIE, auth.issue("admin"))
        assert c.post("/api/exams/T-WH/details", json={"candidates": {"1": "abc"}}).status_code == 400
        ok = c.post("/api/exams/T-WH/details", json={"exam_type": "Competitive", "post": "Assistant Professor",
                                                      "stage": "Prelims", "candidates": {"1": "2,376"},
                                                      "cameras_scheduled": {"1": 99}, "tickets_resolved": {"1": 7}})
        assert ok.json()["details"]["candidates"] == {"1": 2376}
        j = c.get("/api/exams/T-WH/insights").json()
        t = {r["key"]: r for r in j["summary_table"]}
        assert t["candidates"]["by_shift"] == [2376] and t["cameras_scheduled"]["by_shift"] == [99]
        assert t["alerts"]["by_shift"] == [len(rs)] and t["tickets_created"]["by_shift"] == [10]
        assert t["tickets_open"]["by_shift"] == [3] and t["cameras_alerting"]["both"] is None
        assert j["details"]["post"] == "Assistant Professor" and j["has_tickets"]
        assert c.delete("/api/exams/T-WH").json()["ok"]
    assert X.load_details("T-WH") == {}
