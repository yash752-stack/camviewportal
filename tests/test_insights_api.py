"""End to end: ingest a small export, stamp it, read it back through the API."""
from fastapi.testclient import TestClient

from app import auth, exam_rules as X
from app.db import SessionLocal, init_db
from app.ingest.pipeline import ingest_exam
from app.main import app
from app.models import Alert, Exam
from test_validation import base_rows, book, row


def test_ingest_insights_and_confirm_windows(tmp_path):
    init_db()
    rs = base_rows() + [
        row(200, "3", "Trunk Placed", "30/6/2026, 7:45:00", zone="CONTROL ROOM"),
        row(201, "4", "Trunk Opened", "30/6/2026, 8:50:00", zone="CONTROL ROOM"),
        row(202, "17", "Cheating Detection", "30/6/2026, 10:00:00"),
    ] + [row(300 + i, "2", "Zone Intrusion", f"30/6/2026, 10:{i:02d}:00", zone="ENTRY EXIT", cam="gate")
         for i in range(12)]
    p = book(tmp_path, rs)
    with SessionLocal() as s:
        res = ingest_exam(s, code="T-API", name="Test", exam_date=None, excel_path=p, evidence_root=None)
        exam = s.get(Exam, res.exam_id)
        X.refresh_exam(s, exam)
        zi = s.query(Alert).filter_by(exam_id=exam.id, modality_code="ZI").all()
        assert {a.priority for a in zi} == {"High"} and {a.priority_count for a in zi} == {12}
        cht = s.query(Alert).filter_by(exam_id=exam.id, channel="17").one()
        assert cht.modality_code == "CHT" and cht.severity == "Critical" and cht.phase == "exam"
    assert X.load_windows("T-API")["2026-06-30"]["source"] == "inm"

    with TestClient(app) as c:
        c.cookies.set(auth.COOKIE, auth.issue("admin"))
        j = c.get("/api/exams/T-API/insights").json()
        assert j["windows"][0]["start"] == "09:00" and j["summary"][0]["total"] == len(rs)
        assert c.get("/exam/T-API/insights").status_code == 200
        bad = c.post("/api/exams/T-API/windows", json={"windows": [{"date": "2026-06-30", "start": "11:00", "end": "10:00"}]})
        assert bad.status_code == 400
        ok = c.post("/api/exams/T-API/windows", json={"windows": [{"date": "2026-06-30", "start": "09:30", "end": "12:00"}]})
        assert ok.json()["ok"] and ok.json()["windows"][0]["source"] == "configured"
        sh = c.get("/api/exams/T-API/shifts").json()["shifts"]
        assert sh[0]["opening"] == ["09:15", "09:30"]          # trunk rule follows the confirmed start
        with open(p, "rb") as f:
            v = c.post("/api/validate-excel", files=[("files", ("a.xlsx", f))], data={"exam": "T-API"}).json()
        assert v["ok"] and v["numbers"]["windows"][0]["source"] == "configured"
        assert c.delete("/api/exams/T-API").json()["ok"]
    assert X.load_windows("T-API") == {}
