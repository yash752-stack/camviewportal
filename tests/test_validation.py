"""The Excel validation check on small hand-made workbooks."""
from pathlib import Path

import openpyxl

from app.validation import as_text, validate_workbook

HEAD = ["S.no", "Center Code", "Center Name", "District/City", "State", "Camera Name",
        "Camera Sub Location", "Alert Timestamp (IST)", "Alarm Type", "Ticket ID", "DSS ID", "Alarm ID"]


def book(tmp_path: Path, rows, head=HEAD) -> Path:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Alarms"
    ws.append(head)
    for r in rows:
        ws.append(r)
    p = tmp_path / "alerts.xlsx"
    wb.save(p)
    return p


def row(i, ch, label, t, centre="47001", zone="CLASS ROOM", cam="1000_1"):
    return [i, centre, "Some College", "LUCKNOW", "Uttar Pradesh", cam, zone, t, label, "", "1000",
            f"C-1-{ch}-1788091186684-{i}"]


def base_rows():
    rs = []
    for i, m in enumerate(range(0, 175, 5)):
        h, mm = divmod(9 * 60 + m, 60)
        rs.append(row(i + 1, "12", "Inv Not Moving", f"30/6/2026, {h}:{mm:02d}:00"))
    return rs


def test_clean_file_reads_with_numbers(tmp_path):
    res = validate_workbook(book(tmp_path, base_rows()))
    assert res["ok"] and res["numbers"]["alerts"] == 35
    assert res["numbers"]["windows"][0]["start"] == "09:00"
    assert "HOW THE PORTAL READS IT" in as_text(res)


def test_missing_column_is_an_error(tmp_path):
    head = [h for h in HEAD if h != "Alarm Type"]
    res = validate_workbook(book(tmp_path, [r[:8] + r[9:] for r in base_rows()], head=head))
    assert not res["ok"] and any(f["check"] == "columns" for f in res["findings"])


def test_duplicates_bad_times_label_clash_and_new_types(tmp_path):
    rs = base_rows()
    rs.append(rs[0])                                                    # duplicate Alarm ID
    rs.append(row(90, "12", "Inv Not Moving", "yesterday"))             # unreadable time
    rs.append(row(91, "14", "Zone Intrusion", "30/6/2026, 10:00:00"))   # label says ZI, channel says Mobile
    rs.append(row(92, "99", "Laser Detection", "30/6/2026, 10:00:00"))  # unknown model
    rs.append(row(93, "2", "Zone Intrusion", "30/6/2026, 10:05:00"))    # ZI from a class room camera
    rs.append([94, "", "x", "LUCKNOW", "", "", "", "30/6/2026, 10:00:00", "Inv Not Moving", "", "", "C-1-12-1-94"])
    checks = {f["check"]: f for f in validate_workbook(book(tmp_path, rs))["findings"]}
    assert checks["duplicates"]["count"] == 1
    assert checks["timestamps"]["count"] == 1
    assert "channel 14" in checks["label_vs_channel"]["text"]
    assert "Laser Detection" in checks["new_type"]["text"]
    assert checks["location"]["count"] == 1
    assert checks["dropped_rows"]["count"] == 1
