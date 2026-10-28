"""The operations-review reading rules (backend/app/exam_rules.py)."""
from datetime import datetime, timedelta

import pytest

from app import exam_rules as X


def rec(code, t, *, centre="C1", cam="cam1", zone="CLASS ROOM", stage=None, aid=[0]):
    aid[0] += 1
    st = stage or {"INM": "during", "CHT": "during", "MPS": "during", "TP": "pre", "TO": "pre"}.get(code, "whole")
    h, m = t.split(":")
    return X.Rec(alarm_id=f"A{aid[0]}", code=code, label=code, stage=st, severity="Low",
                 centre_code=centre, centre_name=centre, district="D", zone=zone, camera=cam,
                 ts=datetime(2026, 6, 30, int(h), int(m)))


def inm_block(start, end, step=5, centre="C1", cam="cam1"):
    t = datetime(2026, 6, 30, *map(int, start.split(":")))
    e = datetime(2026, 6, 30, *map(int, end.split(":")))
    out = []
    while t <= e:
        out.append(rec("INM", t.strftime("%H:%M"), centre=centre, cam=cam))
        t += timedelta(minutes=step)
    return out


def test_priority_thresholds():
    assert X.priority_of(10) == "High" and X.priority_of(25) == "High"
    assert X.priority_of(9) == "Medium" and X.priority_of(5) == "Medium"
    assert X.priority_of(4) == "Low" and X.priority_of(1) == "Low"


def test_windows_from_inm_two_shifts_rounded_out():
    recs = inm_block("09:07", "11:52") + inm_block("14:33", "17:21")
    ws = X.infer_windows(recs)
    assert [(X.hm(w.start), X.hm(w.end), w.source) for w in ws] == [
        ("09:00", "12:00", "inm"), ("14:30", "17:30", "inm")]


def test_stray_inm_is_noise():
    recs = [rec("INM", "07:40")] + inm_block("09:00", "11:55")
    ws = X.infer_windows(recs)
    assert len(ws) == 1 and X.hm(ws[0].start) == "09:00"


def test_no_inm_falls_back_to_density():
    recs = [rec("CD", f"10:{m:02d}") for m in range(0, 50, 5)]
    ws = X.infer_windows(recs)
    assert ws and ws[0].source == "density"


def test_phases_and_shift_boundaries():
    recs = inm_block("09:00", "11:55") + inm_block("14:30", "17:25") + [
        rec("TP", "07:40"), rec("TP", "12:40"), rec("CHT", "13:10"), rec("CD", "17:45")]
    ws = X.infer_windows(recs)
    X.assign(recs, ws)
    by = {r.alarm_id: r for r in recs}
    tp1, tp2, cht, late = recs[-4:]
    assert (tp1.shift, tp1.phase) == (1, "pre")
    assert (tp2.shift, tp2.phase) == (2, "pre")          # Shift 2 starts where Shift 1's window ends
    assert (cht.shift, cht.phase) == (2, "pre") and not cht.in_scope   # cheating outside the window: off-hours
    assert (late.shift, late.phase) == (2, "post")
    assert by[recs[0].alarm_id].phase == "exam"


def test_priority_is_per_camera_type_and_shift():
    recs = inm_block("09:00", "11:55")
    recs += [rec("ZI", f"10:{m:02d}", cam="gate", zone="ENTRY EXIT") for m in range(0, 50, 5)]   # 10 fires
    recs += [rec("ZI", "10:30", cam="gate2", zone="ENTRY EXIT")]
    X.assign(recs, X.infer_windows(recs))
    zi = [r for r in recs if r.code == "ZI"]
    assert {r.priority for r in zi if r.camera == "gate"} == {"High"}
    assert [r.priority for r in zi if r.camera == "gate2"] == ["Low"]
    assert {r.priority_count for r in zi if r.camera == "gate"} == {10}


def test_trunk_windows_relative_to_start():
    w = X.Window(datetime(2026, 6, 30).date(), 1, 9 * 60, 12 * 60, "configured")
    assert X.trunk_windows(w) == {"name": "Shift 1", "arrival": ["07:30", "08:15"], "opening": ["08:45", "09:00"]}


