"""Validate the generated report against the source Excel, claim by claim."""
import collections, datetime, sys
sys.path.insert(0, r'C:\Users\yash.chaudhary\camviewportal\backend')
import openpyxl
from sqlalchemy import select
from app.db import SessionLocal
from app.models import Exam, Alert
from app import report_render as RR, comparison_report as CMP

XL = r'C:\Users\yash.chaudhary\Downloads\UPSSSC DEMO TRUE ALERT REPORT 24-AUG-2026 (3).xlsx'

# ---------------------------------------------------------------- ground truth
ws = openpyxl.load_workbook(XL, read_only=True, data_only=True)['Alarms']
rows = [r for r in ws.iter_rows(values_only=True)][1:]
rows = [r for r in rows if r and r[11]]


def ts(x):
    for f in ('%d/%m/%Y, %I:%M:%S %p', '%d/%m/%Y, %H:%M:%S'):
        try:
            return datetime.datetime.strptime(str(x).replace(' am', ' AM').replace(' pm', ' PM'), f)
        except ValueError:
            pass


truth_total = len(rows)
truth_types = collections.Counter(r[8] for r in rows)
truth_centres = {str(r[1]).strip() for r in rows}
truth_districts = {str(r[3]).strip() for r in rows}


def true_peak(times, span=15):
    """Same definition the report should use: busiest span-minute window."""
    mins = collections.Counter(t.hour * 60 + t.minute for t in times)
    if not mins:
        return None, 0
    lo, hi = min(mins), max(mins)
    best = (lo, -1)
    for s in range(lo, hi + 1):
        n = sum(mins.get(m, 0) for m in range(s, s + span))
        if n > best[1]:
            best = (s, n)
    return f"{best[0]//60:02d}:{best[0]%60:02d}", best[1]


times_by_type = collections.defaultdict(list)
for r in rows:
    t = ts(r[7])
    if t:
        times_by_type[r[8]].append(t)

# ---------------------------------------------------------------- what the app says
s = SessionLocal()
e = s.scalar(select(Exam).where(Exam.code == 'UPSSSC'))
codes = [c for c, in s.execute(select(Alert.modality_code).where(Alert.exam_id == e.id)
                               .group_by(Alert.modality_code))]
profs, code_of_prof = [], []
for c in codes:
    d = RR.R.gather(s, e.id, c, c)
    profs.append(RR._profile(d))
    code_of_prof.append(c)

# the Excel's alarm-type string -> the modality code the app assigned it.
# Taken from the ingested rows, so it reflects what the app actually did rather
# than a mapping I guessed.
type_to_code = {}
for raw, mc in s.execute(select(Alert.alarm_type_raw, Alert.modality_code)
                         .where(Alert.exam_id == e.id).group_by(Alert.alarm_type_raw, Alert.modality_code)):
    type_to_code[str(raw).strip()] = mc
by_code = dict(zip(code_of_prof, profs))

fails = []


def check(name, got, want):
    ok = got == want
    print(f"  {'PASS' if ok else 'FAIL'}  {name:38} report={got!r:>22}  excel={want!r}")
    if not ok:
        fails.append(name)


print("=" * 96)
print("TOTALS")
check("total alerts", sum(p['total'] for p in profs), truth_total)
check("distinct centres", len({x for p in profs for x in p['centre_codes']}), len(truth_centres))
check("distinct districts", len({d for p in profs for d, _ in p['dist']}), len(truth_districts))
crit = len({x for p in profs for x in p['crit_codes']})
print(f"  {'INFO'}  {'critical centres (deduplicated)':38} report={crit!r:>22}  "
      f"(cannot exceed {len(truth_centres)} centres)")
if crit > len(truth_centres):
    fails.append("critical centres exceeds centre count")

print()
print("PER-MODALITY ALERT COUNTS")
for typ, n in truth_types.most_common():
    mc = type_to_code.get(typ)
    p = by_code.get(mc)
    if p is None:
        print(f"  SKIP  {typ:38} (unmapped: code={mc!r})")
        continue
    check(f"{typ} [{mc}]", p['total'], n)

print()
print("PEAK WINDOW  (report caption says 'in the busiest 15 min')")
for typ, times in sorted(times_by_type.items(), key=lambda kv: -len(kv[1])):
    p = by_code.get(type_to_code.get(typ))
    if p is None:
        continue
    want_hm, want_n = true_peak(times)
    got_hm, got_n = p['peak_hm'], p['peak_v']
    ok = got_n == want_n
    print(f"  {'PASS' if ok else 'FAIL'}  {typ:32} report={got_hm} x{got_n:<3}   excel={want_hm} x{want_n}")
    if not ok:
        fails.append(f"peak {typ}")

print()
print("=" * 96)
print(f"{len(fails)} FAILING CHECK(S)" if fails else "ALL CHECKS PASS")
for f in fails:
    print("   -", f)
