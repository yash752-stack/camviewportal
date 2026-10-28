"""Check a CamView alert export before (or instead of) loading it.

    python tools/validate_excel.py "path/to/export.xlsx" [more.xlsx ...] [--exam CODE] [--json out.json]

Prints what is wrong with the file (errors, warnings, notes) and how the portal
will read it: exam windows, alerts per shift before/during/after the exam,
priority mix, exam-window swing by alert type, trunk compliance on the relative
rule and the unusual centres. --exam uses the exam windows already confirmed
for that exam in the portal. Exit code 1 when the file has errors.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))

from app.validation import as_text, validate_workbook  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--exam", default=None, help="use the exam windows confirmed for this exam code")
    ap.add_argument("--json", type=Path, default=None, help="also write the full result as JSON")
    a = ap.parse_args()
    res = validate_workbook(a.files, code=a.exam)
    print(as_text(res))
    if a.json:
        a.json.write_text(json.dumps(res, indent=2, default=str))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
