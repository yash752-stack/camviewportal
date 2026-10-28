"""The time-of-day clock page and the report's last page."""
from app import clock_chart as K, exam_rules as X, iv_paper
from app.db import SessionLocal, init_db
from app.ingest.pipeline import ingest_exam
from app.models import Exam
from test_validation import base_rows, book, row


def test_clock_counts_exam_window_slots_and_leaves_setup_out(tmp_path):
    init_db()
    rs = base_rows() + [row(400, "1", "Crowd Detection", "30/6/2026, 7:45:00", zone="ENTRY EXIT"),
                        row(401, "1", "Crowd Detection", "30/6/2026, 10:10:00", zone="ENTRY EXIT")]
    with SessionLocal() as s:
        res = ingest_exam(s, code="T-CLK", name="T", exam_date=None, excel_path=book(tmp_path, rs), evidence_root=None)
        exam = s.get(Exam, res.exam_id)
        X.refresh_exam(s, exam)
        d = K.time_of_day(s, exam, ["CD"])
        assert d["by"] == "centre" and len(d["shifts"]) == 1
        sh = d["shifts"][0]
        assert sh["label"] == "9:00 AM to 12:00 PM" and len(sh["slots"]) == 6
        assert sh["total"] == 1 and sh["setup"] == 1 and sh["peak_at"] == "10:00 AM"
        body = K.page_body(d, "Crowd Formation")
        assert "<svg" in body and "<line" in body and "1 before Shift 1" in body
        assert K.time_of_day(s, exam, ["MD"]) is None          # nothing on the clock, no page


def test_report_has_no_credits_only_last_page():
    html = iv_paper.document("", ['<section class="page">content</section>'],
                             iv_paper.cover("Exam", "Report", "sub", ["30 June 2026"]))
    assert 'class="page back"' not in html
    assert html.rfind("<section") == html.find("content") - len('<section class="page">')