def test_trunk_compliance_classifies_and_ignores_pre_arrival_open():
    recs = inm_block("09:00", "11:55")
    recs += [rec("TO", "07:40", centre="A"), rec("TP", "07:50", centre="A"), rec("TO", "08:50", centre="A"),
             rec("TP", "08:40", centre="B"), rec("TO", "09:20", centre="B"),
             rec("TP", "07:00", centre="C")]
    ws = X.infer_windows(recs)
    X.assign(recs, ws)
    t = {r["centre"]: r for r in X.trunk_compliance(recs, ws)}
    assert t["A"]["arrival"]["status"] == "ok" and t["A"]["opening"]["status"] == "ok"
    assert t["A"]["opening"]["at"].startswith("08:50")       # the 07:40 open precedes the arrival: box handling, ignored
    assert t["B"]["arrival"]["status"] == "late" and t["B"]["opening"]["status"] == "late"
    assert t["C"]["arrival"]["status"] == "early" and t["C"]["opening"]["status"] == "none"


def test_window_check_flags_late_inm_start():
    recs = inm_block("09:35", "11:30")
    recs += [rec("TO", "08:5" + str(i), centre=f"K{i}") for i in range(5)]
    ws = X.infer_windows(recs)
    X.assign(recs, ws)
    checks = X.window_checks(recs, ws)
    assert len(checks) == 1 and checks[0]["suggested_start"] == "09:00"


def test_outliers_mean_plus_minus_one_sd():
    o = X.outliers({"a": 1, "b": 1, "c": 1, "d": 1, "e": 30, "f": 0})
    assert o["high"] == ["e"]
    assert X.outliers({"a": 2, "b": 2})["high"] == []        # no spread, nothing flagged


@pytest.mark.parametrize("n,k", [(5, 5), (10, 10), (100, 10), (250, 13), (1042, 53)])
def test_top_k_is_top_ten_or_five_percent(n, k):
    assert X.top_k(n) == k


def test_swing():
    assert X.swing(10, 15) == 50 and X.swing(6, 1) == -83 and X.swing(0, 4) is None and X.swing(0, 0) == 0


def test_risk_overlap_same_centre_within_window():
    recs = inm_block("09:00", "11:55")
    recs += [rec("ZI", "10:00", zone="ENTRY EXIT"), rec("CT", "10:20"), rec("ZI", "11:00", zone="ENTRY EXIT"),
             rec("CD", "11:10", zone="CONTROL ROOM"), rec("CT", "10:20", centre="OTHER")]
    X.assign(recs, X.infer_windows(recs))
    r = X.risk_overlaps(recs, "ZI")
    ct = next(x for x in r["rules"] if x["other"] == "CT")
    cd = next(x for x in r["rules"] if x["other"] == "CD")
    assert r["total"] == 2 and ct["hits"] == 1 and cd["hits"] == 1


def test_cheating_with_stationary_invigilator_same_room():
    recs = inm_block("09:00", "11:55", cam="room7") + [rec("CHT", "10:02", cam="room7"), rec("CHT", "10:02", cam="room9")]
    X.assign(recs, X.infer_windows(recs))
    inm = next(x for x in X.risk_overlaps(recs, "CHT")["rules"] if x["other"] == "INM")
    assert inm["hits"] == 1


def test_analyse_shapes_and_exam_window_only_comparisons():
    recs = inm_block("09:00", "11:55") + inm_block("14:30", "17:25")
    recs += [rec("TP", "07:40"), rec("MD", "10:00"), rec("MD", "15:00"), rec("MD", "15:10"), rec("MD", "13:00")]
    out = X.analyse(recs, X.infer_windows(recs))
    md = next(f for f in out["features"] if f["code"] == "MD")
    assert md["alerts"] == [1, 2] and md["swing"] == 100      # the 13:00 setup-time alert is not compared
    assert all(f["code"] != "TP" for f in out["features"])    # pre-exam models are not on the exam clock
    assert out["summary"][0]["pre"] == 1
    assert {"windows", "clock", "heat", "unusual", "priority", "trunk", "analysis", "rules"} <= set(out)
